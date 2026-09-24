#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_site.py —— 观测地维度数据集构建（v2.0.0 新增）

角色
────
`build_dataset.py` 负责**日记录**（wp_astro_daily）与**事件**（wp_astro_events）；
本脚本负责**观测地维度**（wp_astro_daily_site）：日出/日落/昼长/三种晨昏/月出/月落。
三张表互不重叠，合起来支撑「今日天象（观测地可选）／未来天象预告／历史今日天象」。

为什么不把它并进 build_dataset.py
────────────────────────────────
① 两者的**滚动窗口口径不同**：日记录按承诺窗口（1900—2050）全量，观测地维度按
   **滚动窗**增量刷新即可 —— 页面只查「今天」。
   混在一个脚本里会让「--start/--end」有两套默认值语义。
② 观测地维度是 **N 城 × M 天** 的二维展开，规模比日记录大一个量级，
   单独跑便于控制进程数与分批推送。

★ 滚动窗口径（v2.3.0 改定；改前为 −370 / +400 天）
──────────────────────────────────────────────────
**滚动窗不是「覆盖需求」，是「免维护预算」。** 页面侧 / 读取面只有一处：
`shortcodes.php` 的 `kcj_astro_load_places($date)`，而 $date 恒为 `current_time('Y-m-d')`
＝**今天**（`[astro_hub]` 的今日栏调 `[astro_today]` **不带 date**；历史栏走 `astro_history_today`
读的是 **events 表**，未来栏走 report，都不是本表）。既然只查今天，那么：
  · **往后**：预计算出未来的每天 ⇒ 只要窗口还有剩，**不重建也能一直正确**
    —— 这才是「+N 天」的真实用途。N ＝ 免维护天数。
  · **往前**：完全无用（今天不是昨天），只留几天余量吸收「构建日 ≠ 部署日」。
改前 370/400 是照抄 `daily` 的窗（那个表要按任意日期取数、供 SEO 定位），
对 38 城时共 29,298 行尚可；**观测地扩到 340 个锚点后，同窗会变成 262,140 行**（×8.95），
与本表实际用途严重不成比例，故按比例收紧为 **−7 / +120**。
  ⇒ 行数 29,298 → **43,520**（+48%），免维护窗 **4 个月**。
  ⚠ 若将来要延长免维护窗，**先修 `run_tasks` 的并发天花板**（实测：1 进程 0.129 s/行，
    4 进程 14 s、8 进程 11 s、16 进程 11 s ⇒ 硬停在约 **31 行/秒**，父进程侧串行点）
    —— 直接加大窗口会等来 1—3 小时的跑批。

数据集规模（实测基准，本机 2026-09-23）
──────────────────────────────────────
· compute_site_daily 单次 ≈ **0.168 s**（只算升落 + 三档晨昏，不建整条日记录）
· 并发天花板 ≈ 31 行/秒 ⇒ 43,520 行 ≈ **23 分钟**（与 jobs=8/16/20 无关）
· NDJSON 每行约 200 字节 ⇒ 43,520 行约 8—9 MB

怎么跑
──────
    # 自测（真算 + 契约校验，不写盘）
    python build_site.py --selftest

    # 滚动窗全量，全部锚点，8 进程
    python build_site.py --jobs 8

    # 只算 3 城 10 天（快速看产物长什么样）
    python build_site.py --cities jieyang,beijing,guangzhou --start 2026-09-23 --end 2026-10-02

    # 推送入库（需 WP 应用程序密码）
    python build_site.py --push --wp-user <用户名> --wp-app-password <密码>
