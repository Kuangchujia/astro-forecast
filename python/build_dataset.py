#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量数据集构建：把 compute_sky.py 的单日计算跑成可导入的数据集。

分工：天文量一律由 compute_sky.py 计算（唯一权威 API）；本文件只负责
      「区间遍历 / 并行调度 / 落盘 NDJSON / 事件集装配 / manifest / REST 推送」。

产物（均写入 --outdir，默认 <仓库根>/data）：
  daily_<起始年>.ndjson   日记录，每行一条，键与 REST daily 白名单一致
  events_future.json      未来事件数组（真枚举，见下）
  events_historical.json  历史事件数组（人工条目表，未核录者为草稿）
  manifest.json           本次构建元信息

★ v1.1.0：未来事件**不再输出空数组**。事件枚举已由同目录 event_almanac.py 提供
  （求根引擎 + 七个生成器 + slug 去重），本文件只负责「定区间 → 取事件 → 装配行」。
  红线沿袭：**不编造事件** —— 某类型一件都没有，就让它空着（前台该 Tab 显示「暂无」），
  绝不为「让 Tab 有内容」而生成占位事件。

字段口径、生成与推送命令见 data/README.md。
"""

import argparse
import json
import math
import multiprocessing as mp
import os
import re
import shutil
import sys
import tempfile
import time
from datetime import date, datetime, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(_HERE)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import compute_sky  # noqa: E402  （同目录，权威计算内核）
import event_almanac as ea  # noqa: E402  （同目录，事件枚举：求根 + slug 去重 + 行装配）

SCRIPT_VERSION = "1.1.0"
DEFAULT_OUTDIR = os.path.join(REPO_ROOT, "data")

# REST 列白名单的**现场判据**：插件端 rest-import.php 的 kcj_astro_rest_columns()。
# 服务端会丢弃白名单外的键，故客户端多写无益；下面的常量仅为读不到该文件时的兜底副本。
REST_PHP = os.path.join(REPO_ROOT, "wp-astro-forecast", "includes", "rest-import.php")
REST_WHITELIST_FALLBACK = {
    "daily": ("date_str", "jd", "data_json", "data_version", "method"),
    "events": ("event_id", "event_type", "jd_core", "event_time_bj",
               "time_uncertainty", "dt_model", "post_id", "title", "slug",
               "summary", "params_json", "obs_guide", "obs_site", "literature",
               "discussion", "source_ref", "method", "ephemeris", "publish_status"),
    "relations": ("from_event", "to_event", "rel_type"),
}

# -----------------------------------------------------------------------------
# 人工条目表 —— **数据在 data/events_manual.json，不在本文件里**。
#   v1.0.0 曾把两条占位条目硬编码在此（HISTORICAL_ENTRIES）。移出去的理由：
#   ① 史料是**数据**，改条目不该改代码、不该重跑语法检查；
#   ② 代码里的常量无法承载「出处／核录状态」这类需要逐条审计的字段；
#   ③ 本文件是**流水线**，不是内容仓库 —— 分工即边界。
#   表结构与规则见 data/events_manual.json 的 kind_doc / red_line / publish_rule。
# -----------------------------------------------------------------------------
MANUAL_ENTRIES_PATH = os.path.join(REPO_ROOT, "data", "events_manual.json")


class ManualEntryError(ValueError):
    """人工条目表不合规 —— 硬错，不落库（宁可不出，不可出错）。"""


def load_manual_entries(path=MANUAL_ENTRIES_PATH):
    """读人工条目表。返回 (entries, 来源说明)。文件不存在＝空表（合法）。

    ★ 为什么文件不存在算合法：本表是**增量**的 —— 一条史料都没整理好时，
      流水线照样要能跑完（事件主体由 event_almanac 枚举）。但**格式错**必须硬报错，
      否则「表里写错了」会表现成「表里没这条」，静默丢内容。
    """
    if not os.path.isfile(path):
        return [], "无（%s 不存在 ⇒ 空表）" % os.path.relpath(path, REPO_ROOT)
    with open(path, encoding="utf-8") as f:
        try:
            obj = json.load(f)
        except Exception as e:
            raise ManualEntryError("人工条目表不是合法 JSON：%s" % e)
    if not isinstance(obj, dict) or not isinstance(obj.get("entries"), list):
        raise ManualEntryError("人工条目表顶层须是对象，且含 entries 数组")
    entries = obj["entries"]
    seen = set()
    for i, ent in enumerate(entries, 1):
        if not isinstance(ent, dict):
            raise ManualEntryError("第 %d 条不是对象" % i)
        kind = ent.get("kind")
        if kind not in ("historical", "catalog"):
            raise ManualEntryError("第 %d 条 kind 须为 historical 或 catalog（得到 %r）"
                                   % (i, kind))
        slug = str(ent.get("slug") or "").strip()
        if not slug:
            raise ManualEntryError("第 %d 条缺 slug（slug 是 REST 的幂等键，不可省）" % i)
        if slug in seen:
            raise ManualEntryError("第 %d 条 slug 重复：%s" % (i, slug))
        seen.add(slug)
        if kind == "historical":
            for k in ("era_year", "month", "day", "calendar_note",
                      "source_text", "source_ref"):
                if ent.get(k) in (None, ""):
                    raise ManualEntryError("第 %d 条（historical/%s）缺 %s" % (i, slug, k))
        else:  # catalog
            for k in ("jd_core", "title", "source_ref"):
                if ent.get(k) in (None, ""):
                    raise ManualEntryError("第 %d 条（catalog/%s）缺 %s" % (i, slug, k))
            if not ent.get("event_type"):
                raise ManualEntryError("第 %d 条（catalog/%s）缺 event_type" % (i, slug))
    return entries, "现场读取 %s（%d 条）" % (os.path.relpath(path, REPO_ROOT), len(entries))

# VARCHAR 列宽上限（见 sql/install_tables.sql）：超长会被截断，故先按列宽裁剪。
# ★ 注释里的「实测」是 2026-09-23 用真数据跑出的最长值；**列宽必须 ≥ 实测**，
#   否则服务端 MySQL 会直接拒行（回执 written:0 / failed:1），而不是截断——见 F22。
# ★ v1.2.1 修正：`data_version` v1.2.0 **根本没列进来** ⇒ 既不裁剪、又超列宽（36/45 > 32），
#   线上首推 1 行全部失败；`dt_model` 列了 32，但真实值是 36 ⇒ 会被**静默截断**，溯源失真。
# ★★ v2.2.6 续（2026-09-23 · **实测**）：上表的数字单位是「**字节**」，不是「字符」。
#   依据：v2.2.6 信标 `cols` 段直采到线上列定义 —— **所有字符串列的字符集都是
#   `latin1_swedish_ci`**；而 WordPress 的 `strip_invalid_text()`（wp-includes/class-wpdb.php）
#   对「latin1 字符集」**一律按字节**判长度（`strlen`/`substr`，不是 `mb_strlen`）。
#   ⇒ **中文每字 3 字节，一个 varchar(32) 的中文列实际只装得下 10 个字**。
#   F27 就是在这里翻的车：`time_uncertainty` 真值 60 字符 / **159 字节**，
#   而当时按**字符**判「60 ≤ 64 合规」，上线后被数据库按**字节**全数拒收（4,672 行）。
#   ⇒ 本表的语义自此统一为字节，**裁剪与判据都必须按字节**。

COL_MAXLEN = {
    # ★ v2.2.6：原写 64，注释里的「实测 37」是**更早一版文案**的长度 —— 判据拿旧样本定值，
    #   于是真值涨到 60 字符 / **159 字节**时没人发现（F27）。现按真值放到 191：
    #   191 ≥ 159 字节且 ≥ 60 字符，**字符与字节两种口径同时通过**。
    "time_uncertainty": 191,  # 实测 60 字符 / 159 字节（±数小时（极大时刻为 λ☉ 锚点下的**理论值**…））
    "dt_model": 64,           # 实测 36：de421+dt_espenak_meeus_2006+tt_scale
    "data_version": 64,       # 实测 45：同上 + "+analytic"（解析降级行）
    # ★ v2.2.6：原写 96，只按「de421.bsp（…）」这一条（40 字节）定值；
    #   降级态的「未使用（de421.bsp（…） 覆盖之外，已降级为 Meeus 解析式）」是 59 字符 / **99 字节**
    #   ⇒ 96 装不下。这一条是 v2.2.6 新的**双口径判据**当场揪出来的（属 F27 同类·潜伏）。
    "ephemeris": 191,         # 实测 59 字符 / 99 字节（含覆盖外降级态文案）
    "method": 32,             # 实测 15：ephemeris_de421
}


# ============================== 小工具 ==============================
def load_rest_whitelist():
    """返回 (白名单 dict, 来源说明)。优先现场解析插件 PHP，失败则用兜底常量。"""
    try:
        with open(REST_PHP, encoding="utf-8") as f:
            text = f.read()
        table = {}
        for key in REST_WHITELIST_FALLBACK:
            m = re.search(r"'%s'\s*=>\s*array\(([^)]*)\)" % key, text)
            if not m:
                raise ValueError("PHP 中未找到表 %s 的列定义" % key)
            table[key] = tuple(re.findall(r"'([^']+)'", m.group(1)))
        return table, "现场解析 %s" % os.path.relpath(REST_PHP, REPO_ROOT)
    except Exception as e:
        return dict(REST_WHITELIST_FALLBACK), "兜底常量（读取 PHP 失败：%s）" % e


def load_event_types():
    """返回 (规范 event_type 集合, 来源说明) —— 现场解析插件 cpt.php 的单一真值源。

    ★ 为什么要现场解析而不是写死常量：`event_type` 的规范取值由插件
      `kcj_astro_event_types()` 定义，同时决定前台的 Tab 分组与分类法 term。
      客户端写死一份副本，两边就会各自漂移（本项目已因「两份正本不一致」踩过 F23）。
      解析失败则返回 None，调用方**跳过**该判据并出声明（而不是当成通过）。
    """
    cpt = os.path.join(REPO_ROOT, "wp-astro-forecast", "includes", "cpt.php")
    try:
        with open(cpt, encoding="utf-8") as f:
            text = f.read()
        m = re.search(r"function\s+kcj_astro_event_types\s*\(\s*\)\s*\{.*?return\s+array\((.*?)\);",
                      text, re.S)
        if not m:
            raise ValueError("cpt.php 中未找到 kcj_astro_event_types 的返回数组")
        return set(re.findall(r"'([a-z_]+)'\s*=>", m.group(1))), \
            "现场解析 %s" % os.path.relpath(cpt, REPO_ROOT)
    except Exception as e:
        return None, "未取到（读取 cpt.php 失败：%s）" % e


# ★ v1.2.1：裁剪日志。`_clip` 一旦真的截断，就把事实记下来。
#   裁剪**永远不该发生**——它意味着列宽装不下真值，属于静默数据失真
#   （v1.2.0 线上就是这么丢掉 data_version 的溯源信息的）。故构建期自检断言本表为空，
#   把「列宽够不够」的判据放在**裁剪的上游**，而不是裁剪之后（后者恒真，形同虚设）。
CLIP_LOG = []


def _utf8_len(s):
    """字符串的 **UTF-8 字节数**（列宽的真实口径，见上方说明）。"""
    return len(s.encode("utf-8"))


def _utf8_clip(s, n):
    """把 s 截到 **≤ n 字节**，且**落在 UTF-8 字符边界**上（不产生半个汉字）。

    ★ 为什么不能用 `s[:n]`：那是**按字符**截 —— 中文每字 3 字节 ⇒ 21 个汉字就 63 字节，
      早已越过 varchar(64) 的字节上限，而 `s[:64]` 会安然放行 64 个汉字（192 字节）。
      这正是 F27 的同族：**上游按字符放行、下游按字节拒收**。
    """
    b = s.encode("utf-8")
    if len(b) <= n:
        return s
    return b[:n].decode("utf-8", "ignore")


def _clip(s, key):
    """按目标列宽（**字节**）裁剪字符串；None 原样返回。真的裁剪会记入 CLIP_LOG。

    ★ v2.2.6 续：原实现用 `len(s)`（字符）与 `s[:n]`（字符切片）——
      **对中文等于把上限放大 3 倍**，是 F27 的上游同族缺陷。现按字节。
    """
    if s is None:
        return None
    n = COL_MAXLEN.get(key)
    if n is not None and _utf8_len(s) > n:
        CLIP_LOG.append({"key": key, "bytes": _utf8_len(s), "chars": len(s),
                         "maxlen": n, "head": s[:40]})
        return _utf8_clip(s, n)
    return s


def _write_json(path, obj):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def _iter_days(start, end):
    """YYYY-MM-DD 区间（含两端）逐日产出 (y, m, d)。"""
    cur, last = date.fromisoformat(start), date.fromisoformat(end)
    while cur <= last:
        yield cur.year, cur.month, cur.day
        cur += timedelta(days=1)


# ---------------------------------------------------------------- 独立校核算式
# ★ 这三件是**校验专用**：故意不复用 compute_sky / event_almanac 的任何换算函数。
#   理由：若校验与生成共用同一段代码，判据恒真（本项目在 F25 已吃过一次）。
#   本文件自己按 Meeus 的公历公式算 JD，用固定 TT−UTC 常数，形成**第二条路**。
_TT_MINUS_UTC_SEC = 69.184      # 32.184 s（力学时差）+ 37 s（闰秒，2017 年起）


def _jd_utc_from_dt(d):
    """公历年月日时分秒 → 儒略日（UT 尺度）。Meeus《Astronomical Algorithms》ch.7 公历式。"""
    y, m = d.year, d.month
    frac = (d.hour + d.minute / 60.0 + d.second / 3600.0) / 24.0
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return (math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1))
            + d.day + frac + b - 1524.5)


_SLUG_DATE_RE = re.compile(r"(\d{8})(?:-\d+)?$")


def _slug_date_matches(slug, bj_str):
    """slug 末尾的 YYYYMMDD 是否等于北京日期串的 Y-M-D。"""
    m = _SLUG_DATE_RE.search(str(slug))
    if not m or not bj_str:
        return False
    return m.group(1) == str(bj_str)[:10].replace("-", "")


# ============================== 单日：并行调度 ==============================
def daily_worker(task):
    """单日计算（模块级函数，供 multiprocessing 序列化）。异常不走崩，转为失败行。"""
    y, m, d, city, tz, eph, allow = task
    try:
        return compute_sky.compute_daily(y, m, d, city=city, tz_hours=tz,
                                         ephemeris=eph, allow_analytic=allow)
    except Exception as e:
        return {"date_str": "%04d-%02d-%02d" % (y, m, d), "method": "error",
                "_error": "%s: %s" % (type(e).__name__, e)}


def _run_tasks(tasks, jobs):
    """按序产出（imap 保序，故输出天然按日期递增）。jobs<=1 时单进程直跑。"""
    if jobs and jobs > 1 and len(tasks) > 1:
        with mp.Pool(jobs) as pool:
            for rec in pool.imap(daily_worker, tasks, chunksize=8):
                yield rec
    else:
        for tk in tasks:
            yield daily_worker(tk)


def _daily_row(rec):
    """抽取 REST daily 白名单内的 5 个键；其余键服务端会丢弃，故不写。

    ★ v1.2.1：`data_version` / `method` 也走 _clip —— v1.2.0 这两个是「裸写」，
      其中 data_version 实测 45 > 列宽 32 ⇒ 被 MySQL 拒收（F22）。
    """
    return {
        "date_str": rec["date_str"],
        "jd": rec["jd"],
        "data_json": json.dumps(rec, ensure_ascii=False),
        "data_version": _clip(rec["data_version"], "data_version"),
        "method": _clip(rec["method"], "method"),
    }


def build_daily(args, outdir, tasks, allow):
    path = os.path.join(outdir, "daily_%s.ndjson" % args.start[:4])
    stats = {"path": path, "rows": 0, "ok": 0, "degraded": 0, "failed": 0, "errors": []}
    t0 = time.time()
    print("[build_dataset] 日记录 -> %s（%d 天，jobs=%d）" % (path, len(tasks), args.jobs),
          file=sys.stderr)
    with open(path, "w", encoding="utf-8", newline="\n") as f:   # newline="\n"：强制 LF
        for rec in _run_tasks(tasks, args.jobs):
            stats["rows"] += 1
            if "_error" in rec:
                stats["failed"] += 1
                stats["errors"].append({"date_str": rec.get("date_str"), "error": rec["_error"]})
            else:
                f.write(json.dumps(_daily_row(rec), ensure_ascii=False) + "\n")
                if rec["method"] == "ephemeris_de421":
                    stats["ok"] += 1
                else:
                    stats["degraded"] += 1
            if stats["rows"] % 200 == 0 or stats["rows"] == len(tasks):
                print("  ... %d/%d（精算 %d / 降级 %d / 失败 %d，用时 %.1fs）"
                      % (stats["rows"], len(tasks), stats["ok"], stats["degraded"],
                         stats["failed"], time.time() - t0), file=sys.stderr)
    stats["elapsed_sec"] = round(time.time() - t0, 3)
    return stats


def _read_ndjson(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                rows.append(json.loads(ln))
    return rows


# ============================== 事件集 ==============================
class EmptyEventSet(RuntimeError):
    """事件枚举产出 0 条 —— 视为缺陷，不写空文件。"""


def _guard_events(rows, allow_empty, scope):
    """★ 空集守卫：事件数为 0 必须报错，**不得静默写空文件**。

    为什么必须是硬错而不是警告：空数组写进 events_future.json 后，前台六个 Tab 会
    一起显示「该类型暂无已发布事件」，而**没人知道是「真没有」还是「枚举崩了」**
    —— 早先版本的「结构空集」就是这个形态，一直没人报错。
    本判据放在**写文件之前**，故不会留下半成品。
    """
    if rows or allow_empty:
        return
    raise EmptyEventSet(
        "事件集为空（%s）：枚举没产出任何事件。空数组会被前台渲染成「暂无」，"
        "与「真的没有」无法区分，故拒绝写出。确需空集请显式加 --allow-empty-events。"
        % scope)


def _apply_publish_window(rows, publish_from):
    """按发布窗口筛行：北京日期 < publish_from 的**不落地**。返回 (保留, 剔除数)。

    ★ 为什么需要它：前台 `[astro_forecast_list]` 的 SQL 是
      `WHERE event_type=%s AND publish_status=1 ORDER BY jd_core ASC`（无「仅未来」条件，
      见 includes/shortcodes.php）。它叫**天象预告**，若把已过去的事件也标为已发布，
      读者打开页面第一眼看到的就是年初的天象 —— 页面立刻显得过期。
    ★ 为什么不改成 publish_status=0 留档：那会在 WP 后台堆一批「已过期」草稿 CPT，
      同样污染事件列表；而**枚举本身可随时重跑**，过窗口的行没有留档的必要。
      故选择「不落地」，并把 cutoff 与剔除条数如实记进 manifest（可审计）。
    """
    if not publish_from:
        return list(rows), 0
    kept = [r for r in rows if str(r.get("event_time_bj") or "")[:10] >= publish_from]
    return kept, len(rows) - len(kept)


def build_future(outdir, eph, y0, y1, kinds=None, allow_unverified=False,
                 allow_empty=False, publish_from=None, verbose=True):
    """未来事件数组 —— 真调 event_almanac 枚举，装配成 REST events 白名单行。

    分工：本文件**不**做天文求根（那是 event_almanac + compute_sky 的职责），
          只把区间与生成器选择传下去，再把结果写成文件。

    区间口径：生成器按**北京时间年份**收口（跨年夜的月食在 TT 与北京时下可能差一天，
    标题／slug／event_time_bj／分年四处必须同一口径，见 event_almanac.build_events）。
    发布窗口：`publish_from`（YYYY-MM-DD）之前的行不落地，见 _apply_publish_window。
    """
    path = os.path.join(outdir, "events_future.json")
    events, stat = ea.build_events(y0, y1, eph=eph, which=kinds,
                                  allow_unverified=allow_unverified, verbose=verbose)
    rows = ea.to_rows(events, publish_status=1)
    rows, dropped = _apply_publish_window(rows, publish_from)
    stat["publish_from"] = publish_from
    stat["dropped_before_window"] = dropped
    # ★ 守卫在**写盘之前**：装到后面就会留下一个空数组文件，而那是谁也不会报错的静默失败。
    _guard_events(rows, allow_empty, "区间 %d—%d（发布窗口起 %s）" % (y0, y1, publish_from))
    _write_json(path, rows)
    return path, rows, stat


def _manual_row_historical(ent, ephemeris, allow):
    """史料型条目 → 一行。回推一律走 compute_sky.back_calc_historical()。"""
    era_year = compute_sky.parse_era_year(ent["era_year"])
    hist = compute_sky.back_calc_historical(
        era_year, int(ent["month"]), int(ent["day"]),
        ent["calendar_note"], ent["source_text"], ent["source_ref"],
        ephemeris=ephemeris, allow_analytic=allow)
    calc = hist["calc"]
    phases = calc.get("nearest_phases") or []
    # jd_core 取模块算出的「最近朔/望」时刻（历史食类条目的关键量）；
    # 无相位结果时退回查询时刻，并在 params_json 里标明来源。
    if phases:
        jd_core, jd_src = phases[0]["jd_tt"], "calc.nearest_phases[0].jd_tt"
    else:
        jd_core, jd_src = calc["jd_query_tt"], "calc.jd_query_tt"
    verified = bool(ent.get("verified"))
    params = {
        "placeholder": not verified,
        "verified": verified,
        "note": ("结构样例：日期为占位值，未指向任何具体史料；待人工补录并核录后置 verified=true。"
                 if not verified else
                 "已人工核录（verified=true）。文献原文与出处见 literature / source_ref。"),
        "jd_core_source": jd_src,
        "entry": {"era_year_input": ent["era_year"], "month": ent["month"],
                  "day": ent["day"]},
        "chronology": hist["chronology"],
        "calc": calc,
    }
    return {
        "event_type": "historical",
        "jd_core": jd_core,
        "event_time_bj": None,
        "title": ent.get("title") or "TODO-人工补录（历史条目结构样例）",
        "slug": ent["slug"],
        "summary": ent.get("summary") or "TODO-人工补录",
        "params_json": json.dumps(params, ensure_ascii=False),
        "method": _clip(calc["method"], "method"),
        "ephemeris": _clip(calc["ephemeris"], "ephemeris"),
        "publish_status": 1 if (verified and int(ent.get("publish_status", 0)) == 1) else 0,
        "literature": ent.get("literature") or ent.get("source_text"),
        "discussion": ent.get("discussion") or hist["discussion"],
        "source_ref": ent["source_ref"],
        "time_uncertainty": _clip(calc["time_uncertainty"], "time_uncertainty"),
        "dt_model": _clip(calc["dt_model"], "dt_model"),
    }


def _manual_row_catalog(ent):
    """目录型条目 → 一行（照录，不算）。

    ★ event_time_bj **由 jd_core 格式化得出，不取条目里的手填值** ——
      否则「jd_core」与「展示时刻」两个口径会各自漂移，正是本项目在
      时刻尺度上反复踩过的坑（见 event_almanac 模块 docstring「时刻口径」）。
    """
    jd = float(ent["jd_core"])
    jd_bj = ea._jd_bj_str(jd)      # 与事件枚举同一条转换路径（TT → 北京时间）
    verified = bool(ent.get("verified"))
    params = dict(ent.get("params") or {})
    params.setdefault("verified", verified)
    params.setdefault("criterion", "人工目录型条目：数值为权威照录，非本库自算")
    return {
        "event_type": ent["event_type"],
        "jd_core": round(jd, 6),
        "event_time_bj": jd_bj,
        "title": ent["title"],
        "slug": ent["slug"],
        "summary": ent.get("summary") or "",
        "params_json": json.dumps(params, ensure_ascii=False, sort_keys=True),
        "obs_guide": ent.get("obs_guide"),
        "obs_site": ent.get("obs_site"),
        "literature": ent.get("literature"),
        "discussion": ent.get("discussion"),
        "source_ref": ent["source_ref"],
        "method": ent.get("method") or "catalog_manual",
        "ephemeris": ent.get("ephemeris"),
        "time_uncertainty": ent.get("time_uncertainty"),
        "dt_model": ent.get("dt_model"),
        "publish_status": 1 if (verified and int(ent.get("publish_status", 0)) == 1) else 0,
    }


def build_historical(outdir, entries, ephemeris, allow):
    """人工条目表 → events 白名单行，写 events_historical.json。

    两类条目各自的装配见 _manual_row_historical / _manual_row_catalog。
    行内只放白名单键；只做**逐字净化**（``ea.to_rows`` 的 ``_plain`` 规则），不改写内容。

    ★ 推送策略由调用方决定：slug 以 ``todo-`` 开头者默认不推（见 pushable_events）。
      已核录（verified=true）的真史料不受此限。
    """
    path = os.path.join(outdir, "events_historical.json")
    rows = []
    for ent in entries:
        if ent["kind"] == "historical":
            rows.append(_manual_row_historical(ent, ephemeris, allow))
        else:
            rows.append(_manual_row_catalog(ent))
    # 再过一次明文净化（与枚举事件同一出口规则）：WP 端 esc_html 直出，
    # 任何 `**粗体**` 都只会示人两个星号。
    rows = [dict(r, **{k: ea._plain(v) for k, v in r.items() if isinstance(v, str)})
            for r in rows]
    _write_json(path, rows)
    n_ph = sum(1 for r in rows if r["slug"].startswith("todo-"))
    n_pub = sum(1 for r in rows if int(r["publish_status"]) == 1)
    return path, rows, n_ph, n_pub


def pushable_events(rows, push_placeholders=False):
    """过滤出可推送的事件行。

    ★ 占位条目（slug 以 `todo-` 开头）默认不发 —— 见 build_historical 的说明。
      判据用 slug 前缀而不是 `publish_status`：占位件是草稿，但**草稿也可能是真条目**
      （史料未核录完的条目就该以草稿形态存在），故「是不是占位」必须看 slug 约定。
    """
    if push_placeholders:
        return list(rows)
    return [r for r in rows if not str(r.get("slug", "")).startswith("todo-")]


# ============================== 主流程 ==============================
def _events_years(args):
    """事件区间年份：显式 --events-range 优先，否则由 --start/--end 的年份推出。

    ★ 为什么事件区间与日记录区间**分开**：日记录是逐日的（区间短则快），
      而事件枚举是**整年粗扫 + 求根**（最小有意义单位是一年）。若硬绑 --start/--end，
      「只想试 3 天日记录」会顺带跑一整年天象枚举，把快速自测拖到 20 秒。
    """
    if args.events_range:
        return int(args.events_range[0]), int(args.events_range[1])
    return int(args.start[:4]), int(args.end[:4])


def run_build(args):
    outdir = os.path.abspath(args.outdir)
    os.makedirs(outdir, exist_ok=True)
    try:
        days = list(_iter_days(args.start, args.end))
    except ValueError as e:
        print("[build_dataset] 日期格式须为 YYYY-MM-DD：%s" % e, file=sys.stderr)
        return 2
    if args.start[:4] != args.end[:4] and not args.events_only:
        print("[build_dataset] 注意：区间跨年，日记录仍写单文件 daily_%s.ndjson" % args.start[:4],
              file=sys.stderr)
    if args.limit is not None:
        days = days[:max(0, args.limit)]
    if not days and not args.events_only:
        print("[build_dataset] 无待算日期（--limit 过小或区间为空）", file=sys.stderr)
        return 2

    eph = compute_sky.load_ephemeris(args.ephemeris)
    jd_lo, jd_hi, win_desc = compute_sky.ephemeris_window(eph, args.ephemeris)
    # 星历覆盖外是否降级：不给 --allow-analytic 时沿用 compute_sky 的默认
    # （CONFIG.ANALYTIC_FALLBACK = True），加了即显式声明同一行为。
    allow = True if args.allow_analytic else None
    tasks = [(y, m, d, args.city, args.tz, args.ephemeris, allow) for (y, m, d) in days]

    daily = build_daily(args, outdir, tasks, allow) if not args.events_only else None
    fut_path, fut_rows, fut_stat = None, [], None
    hist_path, hist_rows, hist_placeholders, hist_published = None, [], 0, 0
    ev_y0 = ev_y1 = None      # 事件区间年份；--daily-only 时不定义
    manual_src = "未读取"
    if not args.daily_only:
        ev_y0, ev_y1 = _events_years(args)
        if ev_y0 > ev_y1:
            print("[build_dataset] --events-range 起始年不得大于结束年：%d > %d"
                  % (ev_y0, ev_y1), file=sys.stderr)
            return 2
        kinds = [k.strip() for k in (args.event_kinds or "").split(",") if k.strip()] or None
        if kinds:
            unknown = [k for k in kinds if k not in ea.GENERATORS]
            if unknown:
                print("[build_dataset] --event-kinds 含未知生成器 %s（可用：%s）"
                      % (unknown, ",".join(ea.GENERATORS)), file=sys.stderr)
                return 2
        try:
            fut_path, fut_rows, fut_stat = build_future(
                outdir, eph, ev_y0, ev_y1, kinds=kinds,
                allow_unverified=args.allow_unverified_events,
                allow_empty=args.allow_empty_events,
                publish_from=args.publish_from)
        except ea.EmptyEventSet as e:
            print("[build_dataset] %s" % e, file=sys.stderr)
            return 2
        # —— 人工条目表：格式错即硬停，不静默降级成「表里没这条」 ——
        try:
            manual, manual_src = load_manual_entries(args.manual_entries)
        except ManualEntryError as e:
            print("[build_dataset] 人工条目表不合规，已停：%s" % e, file=sys.stderr)
            return 2
        hist_path, hist_rows, hist_placeholders, hist_published = build_historical(
            outdir, manual, args.ephemeris, allow)

    # 可推送事件 = 未来事件 + 历史事件（占位件默认剔除，见 pushable_events）
    all_ev = list(fut_rows) + list(hist_rows)
    if args.push_placeholders:
        ev_rows, ev_skipped = all_ev, 0
    else:
        ev_rows = pushable_events(all_ev)
        ev_skipped = len(all_ev) - len(ev_rows)

    # —— 推送（--dry-run 只统计，不发任何请求）——
    push_info = {"enabled": bool(args.push), "dry_run": bool(args.dry_run)}
    push_info["events_planned"] = len(ev_rows)
    push_info["events_skipped_placeholder"] = ev_skipped
    if args.dry_run:
        push_info["planned_daily_rows"] = (daily["ok"] + daily["degraded"]) if daily else 0
        push_info["planned_event_rows"] = len(ev_rows)
        push_info["note"] = ("dry-run：仅统计行数，未发起任何推送；占位条目 %d 条不计入"
                             % ev_skipped)
    elif args.push:
        if not args.wp_user or not args.wp_app_password:
            print("[build_dataset] --push 需要 --wp-user 与 --wp-app-password", file=sys.stderr)
            return 2
        try:
            if daily:
                rows = _read_ndjson(daily["path"])
                if args.table != "daily":
                    print("[build_dataset] 注意：日记录将写入表 %s" % args.table, file=sys.stderr)
                push_info["daily_pushed"] = compute_sky.push_rest(
                    rows, args.table, args.wp_site, args.wp_user, args.wp_app_password)
            if ev_rows:
                # ★ 事件批比日记录小得多：服务端每写一行事件都会同步建/更新一篇
                #   CPT 文章（rest-import.php → kcj_astro_sync_event_to_post），
                #   200 行/批等于一个请求里做 200 次 wp_insert_post + 分类法赋值，
                #   很容易撞上 wp.com 的请求时限。25 行/批把单请求工作量压到可控，
                #   且写失败是**按 slug 幂等**的，重跑即可补齐。
                push_info["events_pushed"] = compute_sky.push_rest(
                    ev_rows, "events", args.wp_site, args.wp_user, args.wp_app_password,
                    batch=args.events_batch)
            push_info["cache_flush"] = compute_sky.flush_remote_cache(
                args.wp_site, args.wp_user, args.wp_app_password)
        except Exception as e:
            push_info["error"] = str(e)
            print("[build_dataset] 推送失败：%s" % e, file=sys.stderr)

    # —— manifest（推送之后写，以便如实记录推送结果）——
    _, wl_src = load_rest_whitelist()
    manifest = {
        "script": "python/build_dataset.py",
        "script_version": SCRIPT_VERSION,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "range": {"start": args.start, "end": args.end, "limit": args.limit},
        "daily": None if not daily else {
            "file": os.path.basename(daily["path"]),
            "rows_written": daily["ok"] + daily["degraded"],
            "ok_ephemeris": daily["ok"],
            "degraded_analytic": daily["degraded"],
            "failed": daily["failed"],
            "errors_sample": daily["errors"][:20],
            "elapsed_sec": daily["elapsed_sec"],
            "rows_per_sec": round((daily["rows"] / daily["elapsed_sec"]), 3)
                            if daily["elapsed_sec"] else None,
        },
        "events": {
            "future_file": os.path.basename(fut_path) if fut_path else None,
            "future_count": len(fut_rows),
            "future_by_type": None if fut_stat is None else fut_stat["by_type"],
            "future_by_generator": None if fut_stat is None else fut_stat["counts"],
            "future_range_years": None if fut_stat is None else [ev_y0, ev_y1],
            "publish_from": None if fut_stat is None else fut_stat.get("publish_from"),
            "dropped_before_window": None if fut_stat is None else fut_stat.get("dropped_before_window"),
            "slug_conflicts": None if fut_stat is None else len(fut_stat["slug_conflicts"]),
            "historical_file": os.path.basename(hist_path) if hist_path else None,
            "historical_count": len(hist_rows),
            "historical_placeholders": hist_placeholders,
            "historical_published": hist_published,
            "manual_entries_source": manual_src,
            "pushed_rows": len(ev_rows),
            "skipped_placeholders": ev_skipped,
            "enumerator": ("event_almanac v%s（求根引擎 + 七个生成器：%s）"
                           % (ea.SCRIPT_VERSION, ",".join(ea.GENERATORS))),
            "status": ("enumerated" if fut_rows else "empty"),
            "note": ("未来事件由 event_almanac.py 真枚举产出（区间按**北京时间年份**收口）。"
                     "红线：不编造事件 —— 某类型一件都没有就让它空着。"
                     "**发布窗口**：早于 publish_from 的行不落地（前台预告列表按 jd_core 升序，"
                     "不筛会把已过去的事件排在最前，页面显得过期）；剔除条数见 dropped_before_window。"
                     "历史事件仍为结构样例（日期是占位值，判定为占位的 slug 以 `todo-` 开头），"
                     "**默认不推送**，人工条目表落地后再替换；params_json 内为真算的回推值。"
                     "字段口径与推送命令见 data/README.md。"),
        },
        "ephemeris": {
            "requested": args.ephemeris,
            "resolved": compute_sky.resolve_ephemeris_path(args.ephemeris),
            "window": win_desc,
            "jd_lo": jd_lo, "jd_hi": jd_hi,
        },
        "delta_t": {
            "data_version": compute_sky.CONFIG.DATA_VERSION,
            "model": "ΔT = TT − UTC，Espenak & Meeus (2006) 多项式（compute_sky.delta_t_seconds）",
            "delta_t_sec_at_start_year": round(compute_sky.delta_t_seconds(int(args.start[:4])), 2),
        },
        "build": {"city": args.city, "tz_hours": args.tz, "jobs": args.jobs,
                  "allow_analytic_flag": bool(args.allow_analytic),
                  "analytic_fallback_effective": True,
                  "note": "不传 --allow-analytic 时沿用 compute_sky 默认（CONFIG.ANALYTIC_FALLBACK=True）"},
        "rest_whitelist_source": wl_src,
        "push": push_info,
    }
    manifest["range"]["days_computed"] = len(tasks)
    man_path = os.path.join(outdir, "manifest.json")
    _write_json(man_path, manifest)

    # —— 摘要（stdout）——
    print("构建完成（build_dataset v%s）" % SCRIPT_VERSION)
    if daily:
        print("  日记录：%s  %d 行（精算 %d / 降级 %d / 失败 %d）  用时 %.2f s"
              % (daily["path"], daily["ok"] + daily["degraded"], daily["ok"],
                 daily["degraded"], daily["failed"], daily["elapsed_sec"]))
    else:
        print("  日记录：本次未构建（--events-only）")
    if not args.daily_only:
        bt = "  ".join("%s=%d" % (k, v) for k, v in sorted(fut_stat["by_type"].items()))
        print("  未来事件：%s  %d 条（区间 %d—%d；发布窗口起 %s，窗口外剔除 %d 条）"
              % (fut_path, len(fut_rows), ev_y0, ev_y1,
                 fut_stat.get("publish_from") or "不限", fut_stat.get("dropped_before_window", 0)))
        print("    %s" % (bt or "空"))
        if fut_stat["slug_conflicts"]:
            print("    ⚠ slug 冲突 %d 件（已加序号，请核查生成器是否重叠）"
                  % len(fut_stat["slug_conflicts"]))
        print("  历史事件：%s  %d 条（占位 %d 条；其中 %d 条已核录可发布）"
              % (hist_path, len(hist_rows), hist_placeholders, hist_published))
        if not hist_rows:
            print("    人工条目表：%s" % manual_src)
        print("  可推送事件：%d 条（跳过占位 %d 条%s）"
              % (len(ev_rows), ev_skipped,
                 "；占位也推：--push-placeholders" if ev_skipped else ""))
    else:
        print("  事件集：本次未构建（--daily-only）")
    print("  元信息：%s" % man_path)
    if args.dry_run:
        print("  推送：dry-run（未发起任何请求）  计划日记录 %d 行 / 事件 %d 条"
              % (push_info["planned_daily_rows"], push_info["planned_event_rows"]))
    elif args.push:
        print("  推送：已执行  %s" % json.dumps(push_info, ensure_ascii=False))
    else:
        print("  推送：未启用")
    return 0 if not (args.push and push_info.get("error")) else 2


# ============================== 自检 ==============================
def selftest():
    """真算 3 天并校验 NDJSON 契约；全过 exit 0，任一失败 exit 1。"""
    ok, fails = 0, []

    def chk(name, cond, detail=""):
        nonlocal ok
        if cond:
            ok += 1
            print("  [PASS] %s %s" % (name, detail))
        else:
            fails.append("%s %s" % (name, detail))
            print("  [FAIL] %s %s" % (name, detail))

    wl, wl_src = load_rest_whitelist()
    print("  REST 白名单来源：%s" % wl_src)
    print("  daily 白名单：%s" % (list(wl["daily"]),))
    manual_entries, manual_src = load_manual_entries(MANUAL_ENTRIES_PATH)
    print("  人工条目表：%s" % manual_src)

    limit = 3
    start = date.today()
    CLIP_LOG.clear()          # 模块级累积，自检前清空，避免上次残留算到本次头上
    tmp = tempfile.mkdtemp(prefix="kcj_astro_selftest_")
    args = argparse.Namespace(
        start=start.isoformat(), end=(start + timedelta(days=limit - 1)).isoformat(),
        limit=limit, city="jieyang", tz=float(compute_sky.CONFIG.TZ_OFFSET_HOURS),
        outdir=tmp, ephemeris=None, allow_analytic=None, jobs=1,
        push=False, wp_site="", wp_user="", wp_app_password="", table="daily",
        events_only=False, daily_only=False, dry_run=True, selftest=True,
        # ★ 自检用**全年全类**事件（不是 --event-kinds meteor 这种裁剪）：
        #   契约判据要对「四类事件都在场」成立，裁剪过的样本会漏掉整类。
        # ★ 自检**关掉发布窗口**（publish_from 取 1900-01-01）：窗口按「今天」算，
        #   而今天是变量 —— 若把它带进自检，判据会随日期漂移（年终时甚至可能空集）。
        #   窗口本身另有独立的单元判据（见 _apply_publish_window 那几条）。
        events_range=None, event_kinds="", allow_unverified_events=False,
        allow_empty_events=False, push_placeholders=False,
        publish_from="1900-01-01", manual_entries=MANUAL_ENTRIES_PATH, events_batch=25)
    try:
        rc = run_build(args)
        chk("构建返回 0", rc == 0, "rc=%d" % rc)

        daily_path = os.path.join(tmp, "daily_%s.ndjson" % args.start[:4])
        chk("NDJSON 已生成", os.path.isfile(daily_path), daily_path)
        raw = ""
        if os.path.isfile(daily_path):
            with open(daily_path, encoding="utf-8") as f:
                raw = f.read()
        chk("行尾为 LF（无 CRLF）", "\r" not in raw)
        lines = [ln for ln in raw.split("\n") if ln.strip()]
        chk("行数 = %d" % limit, len(lines) == limit, "=%d" % len(lines))

        rows, bad = [], []
        for i, ln in enumerate(lines, 1):
            try:
                rows.append(json.loads(ln))
            except Exception as e:
                bad.append("第 %d 行: %s" % (i, e))
        chk("每行可被 json.loads", not bad and len(rows) == len(lines), "; ".join(bad))

        allowed = set(wl["daily"])
        extra, missing = set(), set()
        for r in rows:
            extra |= set(r) - allowed
            missing |= allowed - set(r)
        chk("键集 ⊆ REST daily 白名单", not extra, "多余键 %s" % sorted(extra))

        # ★ 白名单里的 `special_event_ids` **不要求出现**，这是有意为之：
        #   该列存的是「指向 wp_astro_events.event_id 的 ID 串」，而 compute_daily()
        #   给出的 special_event 只是标题/说明文本，并没有事件行 ID。
        #   为了让键齐备而编号，等于**伪造事件引用**——宁可留 NULL（列本身可空），
        #   等事件枚举模块上线、拿到真 event_id 后再回填。
        #   故此处只要求「compute_daily 确实产出的那 5 个键」齐备。
        required = set(wl["daily"]) - {"special_event_ids"}
        missing &= required
        chk("必填键齐备（%d 个；special_event_ids 故意留空）" % len(required), not missing,
            "缺 %s" % sorted(missing))

        jds = [r["jd"] for r in rows]
        chk("jd 单调递增", all(jds[i] < jds[i + 1] for i in range(len(jds) - 1)),
            "%s" % jds)

        mism = [(r["date_str"], compute_sky.jd_to_str(r["jd"], args.tz)[:10])
                for r in rows if compute_sky.jd_to_str(r["jd"], args.tz)[:10] != r["date_str"]]
        chk("date_str 与 jd 对应（jd_to_str）", not mism, "%s" % mism)

        days = [date.fromisoformat(r["date_str"]) for r in rows]
        chk("date_str 逐日连续",
            all((days[i + 1] - days[i]).days == 1 for i in range(len(days) - 1)))

        inner_ok, inner_bad = True, []
        for r in rows:
            d = json.loads(r["data_json"])
            same = (d["date_str"] == r["date_str"] and d["jd"] == r["jd"]
                    and d["method"] == r["method"] and d["data_version"] == r["data_version"])
            inner_ok &= same
            if not same:
                inner_bad.append(r["date_str"])
        chk("data_json 内层与外壳字段一致", inner_ok, "%s" % inner_bad)

        # ★ v1.2.1 新增（F22）：产出值必须装得进 COL_MAXLEN 声明的列宽。
        #   v1.2.0 的 `data_version` 既没进 COL_MAXLEN、又比列宽长 ⇒ 线上 MySQL 直接拒行，
        #   回执 written:0 / failed:1，而当时客户端只读 written ⇒ 完全看不出原因。
        #   本项把「列宽够不够」的判据前移到构建期，与 verify_package.py 的列类型对拍互为双闸。
        keys = set()
        for r in rows:
            keys |= set(r)
        # ★ 判据一（上游）：列宽**从未**需要裁剪 —— 即真值装得进声明列宽。
        #   放在 _clip 下游写「裁剪后不超宽」是恒真的（负控制实测确认过），故必须看 CLIP_LOG。
        chk("构建期 _clip 从未触发（列宽装得下真值）", not CLIP_LOG,
            "被裁剪：%s" % (CLIP_LOG[:5] or "无"))
        # ★ 判据二（覆盖）：daily 的文本列必须都在 COL_MAXLEN 里 —— 漏登记＝既不裁剪也不设防。
        #   这正是 v1.2.0 的真缺陷：data_version 没进 COL_MAXLEN（负控制②可复现报红）。
        uncovered = sorted(keys - set(COL_MAXLEN) - {"date_str", "jd", "data_json"})
        chk("daily 文本列均已纳入 COL_MAXLEN 覆盖", not uncovered, "未覆盖：%s" % uncovered)

        for name in ("events_future.json", "events_historical.json", "manifest.json"):
            p = os.path.join(tmp, name)
            try:
                with open(p, encoding="utf-8") as f:
                    obj = json.load(f)
                if name == "manifest.json":
                    good = isinstance(obj, dict) and "daily" in obj and "events" in obj
                else:
                    good = isinstance(obj, list) and all(set(r) <= set(wl["events"]) for r in obj)
            except Exception as e:
                good = False
                print("    %s 读取失败：%s" % (name, e))
            chk("%s 可解析且字段合规" % name, good)

        # ================= 事件集契约（v1.1.0 新增） =================
        # ★ 为什么这些判据不能省：事件集此前**恒为空**，`all(...)` 在空列表上恒真
        #   ⇒ 那几条「字段合规」的检查一直在假通过（空集假通过的典型脸）。
        #   现在事件真有了，判据才第一次有内容 —— 故同时补一条**非空**断言。
        fpath = os.path.join(tmp, "events_future.json")
        with open(fpath, encoding="utf-8") as f:
            fut = json.load(f)
        chk("未来事件**非空**（空数组＝枚举崩了，不是「真没有」）", len(fut) > 0,
            "%d 条" % len(fut))
        print("    未来事件 %d 条：%s" % (len(fut), "  ".join(
            "%s=%d" % (k, sum(1 for r in fut if r["event_type"] == k))
            for k in sorted({r["event_type"] for r in fut}))))

        allowed_ev = set(wl["events"])
        chk("事件键集 ⊆ REST events 白名单",
            all(set(r) <= allowed_ev for r in fut),
            "多余键 %s" % sorted({k for r in fut for k in r} - allowed_ev))
        chk("事件不发 event_id / post_id（PK 由服务端定）",
            all(not (set(r) & {"event_id", "post_id"}) for r in fut))
        req_ev = {"event_type", "jd_core", "event_time_bj", "title", "slug", "publish_status"}
        chk("事件必填键齐备且非 None",
            all(all(r.get(k) is not None for k in req_ev) for r in fut))
        # ★ slug 唯一是**推送幂等的硬前提**：REST 端按 slug 查存在→更新，
        #   同批里出现两个同 slug，第二条会覆盖第一条，**静默丢一条事件**。
        slugs = [r["slug"] for r in fut]
        chk("slug 全局唯一（否则 REST 会静默覆盖）",
            len(slugs) == len(set(slugs)), "重复 %d" % (len(slugs) - len(set(slugs))))
        jds = [r["jd_core"] for r in fut]
        chk("jd_core 升序", all(jds[i] <= jds[i + 1] for i in range(len(jds) - 1)))
        # ★ 时刻自洽检查。**必须用本文件自己的算式**，不能回手调 _jd_bj_str：
        #   同一个函数既生成又校验＝恒真。这里改走「北京时间字符串 → 减 8h 得 UTC
        #   → 本文件的 Meeus 式算 JD → 加 TT−UTC 得 TT JD」，与生成路径**无共用代码**。
        #   它拦得住两类真错：① 把 jd_core（TT）当 UT 直接格式化（差 69 秒）；
        #   ② 日期串错（月/日颠倒、跨年错）。容差 ±2 s：生成侧 strftime 截到秒。
        tdiff = []
        for r in fut:
            try:
                bj = datetime.strptime(r["event_time_bj"], "%Y-%m-%d %H:%M:%S")
            except Exception:
                tdiff.append((r["slug"], 9e9, "格式不符 YYYY-MM-DD HH:MM:SS"))
                continue
            jd_tt_indep = _jd_utc_from_dt(bj - timedelta(hours=8)) + _TT_MINUS_UTC_SEC / 86400.0
            dsec = (r["jd_core"] - jd_tt_indep) * 86400.0
            if abs(dsec) > 2.0:
                tdiff.append((r["slug"], dsec, r["event_time_bj"]))
        chk("event_time_bj ↔ jd_core 自洽（独立算式，|Δ| ≤ 2 s）", not tdiff,
            "不符 %d 条，例：%s" % (len(tdiff), tdiff[:2]))
        # ★ 跨字段不变量：slug 末尾的 YYYYMMDD 必须等于 event_time_bj 的北京日期。
        #   两者走不同的格式化路径（_bj_date 与 _jd_bj_str），改动其一即漂移。
        mism_slug = [(r["slug"], r["event_time_bj"]) for r in fut
                     if not _slug_date_matches(r["slug"], r["event_time_bj"])]
        chk("slug 内嵌日期 == event_time_bj 的北京日期", not mism_slug,
            "不符：%s" % mism_slug[:3])
        chk("未来事件 publish_status 全为 1（前台按 =1 过滤）",
            all(int(r["publish_status"]) == 1 for r in fut))

        # ── 发布窗口：单元判据（拿已载入的 64 行当样本，不再跑一遍枚举） ──
        chk("窗口不限时不剔除任何行（publish_from 空/1900 起）",
            _apply_publish_window(fut, "1900-01-01")[1] == 0
            and _apply_publish_window(fut, None)[1] == 0)
        cut = fut[len(fut) // 2]["event_time_bj"][:10]
        kept_w, dropped_w = _apply_publish_window(fut, cut)
        chk("窗口生效：cutoff=%s ⇒ 保留 %d + 剔除 %d = 总数 %d"
            % (cut, len(kept_w), dropped_w, len(fut)),
            len(kept_w) + dropped_w == len(fut) and 0 < len(kept_w) < len(fut))
        chk("窗口保留的行确无早于 cutoff 者（反向锁：不能漏删）",
            all(str(r["event_time_bj"])[:10] >= cut for r in kept_w))
        chk("负控制：cutoff 早于全部行 ⇒ 一条都不剔（否则判据两侧恒真）",
            _apply_publish_window(fut, "1900-01-01")[1] == 0)
        # ★ 明文纪律：WP 端一律 esc_html 直出，`**` 会示人两个星号。
        dirty = sorted({k for r in fut for k, v in r.items()
                        if isinstance(v, str) and "**" in v})
        chk("事件显示字段无 Markdown 粗体标记（**）", not dirty, "仍有：%s" % dirty)
        # ★ 类型必须是插件声明的规范值之一（现场解析 cpt.php，不写死副本）。
        canon, canon_src = load_event_types()
        print("    event_type 真值源：%s" % canon_src)
        if canon is None:
            chk("event_type 规范值判据", False,
                "未取到 cpt.php ⇒ 跳过即等于放过，故按失败计")
        else:
            bad_t = sorted({r["event_type"] for r in fut} - canon)
            chk("event_type 全落在插件声明的 %d 个规范值内" % len(canon), not bad_t,
                "越界：%s" % bad_t)
        chk("params_json 可反序列化",
            all(isinstance(json.loads(r["params_json"]), dict) for r in fut))
        chk("每条都有 source_ref（不编造：出处必标）",
            all(str(r.get("source_ref") or "").strip() for r in fut))

        # ── 空集守卫的两向验证（判据本体，不是文件的属性） ──
        raised = False
        try:
            _guard_events([], False, "自检探针")
        except EmptyEventSet:
            raised = True
        chk("空集守卫：0 条且未放行 ⇒ 必须抛错（不得静默写空文件）", raised)
        ok_pass = True
        try:
            _guard_events([], True, "自检探针")
        except EmptyEventSet:
            ok_pass = False
        chk("空集守卫正控制：显式 --allow-empty-events 时放行（否则判据恒真）", ok_pass)

        # ── 空集守卫的**端到端**验证：真让枚举返回 0 条，必须抛错且不留文件 ──
        #   ★ 这一条与上面两条不同：上面验的是守卫函数本身，这里验的是
        #     「build_future 里守卫确实装在**写文件之前**」—— 装错位置就会留下
        #     一个空数组文件，而那是谁也不会报错的静默失败。
        #   ★ 打桩的是 `ea.build_events`（正常 import 的模块对象），不是本文件自身
        #     的全局量，故不涉及「直跑时模块名是 __main__、改副本无效」那个坑。
        _orig_be = ea.build_events
        sub = os.path.join(tmp, "empty_probe")
        os.makedirs(sub, exist_ok=True)
        try:
            ea.build_events = lambda *a, **k: ([], {"counts": {}, "total": 0,
                                                    "slug_conflicts": [], "by_type": {},
                                                    "boundary_dropped": 0})
            raised2 = False
            try:
                build_future(sub, None, 2026, 2026, verbose=False)
            except EmptyEventSet:
                raised2 = True
            wrote = os.path.isfile(os.path.join(sub, "events_future.json"))
        finally:
            ea.build_events = _orig_be
        chk("端到端：枚举 0 条 ⇒ 抛错且**不落文件**（守卫装在写盘之前）",
            raised2 and not wrote, "raised=%s wrote=%s" % (raised2, wrote))

        # ── 占位件过滤（推送面） ──
        hpath = os.path.join(tmp, "events_historical.json")
        with open(hpath, encoding="utf-8") as f:
            hist = json.load(f)
        chk("占位件（slug 以 todo- 开头）publish_status 全为 0（草稿，不上前台）",
            all(int(r["publish_status"]) == 0 for r in hist if r["slug"].startswith("todo-")))
        chk("历史行数 == 人工条目表条目数（不多不少）", len(hist) == len(manual_entries),
            "行 %d vs 条目 %d" % (len(hist), len(manual_entries)))
        # ★ 发布规则必须**双向**成立：verified=false 一条都不能上（上面已锁），
        #   verified=true 且显式 publish_status=1 的必须真上 —— 只锁单向的话，
        #   「一律强制草稿」这个错也会通过。
        by_slug = {e["slug"]: e for e in manual_entries}
        rule_bad = []
        for r in hist:
            e = by_slug.get(r["slug"])
            if e is None:
                rule_bad.append((r["slug"], "表中无此条目"))
                continue
            want = 1 if (bool(e.get("verified")) and int(e.get("publish_status", 0)) == 1) else 0
            if int(r["publish_status"]) != want:
                rule_bad.append((r["slug"], "得 %s 应为 %s" % (r["publish_status"], want)))
        chk("发布规则双向：verified ∧ publish_status=1 ⇔ 行 publish_status=1", not rule_bad,
            "%s" % rule_bad[:3])

        # ── 人工条目表：校验器会真的拦人（三向负控制） ──
        #   ★ 为什么必须逐向测：一条「格式错必须硬停」的判据，只在**真的报错**时才算数；
        #     如果校验器把错误吃了、只当没这条，判据就成了摆设（本项目的经典坑）。
        bad_cases = (
            ("缺 slug", {"kind": "historical", "era_year": "1900AD", "month": 1, "day": 1,
                         "calendar_note": "x", "source_text": "y", "source_ref": "z"}),
            ("kind 非法", {"kind": "guess", "slug": "a-b-19000101"}),
            ("historical 缺 source_ref", {"kind": "historical", "slug": "a-b-19000101",
                                          "era_year": "1900AD", "month": 1, "day": 1,
                                          "calendar_note": "x", "source_text": "y"}),
            ("catalog 缺 jd_core", {"kind": "catalog", "slug": "a-b-19000101",
                                    "title": "t", "source_ref": "r",
                                    "event_type": "traditional"}),
            ("slug 重复", "DUP"),
        )
        probe_dir = os.path.join(tmp, "manual_probe")
        os.makedirs(probe_dir, exist_ok=True)
        for label, ent in bad_cases:
            if ent == "DUP":
                ents = [{"kind": "catalog", "slug": "same-slug", "title": "t",
                         "source_ref": "r", "event_type": "traditional", "jd_core": 2451545.0},
                        {"kind": "catalog", "slug": "same-slug", "title": "t2",
                         "source_ref": "r", "event_type": "traditional", "jd_core": 2451546.0}]
            else:
                ents = [ent]
            p = os.path.join(probe_dir, "p.json")
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                json.dump({"schema": 1, "entries": ents}, f, ensure_ascii=False)
            caught = False
            try:
                load_manual_entries(p)
            except ManualEntryError:
                caught = True
            chk("负控制：人工条目表「%s」必须被拦住" % label, caught)
        # 正控制：合法的两条（本仓真表）必须放行 —— 否则上面的负控制可能是「一律报错」
        ok_manual = True
        try:
            load_manual_entries(MANUAL_ENTRIES_PATH)
        except ManualEntryError as e:
            ok_manual = False
            print("    真表读取失败：%s" % e)
        chk("正控制：仓内真表必须通过校验（否则判据是「一律报错」）", ok_manual)
        chk("占位件被 pushable_events 剔除（默认不推脏数据到线上）",
            len(pushable_events(hist, False)) == 0 and
            len(pushable_events(hist, True)) == len(hist),
            "默认放行 %d 条 / 显式全推 %d 条"
            % (len(pushable_events(hist, False)), len(pushable_events(hist, True))))
        # 非占位件必须放行 —— 否则「过滤」变成了「全滤掉」也会通过（恒真方向相反）
        chk("非占位件不受过滤影响（publish_status=1 的真事件仍要推）",
            len(pushable_events(fut[:3], False)) == 3)

        # ── manifest 如实记录（不得再写「未来事件为空数组」这类过期话） ──
        with open(os.path.join(tmp, "manifest.json"), encoding="utf-8") as f:
            man = json.load(f)
        evs = man.get("events", {})
        chk("manifest.events 计数与文件一致",
            evs.get("future_count") == len(fut)
            and evs.get("historical_count") == len(hist),
            "manifest=%s/%s 文件=%s/%s" % (evs.get("future_count"),
                                          evs.get("historical_count"),
                                          len(fut), len(hist)))
        chk("manifest 事件状态不再是旧口径（structural_samples…）",
            evs.get("status") == "enumerated", "status=%s" % evs.get("status"))
        chk("manifest 记录了枚举器与逐类计数",
            bool(evs.get("enumerator")) and bool(evs.get("future_by_type")))
        chk("manifest 如实记录发布窗口（自检为 1900-01-01，剔除 0 条）",
            evs.get("publish_from") == "1900-01-01" and evs.get("dropped_before_window") == 0,
            "publish_from=%s dropped=%s" % (evs.get("publish_from"),
                                            evs.get("dropped_before_window")))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("  —— 自检合计：通过 %d 项，失败 %d 项" % (ok, len(fails)))
    return 0 if not fails else 1


# ============================== CLI ==============================
def parse_args(argv=None):
    today = date.today()
    ap = argparse.ArgumentParser(
        description="天象预报批量数据集构建：调用 compute_sky.py 算日记录与事件集，"
                    "产出 NDJSON/JSON 并可经 REST 入库。仅天文数值与观测条件描述。",
        epilog="示例：--start 2026-01-01 --end 2026-12-31 --jobs 4；"
               "只算事件：--events-only --events-range 2026 2027；自检：--selftest")
    ap.add_argument("--start", default=today.isoformat(),
                    help="起始日期 YYYY-MM-DD（含）；默认今天 %s" % today.isoformat())
    ap.add_argument("--end", default=(today + timedelta(days=365)).isoformat(),
                    help="结束日期 YYYY-MM-DD（含）；默认起始日 +365 天")
    ap.add_argument("--city", default="beijing",
                    help="预置城市键（见 compute_sky.CONFIG.CITIES），默认 beijing")
    ap.add_argument("--tz", type=float, default=float(compute_sky.CONFIG.TZ_OFFSET_HOURS),
                    help="时区偏移小时数，默认 %d（北京时间）" % compute_sky.CONFIG.TZ_OFFSET_HOURS)
    ap.add_argument("--outdir", default=DEFAULT_OUTDIR, help="输出目录，默认 <仓库根>/data")
    ap.add_argument("--ephemeris", help="星历路径或档名（默认自动发现 de421.bsp）")
    ap.add_argument("--allow-analytic", action="store_true", default=None,
                    help="星历覆盖外显式允许降级到 Meeus 解析式（不给出时沿用 compute_sky 默认值 True）")
    ap.add_argument("--jobs", type=int, default=4, help="并行进程数，默认 4")
    ap.add_argument("--push", action="store_true", help="经 REST 端点推送入库")
    ap.add_argument("--wp-site", default="", help="WordPress 站点地址，如 https://example.com")
    ap.add_argument("--wp-user", default="", help="WordPress 用户名")
    ap.add_argument("--wp-app-password", default="", help="WordPress 应用程序密码")
    ap.add_argument("--table", default="daily", choices=["daily", "events", "relations"],
                    help="日记录写入的表（默认 daily；事件固定写 events）")
    ap.add_argument("--events-only", action="store_true", help="只构建事件集，不算日记录")
    ap.add_argument("--daily-only", action="store_true", help="只构建日记录，不算事件集")
    ap.add_argument("--events-range", nargs=2, type=int, metavar=("Y0", "Y1"),
                    help="事件枚举的年份区间（含）；默认取 --start/--end 的年份。"
                         "★ 与日记录区间分开：事件枚举的最小有意义单位是一年")
    ap.add_argument("--event-kinds", default="",
                    help="只生成指定类事件（逗号分隔）：" + ",".join(ea.GENERATORS)
                         + "；默认全部")
    ap.add_argument("--manual-entries", default=MANUAL_ENTRIES_PATH, metavar="PATH",
                    help="人工条目表 JSON（默认 data/events_manual.json）；"
                         "文件不存在＝空表，格式错＝硬停")
    ap.add_argument("--events-batch", type=int, default=25,
                    help="事件推送每批行数，默认 25（服务端每行会建一篇 CPT 文章，"
                         "批太大易撞请求时限）")
    ap.add_argument("--publish-from", default=date.today().isoformat(),
                    metavar="YYYY-MM-DD",
                    help="发布窗口下界（北京日期）：早于此日的行**不落地**，默认今天。"
                         "要全量收录请给 1900-01-01")
    ap.add_argument("--allow-unverified-events", action="store_true",
                    help="放行日食「食甚 vs 自算朔」时差 > 3h 的条目（默认不放行）")
    ap.add_argument("--allow-empty-events", action="store_true",
                    help="显式允许事件集为空（默认：0 条即报错退出，不写空文件）")
    ap.add_argument("--push-placeholders", action="store_true",
                    help="连历史占位样例（slug 以 todo- 开头）一并推送；默认剔除")
    ap.add_argument("--dry-run", action="store_true", help="只统计不推送")
    ap.add_argument("--limit", type=int, default=None, help="只算前 N 天（快速自测用）")
    ap.add_argument("--selftest", action="store_true", help="真算 3 天并校验 NDJSON 契约后退出")
    args = ap.parse_args(argv)
    if args.events_only and args.daily_only:
        ap.error("--events-only 与 --daily-only 不能同时使用")
    return args


def main(argv=None):
    args = parse_args(argv)
    if args.selftest:
        return selftest()
    return run_build(args)


if __name__ == "__main__":
    sys.exit(main())