"""

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(_HERE)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import compute_sky  # noqa: E402

SCRIPT_VERSION = "1.0.0"
DEFAULT_OUTDIR = os.path.join(REPO_ROOT, "data")
TABLE = "daily_site"

# 与插件端 rest-import.php 的 kcj_astro_rest_columns('daily_site') 必须一致。
# 客户端侧只做「送出去之前先自查」，真正的白名单在服务端。
SITE_REST_WHITELIST = (
    "date_str", "city", "city_cn", "lat", "lon", "elev_m", "tz",
    "sunrise_bj", "sunset_bj", "day_length_min",
    "tw_civil_begin", "tw_civil_end",
    "tw_nautical_begin", "tw_nautical_end",
    "tw_astro_begin", "tw_astro_end",
    "moonrise_bj", "moonset_bj",
    "method", "data_version",
)

# 列宽上限（与 sql/install_tables.sql 的表 4 逐列一致）。
# verify_package.py 有一项做「COL_MAXLEN ↔ SQL 列宽」对拍，本表是它的第二处来源。
# ★★ v2.2.6 续（2026-09-23 · **实测**）：上表的数字单位是「**字节**」，不是「字符」。
#   依据：v2.2.6 信标 `cols` 段直采到线上列定义 —— **所有字符串列的字符集都是
#   `latin1_swedish_ci`**；而 WordPress 的 `strip_invalid_text()`（wp-includes/class-wpdb.php）
#   对「latin1 字符集」**一律按字节**判长度（`strlen`/`substr`，不是 `mb_strlen`）。
#   ⇒ **中文每字 3 字节，一个 varchar(32) 的中文列实际只装得下 10 个字**。
#   F27 就是在这里翻的车：`time_uncertainty` 真值 60 字符 / **159 字节**，
#   而当时按**字符**判「60 ≤ 64 合规」，上线后被数据库按**字节**全数拒收（4,672 行）。
#   ⇒ 本表的语义自此统一为字节，**裁剪与判据都必须按字节**。

COL_MAXLEN = {
    "date_str": 10,
    "city": 32,
    "city_cn": 32,
    "tz": 16,
    "sunrise_bj": 8,
    "sunset_bj": 8,
    "tw_civil_begin": 8,
    "tw_civil_end": 8,
    "tw_nautical_begin": 8,
    "tw_nautical_end": 8,
    "tw_astro_begin": 8,
    "tw_astro_end": 8,
    "moonrise_bj": 8,
    "moonset_bj": 8,
    "method": 32,
    "data_version": 64,
}

# 数值列（服务端会强制转型；这里列出便于自测断言类型）
NUMERIC_COLS = ("lat", "lon", "elev_m", "day_length_min")

# ★ v2.3.0：滚动窗按比例收紧（改前 370 / 400）。理由见文件头「滚动窗口径」一节。
#   一句话：本表只被「今天」查询，往前无用、往后＝免维护天数；观测地由 38 扩到 340 个锚点后，
#   维持旧窗会把数据面放大 8.95 倍（29,298 → 262,140 行）而**一个查询都用不到**。
ROLLING_BEHIND_DAYS = 7      # 吸收「构建日 ≠ 部署日」的几天余量
ROLLING_AHEAD_DAYS = 120     # 免维护窗：4 个月不重建也一直能答「今天」

# 自测用城市：揭阳（默认）+ 北京（同经度、差纬度）+ 乌鲁木齐（差 28.75° 经度）
SELFTEST_CITIES = ("jieyang", "beijing", "guangzhou", "wulumqi")


# ============================== 单行装配 ==============================
def site_row(y, m, d, city, tz_hours, eph=None):
    """compute_site_daily → REST 白名单行（丢弃 note 等非列键）。"""
    rec = compute_sky.compute_site_daily(y, m, d, city=city, tz_hours=tz_hours,
                                         ephemeris=eph)
    row = {}
    for k in SITE_REST_WHITELIST:
        if k in rec:
            row[k] = rec[k]
    return row


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


def clip(value, key):
    """按列宽裁剪（**超长即报错，不静默截断** —— 静默截断＝把错数据写进库）。

    ★ v2.2.6 续：列宽单位是**字节**（线上列 latin1 ⇒ WP 按字节判），
      故这里的比较与报数都用 `_utf8_len`，不用 `len`。
    """
    if value is None:
        return None
    s = str(value)
    n = COL_MAXLEN.get(key)
    if n is not None and _utf8_len(s) > n:
        raise ValueError("字段 %s 超列宽：%d 字节 > %d 字节（%d 字符；值：%r）"
                         % (key, _utf8_len(s), n, len(s), s))
    return s


def assert_contract(row):
    """契约断言（自测与 --selftest 共用）。返回问题清单（空＝通过）。"""
    bad = []
    for k in SITE_REST_WHITELIST:
        if k not in row:
            bad.append("缺列 %s" % k)
    for k in ROW_REQUIRED_NOT_NULL:
        if row.get(k) in (None, ""):
            bad.append("必填列为空 %s" % k)
    for k in NUMERIC_COLS:
        v = row.get(k)
        if v is not None and not isinstance(v, (int, float)):
            bad.append("数值列 %s 不是数：%r" % (k, v))
    for k, v in row.items():
        # ★ v2.2.6 续：按**字节**判（线上列 latin1 ⇒ WP 按字节判长度）
        if isinstance(v, str) and _utf8_len(v) > COL_MAXLEN.get(k, 10 ** 9):
            bad.append("列 %s 超宽 %d 字节（%d 字符）" % (k, _utf8_len(v), len(v)))
    return bad


ROW_REQUIRED_NOT_NULL = ("date_str", "city", "city_cn", "lat", "lon", "elev_m", "tz",
                         "method", "data_version")


# ============================== 并行 ==============================
def _worker(task):
    """子进程任务：(y,m,d,city,tz,eph) → 行 dict 或错误串。"""
    y, m, d, city, tz, eph = task
    try:
        return ("ok", site_row(y, m, d, city, tz, eph))
    except Exception as exc:  # noqa: BLE001
        return ("err", "%04d-%02d-%02d %s: %r" % (y, m, d, city, exc))


def run_tasks(tasks, jobs, verbose=True):
    """并行跑任务。jobs<=1 走串行（便于调试与稳定的报错顺序）。"""
    out, errs = [], []
    t0 = time.time()
    total = len(tasks)
    if jobs <= 1:
        for i, t in enumerate(tasks):
            st, v = _worker(t)
            (out if st == "ok" else errs).append(v)
            if verbose and (i + 1) % 200 == 0:
                el = time.time() - t0
                print("  %d/%d  %.0f s  预计剩余 %.0f s" % (i + 1, total, el,
                      el / (i + 1) * (total - i - 1)), file=sys.stderr)
    else:
        import multiprocessing as mp
        with mp.Pool(jobs) as pool:
            done = 0
            for st, v in pool.imap_unordered(_worker, tasks, chunksize=8):
                done += 1
                (out if st == "ok" else errs).append(v)
                if verbose and done % 500 == 0:
                    el = time.time() - t0
                    print("  %d/%d  %.0f s  预计剩余 %.0f s" % (done, total, el,
                          el / done * (total - done)), file=sys.stderr)
    return out, errs


def daterange(a, b):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


# ============================== 写盘 ==============================
def write_ndjson(rows, path):
    """按 (date_str, city) 排序后写盘 —— 排序只为 diff 友好，与幂等无关。"""
    rows = sorted(rows, key=lambda r: (r["date_str"], r["city"]))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    return path, len(rows)


def sql_escape(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("\\", "\\\\").replace("'", "''") + "'"


def write_sql(rows, path, table="wp_astro_daily_site"):
    """生成 `INSERT ... ON DUPLICATE KEY UPDATE` 版 SQL（供 DBA 手工导入兜底）。

    ★ 为什么还要 SQL：REST 需要应用程序密码；没有凭据时，站点后台的
      phpMyAdmin（若有）或 DBA 手工导入是唯一路径。两条路都留着，但**数据同源**。
    """
    rows = sorted(rows, key=lambda r: (r["date_str"], r["city"]))
    cols = list(SITE_REST_WHITELIST)
    upd = ", ".join("%s=VALUES(%s)" % (c, c) for c in cols if c not in ("date_str", "city"))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("-- build_site.py 生成（v%s，%s）\n" % (SCRIPT_VERSION,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        f.write("-- 幂等：ON DUPLICATE KEY UPDATE，键为 (date_str, city)\n")
        f.write("SET NAMES utf8mb4;\n")
        # 每 200 行一条 INSERT，避免单语句过长被网关截断
        for i in range(0, len(rows), 200):
            chunk = rows[i:i + 200]
            f.write("INSERT INTO `%s` (%s) VALUES\n" % (table,
                    ", ".join("`%s`" % c for c in cols)))
            vals = []
            for r in chunk:
                vals.append("(" + ", ".join(sql_escape(r.get(c)) for c in cols) + ")")
            f.write(",\n".join(vals))
            f.write("\nON DUPLICATE KEY UPDATE %s;\n" % upd)
    return path, len(rows)


# ============================== 自测 ==============================
def selftest(verbose=True):
    """真算 3 天 × 3 城（含默认城），逐条校验契约，并**负控制**两条。"""
    problems = []
    ok = 0

    def chk(name, cond, detail=""):
        nonlocal ok
        if cond:
            ok += 1
            if verbose:
                print("  [PASS] %s %s" % (name, detail))
        else:
            problems.append("%s %s" % (name, detail))
            print("  [FAIL] %s %s" % (name, detail))

    print("[build_site] selftest：真算 3 天 × %d 城" % len(SELFTEST_CITIES))
    today = date.today()
    cities = list(SELFTEST_CITIES)
    tasks = [(d.year, d.month, d.day, c, 8.0, None)
             for d in daterange(today, today + timedelta(days=2)) for c in cities]
    rows = []
    for t in tasks:
        st, v = _worker(t)
        if st != "ok":
            problems.append("计算失败：%s" % v)
        else:
            rows.append(v)
    chk("3 天 × %d 城共 %d 行全部算出" % (len(cities), len(cities) * 3),
        len(rows) == len(cities) * 3, "= %d 行" % len(rows))

    allbad = []
    for r in rows:
        allbad += ["%s/%s %s" % (r.get("date_str"), r.get("city"), b)
                   for b in assert_contract(r)]
    chk("契约校验（列齐全/类型/列宽）", not allbad,
        "; ".join(allbad[:5]) or "%d 行全通过" % len(rows))

    # 值本身要像话：升落形如 HH:MM，昼长在 0—1440 之间
    fmt_bad = []
    rng_bad = []
    for r in rows:
        for k in ("sunrise_bj", "sunset_bj", "moonrise_bj", "moonset_bj",
                  "tw_civil_begin", "tw_civil_end", "tw_nautical_begin",
                  "tw_nautical_end", "tw_astro_begin", "tw_astro_end"):
            v = r.get(k)
            if v is not None and not (len(v) == 5 and v[2] == ":" and v[:2].isdigit()
                                      and v[3:].isdigit()):
                fmt_bad.append("%s=%r" % (k, v))
        dl = r.get("day_length_min")
        if dl is not None and not (0 < dl <= 1440):
            rng_bad.append("%s/%s day_length_min=%r" % (r["date_str"], r["city"], dl))
    chk("时刻格式为 HH:MM", not fmt_bad, "; ".join(fmt_bad[:5]) or "全部合规")
    chk("昼长在 0—1440 分钟", not rng_bad, "; ".join(rng_bad[:5]) or "全部合规")

    # 城市间要有差异（否则说明 city 参数根本没接上 —— 这类「看着有、其实没用」最危险）
    # ★ 用乌鲁木齐对照而不用北京：北京(116.40E)与揭阳(116.37E)**经度几乎相同**，
    #   钟表时下的日出只差纬度那几分钟，做负控制太弱；乌鲁木齐(87.62E)差 28.75°
    #   ≈ 115 分钟时差，city 没接线时此项必红。
    jy = [r for r in rows if r["city"] == "jieyang"]
    wl = [r for r in rows if r["city"] == "wulumqi"]
    diffs = []
    for a, b in zip(jy, wl):
        if a["sunrise_bj"] and b["sunrise_bj"]:
            ha, ma = map(int, a["sunrise_bj"].split(":"))
            hb, mb = map(int, b["sunrise_bj"].split(":"))
            diffs.append(abs((hb * 60 + mb) - (ha * 60 + ma)))
    chk("★ 不同观测地给出不同的升落（负控制：city 未接线时此项必红）",
        bool(diffs) and min(diffs) >= 60,
        "揭阳/乌鲁木齐日出时差 " + (", ".join("%d 分" % d for d in diffs) or "无数据")
        + "（应 ≥60 分）")
    if verbose:
        for r in rows[:6]:
            print("      %s %-8s 日出 %s 日落 %s 昼长 %s 分"
                  % (r["date_str"], r["city"], r["sunrise_bj"], r["sunset_bj"],
                     r["day_length_min"]))

    # 负控制①：未知城市必须抛错，不得静默回落默认城
    try:
        site_row(today.year, today.month, today.day, "no-such-city", 8.0)
        chk("★ 负控制①：未知观测地必须报错（不许静默回落揭阳）", False, "竟然算出了结果")
    except Exception as exc:
        chk("★ 负控制①：未知观测地必须报错（不许静默回落揭阳）", True, repr(exc)[:60])

    # 负控制②：超列宽必须报错，不得静默截断
    try:
        clip("x" * 200, "sunrise_bj")
        chk("★ 负控制②：超列宽必须报错（不许静默截断）", False, "竟然通过了")
    except ValueError:
        chk("★ 负控制②：超列宽必须报错（不许静默截断）", True, "已抛 ValueError")

    # 写盘往返（临时目录）
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        p1, n1 = write_ndjson(rows, os.path.join(tmp, "s.ndjson"))
        back = [json.loads(x) for x in open(p1, encoding="utf-8") if x.strip()]
        chk("NDJSON 写读往返行数一致", len(back) == n1 == len(rows), "= %d" % len(back))
        p2, n2 = write_sql(rows, os.path.join(tmp, "s.sql"))
        txt = open(p2, encoding="utf-8").read()
        chk("SQL 含 ON DUPLICATE KEY UPDATE（幂等）", "ON DUPLICATE KEY UPDATE" in txt)
        chk("SQL 语句数与分块一致", n2 == len(rows), "= %d 行" % n2)

    print("[build_site] selftest：通过 %d 项，失败 %d 项" % (ok, len(problems)))
    return 0 if not problems else 1


# ============================== 主流程 ==============================
def main(argv=None):
    ap = argparse.ArgumentParser(description="构建观测地维度数据集（wp_astro_daily_site）")
    today = date.today()
    ap.add_argument("--start", default=(today - timedelta(days=ROLLING_BEHIND_DAYS)).isoformat(),
                    help="起始日期（默认：今天 −%d 天，滚动窗）" % ROLLING_BEHIND_DAYS)
    ap.add_argument("--end", default=(today + timedelta(days=ROLLING_AHEAD_DAYS)).isoformat(),
                    help="结束日期（默认：今天 +%d 天，滚动窗）" % ROLLING_AHEAD_DAYS)
    ap.add_argument("--cities", default="all",
                    help="逗号分隔的城市键，或 all（默认）；键见 compute_sky.CONFIG.CITIES")
    ap.add_argument("--tz", type=float, default=float(compute_sky.CONFIG.TZ_OFFSET_HOURS))
    ap.add_argument("--outdir", default=DEFAULT_OUTDIR)
    ap.add_argument("--ephemeris", help="星历路径或档名（默认自动发现 de421.bsp）")
    ap.add_argument("--jobs", type=int, default=4, help="并行进程数，默认 4")
    ap.add_argument("--format", choices=["ndjson", "sql", "both"], default="both")
    ap.add_argument("--limit", type=int, default=None, help="只算前 N 天（快速自测用）")
    ap.add_argument("--push", action="store_true", help="经 REST 端点推送入库")
    ap.add_argument("--wp-site", default="", help="WordPress 站点地址，如 https://example.com")
    ap.add_argument("--wp-user", default="")
    ap.add_argument("--wp-app-password", default="")
    ap.add_argument("--dry-run", action="store_true", help="只统计，不推不写")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    # 城市解析（认不出即报错，不静默回落）
    if args.cities.strip().lower() == "all":
        cities = compute_sky.city_keys()
    else:
        cities = []
        for raw in args.cities.split(","):
            k = compute_sky.resolve_city_key(raw)
            if k is None:
                print("[build_site] 未知城市：%r（可用：%s）"
                      % (raw, ", ".join(compute_sky.city_keys())), file=sys.stderr)
                return 2
            if k not in cities:
                cities.append(k)

    d0 = date.fromisoformat(args.start)
    d1 = date.fromisoformat(args.end)
    if d1 < d0:
        print("[build_site] 结束日期早于起始日期", file=sys.stderr)
        return 2
    days = list(daterange(d0, d1))
    if args.limit:
        days = days[:args.limit]

    tasks = [(d.year, d.month, d.day, c, args.tz, args.ephemeris)
             for d in days for c in cities]
    print("[build_site] v%s  区间 %s ~ %s（%d 天）× %d 城 = **%d** 个观测地日"
          % (SCRIPT_VERSION, d0, d1, len(days), len(cities), len(tasks)))
    if args.dry_run:
        est = len(tasks) * 0.168
        print("[build_site] dry-run：未计算。单进程约 %.0f 分钟，%d 进程约 %.0f 分钟"
              % (est / 60.0, args.jobs, est / 60.0 / max(1, args.jobs)))
        return 0

    t0 = time.time()
    rows, errs = run_tasks(tasks, args.jobs)
    el = time.time() - t0
    print("[build_site] 计算完成：%d 行成功 / %d 失败，用时 %.0f s" % (len(rows), len(errs), el))
    if errs:
        for e in errs[:10]:
            print("   ⚠ %s" % e, file=sys.stderr)
        if len(errs) > 10:
            print("   … 另有 %d 条" % (len(errs) - 10), file=sys.stderr)

    # 空集守卫：一行都没算出来 ⇒ 报错退出，不许「成功地什么都没做」
    if not rows:
        print("[build_site] 致命：0 行产物（空集守卫）。请检查区间与城市参数。", file=sys.stderr)
        return 3

    bad = []
    for r in rows:
        bad += ["%s/%s %s" % (r.get("date_str"), r.get("city"), b)
                for b in assert_contract(r)]
    if bad:
        print("[build_site] 致命：%d 处契约违规，未写盘未推送。示例：%s"
              % (len(bad), "; ".join(bad[:5])), file=sys.stderr)
        return 3

    os.makedirs(args.outdir, exist_ok=True)
    stamp = "%s_%s" % (args.start.replace("-", ""), args.end.replace("-", ""))
    written = {}
    if args.format in ("ndjson", "both"):
        p, n = write_ndjson(rows, os.path.join(args.outdir, "site_daily_%s.ndjson" % stamp))
        written["ndjson"] = (p, n)
        print("[build_site] 写出 %s（%d 行）" % (os.path.relpath(p, REPO_ROOT), n))
    if args.format in ("sql", "both"):
        p, n = write_sql(rows, os.path.join(args.outdir, "site_daily_%s.sql" % stamp))
        written["sql"] = (p, n)
        print("[build_site] 写出 %s（%d 行）" % (os.path.relpath(p, REPO_ROOT), n))

    if args.push:
        if not (args.wp_user and args.wp_app_password):
            print("[build_site] --push 需要 --wp-user 与 --wp-app-password", file=sys.stderr)
            return 2
        try:
            res = compute_sky.push_rest(rows, TABLE, args.wp_site,
                                        args.wp_user, args.wp_app_password)
            print("[build_site] 推送：%s" % json.dumps(res, ensure_ascii=False))
            compute_sky.flush_remote_cache(args.wp_site, args.wp_user, args.wp_app_password)
        except Exception as exc:  # noqa: BLE001
            print("[build_site] 推送失败：%s" % exc, file=sys.stderr)
            return 2
    else:
        print("[build_site] 未推送（加 --push 与凭据）。数据已落盘，可经 REST 或 SQL 导入。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
