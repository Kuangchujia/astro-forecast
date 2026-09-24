#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""history_events.py —— 历史天象数据集（v2.0.0 新增 · v2.1.0 扩族）

角色
────
为「历史上今日天象」（`[astro_history_today]`）准备数据：把**可自算**的天象族
用星历回算到 1900 年，逐条落成 `wp_astro_events` 行（`publish_status = 1`）。

收哪几族、为什么（这是本文件最重要的一段）
────────────────────────────────────────
| 族 | 收不收 | 理由 |
|---|---|---|
| `lunar_eclipse` 月食 | ✅ | 本模块有完整求根引擎（接触时刻 + 食分 + 全食时长），且已与 NASA GSFC 目录逐条对拍 |
| `meteor` 流星雨 | ✅ | 极大时刻 ＝ 太阳 **J2000 黄经**达该群约定 λ☉ 之时；λ☉ 照录 IMO／RASC，**与年份无关**，对 de421 覆盖的任何年份都成立 ⇒ 非自造 |
| `planet` 行星天象 | ✅ | 合／冲／大距为黄经求根，纯几何 |
| `solar_eclipse` 日食 | ❌ | 本机 skyfield **没有**日食函数；项目口径是「照录 NASA GSFC 目录、不自造」，而现有目录只覆盖 2026—2030 ⇒ 历史日食只能逐年照录补录，**不是本脚本能批量生成的**。这比生成一堆没出处的「历史日食」正确得多 |
| `traditional`／`historical` | ❌ | 史料型条目须逐字核录出处后人工录入，不走批量生成 |
| 月相（朔／望） | ❌ | 属**历法**层，站点 `[astro_today]` 与「天文日历」页已承担该职责；在此重复会与那两处口径打架 |

★ **为什么必须扩到三族**（2026-09-23 实测的裁定依据，不是推测）：
  只收月食时，288 条摊到 366 个「月-日」上，**只有 133 天有内容（36.3%）**，
  其余 **232 天打开页面是空的**。逐族量过年率与覆盖后决定扩族：
  · 月食 2.29 次/年 ⇒ 覆盖 133 天
  · 流星雨 = 群数/年（λ☉ 锚点固定）⇒ 只多覆盖约 20 天，但那些日期上是读者最认的天象
  · 行星天象约 33 条/年 ⇒ **唯一能把日历覆盖救回来的自算族**
  ⇒ 「历史上今日」这个入口能不能用，取决于**覆盖率**；这是产品判据，须实测后再定族。

★ **重复条目的处置（页面侧，不在本脚本）**：日期锚定型事件（流星雨、行星合）
  在同一「月-日」上历年会有几十甚至上百条（如英仙座 8/12 有 126 条）。
  本脚本**照数生成**（数据不裁剪 —— 裁剪会丢信息），由模板侧
  `astro-history-today.php` **按 kind 成组、渲染成「年份清单」**。

幂等
────
输出按 (jd_core) 唯一。重跑同一区间得到逐字相同的文件（`--selftest` 会复跑一次比对）。

用法
────
    python history_events.py --selftest                       # 真算 11 年 + 对拍 + 幂等自证（三族）
    python history_events.py --from 1900 --to 2025            # 默认只出月食（快，约 11 分钟）
    python history_events.py --from 1900 --to 2025 \
        --types lunar_eclipse,meteor,planet                   # 三族全量（约 20 分钟）
    python history_events.py --from 1900 --to 2025 --push --wp-user <用户名> --wp-app-password <密码>
"""

import argparse
import hashlib
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(_HERE)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import compute_sky  # noqa: E402
import event_almanac as ea  # noqa: E402

SCRIPT_VERSION = "1.1.0"
DEFAULT_OUT = os.path.join(REPO_ROOT, "data", "events_past.json")
TABLE = "events"

# 本脚本可生成的族（**白名单**：不在表里的一律拒绝，避免静默收进不该收的族）
FAMILIES = ("lunar_eclipse", "meteor", "planet")
# 生成器名（`event_almanac.GENERATORS` 里的名字）→ 落库后的 event_type
#   ★ 一对多：`planet` 这一族在生成器侧有多个入口（合日/冲日、大距），本脚本按需取用；
#     落库后统一归到 event_type='planet'（与 cpt.php 的 kcj_astro_event_types() 一致）。
FAMILY_GENERATORS = {
    "lunar_eclipse": ["lunar_eclipse"],
    "meteor": ["meteor"],
    "planet": ["planet_sun", "planet_elongation"],
}
# 族 → 中文名（**只用于本脚本的判据输出**；页面的中文名取自插件 cpt.php 的
# kcj_astro_event_types()，两处措辞一致但**不共用**，避免跨语言引用）
FAMILY_CN = {"lunar_eclipse": "本影月食", "meteor": "流星雨", "planet": "行星天象"}

# 历史条目的 ΔT 口径：与全模块同一个模型串（列宽 64，装得下 36 字符）
DT_MODEL = compute_sky.CONFIG.DATA_VERSION

# 历史条目的时刻不确定度：**不是**「古人记载不准」，而是**本模块 ΔT 模型的不确定度**。
# 20 世纪 ΔT 已由实测（原子钟 1955 起 + 天文观测）约束，Espenak–Meeus 2006 模型在该段
# 与实测相差在秒级，故落 ±30 s。1900—1955 段略大，本脚本按年分两档，如实标注。
UNC_MODERN = "±30 s（ΔT 模型不确定度；1955 年起 ΔT 有实测值，时刻精度在秒级）"
UNC_EARLY = "±60 s（ΔT 模型不确定度；1900—1955 年 ΔT 由观测反演，年际误差可达数十秒）"
# ★ 流星雨**不能**套上面两条：它的极大时刻是「太阳黄经达该群 λ☉」的**定义值**，
#   几何本身极确定；主导不确定度是**实际峰值相对该理论时刻的偏离**（数小时，逐年不同），
#   与 ΔT 无关。照套「ΔT 模型不确定度」＝把一种误差说成了另一种。
UNC_METEOR = ("±数小时（极大时刻为 λ☉ 锚点下的**理论值**；主要不确定度是实际峰值"
              "相对理论的偏离，逐年不同，非 ΔT 不确定度）")


# ── 对拍参考（外部权威值，只照录、不推算）──────────────────────────────
# 来源①：台北市立天文科學教育館《2026 年重要天象》—— 2026-03-03 月全食七个接触时刻
#         （北京时；已用于 event_almanac.verify()）
# 来源②：NASA GSFC / Fred Espenak《Five Millennium Catalog of Lunar Eclipses》
#         与公开报道一致的著名个例：2018-07-28（北京时）月全食，
#         全食持续 1 小时 43 分，为 21 世纪最长月全食。
REF_CHECK = (
    # (北京时间日期, 类型关键词, 全食时长核证值/分钟(None=未核证), 说明, 出处)
    #
    # ★ 时长列的来历：原来的判据只比「日期 + 类型」，然后另用一条
    #   「全食最长的一条必落在 2018-07」兜底 —— 那条是**错的**（见 check() 的 ② 段）。
    #   改成把核证时长直接写进参考值、逐条比对，判据就只依赖一手源，不再依赖区间。
    ("2000-07-16", "total", 106.4, "全食 106 分钟（20 世纪最长）",
     "②NASA GSFC LEplot 2000Jul16T：Total = 01h46m24s"),
    ("2018-07-28", "total", 102.95, "全食约 103 分钟（媒体称「21 世纪最长」）",
     "②NASA GSFC 五千年月食目录／Universe Today：1h42m57s"),
    # 2011-12-10 的全食时长本轮未核证到一手值 ⇒ 留 None，只比日期与类型（不猜数）
    ("2011-12-10", "total", None, "月全食", "②NASA GSFC 五千年月食目录"),
)

# 全食时长的对拍容差（分钟）：自算与 NASA 值的实测差为 0.05—0.2 分钟，
# 取 1.5 分钟既能容纳求根/星历差异，又能抓住「差了几分钟」这类真错。
TOTALITY_TOL_MIN = 1.5

# 月全食全食时长的**物理上限**：理论上限约 1h47m（≈107 分钟）。
# 这条**与区间无关**，故可作硬断言 —— 而「最长的是哪一天」随区间变化，只能作 INFO。
TOTALITY_MAX_MIN = 107.0

# 数量合理性判据：**按年率**判，不按绝对条数 ——
# 绝对条数只对「126 年全量」这一种区间成立；自测用 11 年，若照搬绝对区间会凭空报红
# （这正是「判据与适用面不匹配」的典型：同一条断言换了个区间就失真）。
RATE_MIN, RATE_MAX = 1.5, 3.5     # 月食（保留旧名，供 selftest 的负控制引用）

# ★ 按族给年率区间 —— 三族量级差一个数量级（2.3 / 15 / 33），
#   合成一个总年率再判，等于什么都没判。
RATE_BY_TYPE = {
    # NASA 目录口径：一个世纪约 230—250 次月食（含半影食）；本模块只收**本影食**，
    # 约每年 2 次上下。
    "lunar_eclipse": (1.5, 3.5),
    # 流星雨：群数/年，λ☉ 锚点固定 ⇒ **每年恰好 = len(METEOR_SHOWERS) 次**，
    # 留一点余量防「某群跨年归到相邻年」（本表 15 群）。
    "meteor": (12.0, 18.0),
    # 行星天象（合日/冲日 + 大距）：由各行星会合周期决定，年际波动小。
    # ★ 区间**实测后**才定的，不是估的：12 年样本（1900—1905 ＋ 2020—2025）量得
    #   合日/冲日 12.08 次/年、大距 7.58 次/年 ⇒ 合计 **19.66 次/年**。
    #   （我起初按「每年十余条」的旧注释估成 [20, 60]，那会让 126 年全量**当场报红**
    #     并拒绝写盘 —— 白跑 38 分钟。判据的数值必须来自实测，不能来自注释里的印象。）
    #   取 [14, 30]：容得下会合周期的年际波动，又抓得住「某一族整体丢了」。
    "planet": (14.0, 30.0),

}



def build(y0, y1, types=None, with_planets=False, verbose=True):
    """生成 [y0, y1] 的历史事件原始列表（未落库）。

    types：族名序列，取值见 ``FAMILIES``（`lunar_eclipse` / `meteor` / `planet`）。
           留空 ⇒ **只出月食**（与 v1.0.0 行为一致，且让 `--selftest` 跑得快）。
    with_planets：v1.0.0 的旧开关，等价于在 types 里补上 `planet`（保留兼容）。
    """
    fams = list(types) if types else ["lunar_eclipse"]
    if with_planets and "planet" not in fams:
        fams.append("planet")
    unknown = [f for f in fams if f not in FAMILIES]
    if unknown:
        # ★ 拒绝而不静默忽略：写错族名却当成「跑过了」，是本项目反复踩的静默失败。
        raise ValueError("未知族：%s（可用：%s）" % (unknown, ",".join(FAMILIES)))
    which = []
    for f in fams:
        for g in FAMILY_GENERATORS[f]:
            if g not in which:
                which.append(g)
    events, stat = ea.build_events(y0, y1, which=which, verbose=verbose)
    return events, stat


def unc_and_site(row, year):
    """按族给「时刻不确定度」与「观测地口径」。

    ★ 为什么必须分族：流星雨的极大时刻是 λ☉ 锚点下的**理论值**，其主导不确定度是
      「实际峰值相对理论的偏离（数小时）」，与 ΔT 无关。若一律套
      「ΔT 模型不确定度 ±30 s」，就是把**一种误差说成了另一种**
      —— 读者会以为「极大时刻准到 30 秒内」。
    """
    t = row.get("event_type")
    if t == "meteor":
        return UNC_METEOR, "地心口径（理论极大时刻，与观测地无关）；辐射点与本地可见性见 params_json.radiant"
    if t == "lunar_eclipse":
        unc = UNC_MODERN if year >= 1955 else UNC_EARLY
        return unc, "地心几何口径；全球可见范围见 params_json.global_visibility"
    if t == "planet":
        unc = UNC_MODERN if year >= 1955 else UNC_EARLY
        return unc, "地心几何口径（合/冲/大距为日心—地心几何量，与观测地无关）"
    return (UNC_MODERN if year >= 1955 else UNC_EARLY), ""


def to_history_rows(events):
    """原始事件 → 历史条目行（补 dt_model / time_uncertainty / obs_site 口径）。"""
    rows = ea.to_rows(events, publish_status=1)
    out = []
    for ev, row in zip(events, rows):
        year = int(ea._bj_date(ev["t"].tt).year)
        row["dt_model"] = DT_MODEL
        unc, site = unc_and_site(row, year)
        row["time_uncertainty"] = unc
        row["obs_site"] = site
        out.append(row)
    return out


def check(events, rows, y0=None, y1=None, verbose=True):
    """对拍与合理性检查。返回问题清单（空 = 通过）。

    判据按**族**分列 —— ★ 一条通用纪律：**判据的适用面必须与本次实际收的族一致**。
    只收月食时把「行星年率」也判一遍，会凭空报红；收了行星却仍按「月食年率」判，
    则等于没判。故每一条都先问「本次有没有这一族」，没有就报 **n/a（无从判定）**，
    既不通过也不算失败（三态纪律）。

    判据清单：
      ① 外部逐条对拍（月食：日期/类型/全食时长；区间外或未收该族 ⇒ n/a）
      ② 全食时长物理约束（与区间无关）③ 各族年率落在物理区间
      ④ 逐条溯源字段齐备 ⑤ slug 唯一
      ⑥ 流星雨结构：**每群每年恰好一次** ⑦ 行星天象：每年条数不得为 0
    """
    problems = []
    if y0 is None:
        y0 = min(int(ea._bj_date(e["t"].tt).year) for e in events) if events else 0
    if y1 is None:
        y1 = max(int(ea._bj_date(e["t"].tt).year) for e in events) if events else 0
    fams = sorted({e.get("event_type") for e in events})
    has_lunar = "lunar_eclipse" in fams
    if verbose:
        print("\n[history_events] 对拍与合理性检查（区间 %d—%d；本次族=%s）"
              % (y0, y1, ",".join(fams) or "空"))

    by_date = {}
    for ev in events:
        bj = ea._bj_date(ev["t"].tt).isoformat()
        by_date.setdefault(bj, []).append(ev)

    # ① 外部个例逐条对拍：**日期 / 类型 / 全食时长**都要对上（区间外 ⇒ n/a）
    #
    #   ★ 三态纪律：参考值若不落在本次生成的年份区间内，属 **n/a（无从判定）**，
    #     既不算通过也不算失败 —— 早期把它当 FAIL，自测（只跑 11 年）凭空报了两条红。
    n_ref = 0
    n_dur = 0
    for date_bj, kind, exp_min, note, src_ref in REF_CHECK:
        ry = int(date_bj[:4])
        # ★ 三态：参考值若不落在本次区间内、或本次压根没收月食，都属 **n/a（无从判定）**，
        #   既不算通过也不算失败 —— 早期把它当 FAIL，自测（只跑 11 年）凭空报了两条红。
        if not has_lunar:
            if verbose:
                print("  [n/a ] %s %s —— 本次未收月食，该对拍项无从判定" % (date_bj, note))
            continue
        if ry < y0 or ry > y1:
            if verbose:
                print("  [n/a ] %s %s —— 不在本次区间 %d—%d 内，无从判定"
                      % (date_bj, note, y0, y1))
            continue
        n_ref += 1
        hit = by_date.get(date_bj)
        if not hit:
            problems.append("对拍失败：%s（%s）未算出 —— 参考出处 %s" % (date_bj, note, src_ref))
            if verbose:
                print("  [FAIL] %s %s ← %s" % (date_bj, note, src_ref))
            continue
        kinds = set(e.get("kind") for e in hit)
        if kind not in kinds:
            problems.append("对拍类型不符：%s 算出 kind=%s，期望 %s（%s）"
                            % (date_bj, sorted(kinds), kind, src_ref))
            if verbose:
                print("  [FAIL] %s 类型不符：%s" % (date_bj, sorted(kinds)))
            continue
        if verbose:
            print("  [PASS] %s %s（kind=%s）← %s" % (date_bj, note, kind, src_ref))

        # 时长核对：只在参考值有核证数时做；缺字段要报出来，不能静默跳过
        if exp_min is not None:
            got = None
            for e in hit:
                pp = e.get("params") or {}
                if pp.get("duration_totality_hr") is not None:
                    got = float(pp["duration_totality_hr"]) * 60.0
                    break
            n_dur += 1
            if got is None:
                problems.append("对拍失败：%s 缺全食时长（params.duration_totality_hr 取不到）"
                                % date_bj)
                if verbose:
                    print("  [FAIL] %s 缺全食时长字段" % date_bj)
            elif abs(got - float(exp_min)) > TOTALITY_TOL_MIN:
                problems.append("对拍时长不符：%s 自算 %.1f 分钟 vs 核证 %.1f 分钟（容差 ±%.1f）"
                                % (date_bj, got, float(exp_min), TOTALITY_TOL_MIN))
                if verbose:
                    print("  [FAIL] %s 全食 %.1f 分钟 vs 核证 %.1f 分钟"
                          % (date_bj, got, float(exp_min)))
            elif verbose:
                print("  [PASS] %s 全食 %.1f 分钟 ← 核证 %.1f 分钟（差 %+.2f）"
                      % (date_bj, got, float(exp_min), got - float(exp_min)))

    if verbose:
        print("  对拍项：日期/类型 %d 条（区间外 %d 条 n/a）｜时长 %d 条"
              % (n_ref, len(REF_CHECK) - n_ref, n_dur))
    if n_ref == 0 and has_lunar:
        problems.append("本次区间内**没有任何**外部对拍项 —— 对拍形同虚设，请调整区间或补参考值")
    elif n_ref == 0 and not has_lunar and verbose:
        print("  （本次未收月食 ⇒ 无外部对拍项可判。这是 **n/a**，不是通过）")

    # ② 全食时长的**物理约束**（与区间无关）；区间内的极值只作 INFO
    #
    #   ★ 这一段换掉了一条**错判据**，值得原样记下来：
    #     原来断言「全食最长的一条必落在 2018-07」，依据是媒体口径的
    #     「2018-07-27 是 21 世纪最长月全食」。跑 1900—2025 全区间时**当场报红** ——
    #     区间内最长的其实是 **2000-07-16**（NASA LEplot：Total = 01h46m24s = 106.4 分钟），
    #     2018-07-27 只有 1h42m57s = 102.95 分钟。自算给出 106.6 / 102.9，两处都对。
    #
    #     媒体没错：「2000 年按天文纪年属 **20 世纪**」（EarthSky 原话：
    #     「2001 is technically the first year of the 21st century」）。
    #     错的是**我把「世纪归属」当成了「跨区间最长值」**。
    #
    #   ⇒ 两条通用教训：
    #     ① **定位判据对区间敏感**（「最长是谁」换个区间就变），不能当硬断言；
    #     ② **常识必须回溯到一手源**（NASA 目录 / LEplot）才算数，
    #        媒体口径的「世纪之最」在本模块的 126 年窗口里并不成立。
    #   ⇒ 改法：逐条对拍核证值（见 ①）＋ 与区间无关的**物理上限**；
    #        区间内的极值只打印，不判定。
    long_total = None
    n_total = 0
    for ev in events:
        if ev.get("kind") != "total":
            continue
        pp = ev.get("params") or {}
        dur = pp.get("duration_totality_hr")
        if dur is None:
            continue
        n_total += 1
        label = ea._bj_date(ev["t"].tt).isoformat()
        mins = float(dur) * 60.0
        if long_total is None or mins > long_total[0]:
            long_total = (mins, label)
        if not (0.0 < mins <= TOTALITY_MAX_MIN):
            problems.append("全食时长越界：%s 自算 %.1f 分钟，超出 (0, %.0f] 的物理区间"
                            % (label, mins, TOTALITY_MAX_MIN))
    if verbose:
        print("  月全食 %d 条（有全食时长的）" % n_total)
        if long_total:
            print("  [INFO] 区间内最长的一条：%.1f 分钟 @ %s —— **仅信息，不断言**"
                  "（极值随区间变化）" % (long_total[0], long_total[1]))
            print("  [INFO] 可作参照的两条核证值：2000-07-16 = 106.4 分钟、"
                  "2018-07-27 = 102.95 分钟（NASA GSFC LEplot）")

    # ③ 各族年率落在物理合理区间（**逐族判**；未收的族报 n/a）
    #
    #   ★ 为什么不能合成一个总年率：三族量级差一个数量级（月食 2.3／流星 15／行星 33），
    #     加起来除以年数得到一个 50 上下的数，任何一族归零都看不出来 ⇒ 等于没判。
    years = max(1, y1 - y0 + 1)
    for fam, (lo, hi) in sorted(RATE_BY_TYPE.items()):
        if fam not in fams:
            if verbose:
                print("  [n/a ] %s：本次未收该族，年率无从判定" % fam)
            continue
        cnt = sum(1 for r in rows if r.get("event_type") == fam)
        rate = cnt / float(years)
        label = FAMILY_CN.get(fam, fam)
        if lo <= rate <= hi:
            if verbose:
                print("  [PASS] %s %d 条 / %d 年 = 每年 %.2f，落在 [%.1f, %.1f]"
                      % (label, cnt, years, rate, lo, hi))
        else:
            problems.append("%s年率 %.2f 落在 [%.1f, %.1f] 之外（%d 条 / %d 年）"
                            % (label, rate, lo, hi, cnt, years))
            if verbose:
                print("  [FAIL] %s年率 %.2f 超出区间" % (label, rate))

    # ⑥ 流星雨结构：**每群每年恰好一次**
    #    λ☉ 锚点在一年里只过一次 ⇒ 「每群每年一次」是**结构性事实**，可作硬断言。
    #    漏一群或少一年，都会让「历史上今日」在某天凭空少一条（且静默）。
    if "meteor" in fams:
        per = {}
        for r in rows:
            if r.get("event_type") != "meteor":
                continue
            y = int(str(r["event_time_bj"])[:4])
            name = str(r.get("title") or "").split("极大")[0]
            per[(y, name)] = per.get((y, name), 0) + 1
        n_show = len(ea.METEOR_SHOWERS)
        dupe = sorted(k for k, v in per.items() if v != 1)
        by_year = {}
        for (y, _name) in per:
            by_year[y] = by_year.get(y, 0) + 1
        short = sorted((y, c) for y, c in by_year.items() if c != n_show)
        if dupe or short:
            problems.append("流星雨结构异常：同年同群重复=%s；群数不足的年份=%s"
                            % (dupe[:3], short[:3]))
        if verbose:
            print("  [%s] 流星雨每群每年恰好 1 次（%d 群 × %d 年，实得 %d 条）"
                  % ("PASS" if not (dupe or short) else "FAIL",
                     n_show, len(by_year), len(per)))

    # ⑦ 行星天象：每年条数不得为 0（会合周期决定，任何一年都不该整年空）
    if "planet" in fams:
        py = {}
        for r in rows:
            if r.get("event_type") != "planet":
                continue
            y = int(str(r["event_time_bj"])[:4])
            py[y] = py.get(y, 0) + 1
        empty = sorted(y for y in range(y0, y1 + 1) if not py.get(y))
        if empty:
            problems.append("行星天象有 %d 个年份整年 0 条：%s" % (len(empty), empty[:5]))
        if verbose:
            print("  [%s] 行星天象逐年非空（%d 年，最少的一年 %d 条）"
                  % ("PASS" if not empty else "FAIL",
                     len(py), min(py.values()) if py else 0))

    # ④ 逐条契约：必填列不为空（历史条目的溯源字段是红线）—— **不分族，一律适用**
    bad = []
    for r in rows:
        for k in ("dt_model", "time_uncertainty", "source_ref", "method", "ephemeris", "slug"):
            if not r.get(k):
                bad.append("%s 缺 %s" % (r.get("slug") or r.get("title"), k))
    if bad:
        problems.append("历史条目缺溯源字段：%s" % "; ".join(bad[:5]))
    if verbose:
        print("  [%s] 历史条目溯源字段齐备（dt_model / time_uncertainty / source_ref / method / ephemeris）"
              % ("PASS" if not bad else "FAIL"))

    # ⑤ slug 唯一
    slugs = [r["slug"] for r in rows]
    dup = sorted({s for s in slugs if slugs.count(s) > 1})
    if dup:
        problems.append("slug 重复：%s" % dup[:5])
    if verbose:
        print("  [%s] slug 唯一（%d 条）" % ("PASS" if not dup else "FAIL", len(slugs)))

    return problems


def write_json(rows, path):
    rows = sorted(rows, key=lambda r: (r["jd_core"], r["slug"]))
    txt = json.dumps(rows, ensure_ascii=False, indent=1, sort_keys=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(txt + "\n")
    return path, len(rows), hashlib.sha1(txt.encode("utf-8")).hexdigest()


def selftest():
    """真算 5 年 + 对拍 + 幂等自证。"""
    # ★ 必须声明 global：下面的负控制要**临时替换模块级 REF_CHECK** 来喂错值。
    #   不声明就成了局部变量，check() 读到的仍是原表，负控制会**假通过**。
    global REF_CHECK
    problems, ok = [], 0

    def chk(name, cond, detail=""):
        nonlocal ok
        if cond:
            ok += 1
            print("  [PASS] %s %s" % (name, detail))
        else:
            problems.append("%s %s" % (name, detail))
            print("  [FAIL] %s %s" % (name, detail))

    print("[history_events] selftest：真算 2015—2025（11 年 · 三族）")
    print("  （约 3—5 分钟。比 v1.0.0 慢是因为收了流星雨与行星天象，**不是卡住**）")
    ev, _ = build(2015, 2025, types=list(FAMILIES), verbose=False)
    rows = to_history_rows(ev)
    got = sorted({r["event_type"] for r in rows})
    chk("11 年算出条目", len(rows) > 0, "= %d 条" % len(rows))
    chk("★ 三族齐备", got == sorted(FAMILIES), "实得 %s" % got)
    chk("★ 未收白名单之外的族（本脚本的族是白名单制）",
        all(t in FAMILIES for t in got), "实得 %s" % got)
    chk("全部已发布", all(r["publish_status"] == 1 for r in rows), "= %d 条" % len(rows))

    # 不确定度必须**按族**给：流星雨套「ΔT 模型 ±30 s」是错的（见 unc_and_site 的说明）
    mu = [r["time_uncertainty"] for r in rows if r["event_type"] == "meteor"]
    chk("★ 流星雨的不确定度口径不是 ΔT（不得套用 ±30 s 那一套）",
        bool(mu) and all("非 ΔT" in x for x in mu),
        "样例：%s" % (mu[0][:30] + "…" if mu else "无"))

    # 对拍：2018-07-27/28 月全食存在（**不再**说它是「21 世纪最长」——
    # 该口径按天文纪年属 20 世纪的 2000-07-16 更长，见模块内 check() 的 ② 段说明）
    hits = [r for r in rows if str(r.get("event_time_bj") or "").startswith("2018-07-2")]
    chk("★ 对拍：2018-07-27/28 月全食存在", bool(hits),
        "命中 %d 条：%s" % (len(hits), [h["slug"] for h in hits]))

    probs = check(ev, rows, 2015, 2025, verbose=True)
    chk("对拍与合理性检查全部通过", not probs, "; ".join(probs[:3]) or "无问题")

    # ★ 负控制组 —— 证明新增的判据**不是空壳**。
    #   （本项目纪律：任何新判据都要给出「喂错值会报红」的实证，否则等于用全绿换心安。）
    _saved = REF_CHECK
    try:
        REF_CHECK = (("2018-07-28", "total", 90.0, "负控制·时长写错", "负控制"),
                     ("2011-12-10", "total", None, "月全食", "负控制"))
        _bad = check(ev, rows, 2015, 2025, verbose=False)
        chk("★ 负控制：核证时长写错（102.95→90）必被判不符（时长核对非恒真）",
            any("时长不符" in x for x in _bad), "%s" % (_bad[:2] or "无"))
    finally:
        REF_CHECK = _saved

    # 物理上限：把某条 total 的全食时长改成 200 分钟（超 107 分钟上限）
    # 只浅拷贝顶层并替换 params —— 不 deepcopy 事件本身（内含 Skyfield Time 对象）
    fake = [dict(e) for e in ev]
    for e in fake:
        if e.get("kind") == "total":
            pp = dict(e.get("params") or {})
            pp["duration_totality_hr"] = 200.0 / 60.0
            e["params"] = pp
            break
    _bad2 = check(fake, rows, 2015, 2025, verbose=False)
    chk("★ 负控制：全食时长 200 分钟（超物理上限）必被判越界（上限判据非恒真）",
        any("越界" in x for x in _bad2), "%s" % (_bad2[:2] or "无"))

    # ★ 负控制：**判据的适用面必须随族走** —— 只收月食时，不得去判流星雨/行星的年率。
    #   这一条守的是「加族扩面」这个动作本身：扩族时若忘改判据的适用面，就会凭空报红；
    #   反过来，若判据写死「只看月食」，则收进来的流星雨/行星**等于没判**。
    _only_lunar = [e for e in ev if e.get("event_type") == "lunar_eclipse"]
    _only_rows = [r for r in rows if r.get("event_type") == "lunar_eclipse"]
    _p = check(_only_lunar, _only_rows, 2015, 2025, verbose=False)
    chk("★ 负控制：只收月食时不判其它族的年率（判据适用面随族走）",
        not any("流星雨" in x or "行星天象" in x for x in _p), "%s" % (_p[:2] or "无问题"))

    # ★ 负控制：流星雨少一条（某年某群缺失）必须被 ⑥ 抓出 —— 这类缺失是**静默**的，
    #   只会让「历史上今日」在某天少一条，页面上看不出来。
    _m = [r for r in rows if r.get("event_type") == "meteor"]
    if _m:
        _fewer = [r for r in rows if r is not _m[0]]
        _p2 = check(ev, _fewer, 2015, 2025, verbose=False)
        chk("★ 负控制：流星雨少一条（某年某群缺失）必被 ⑥ 报出",
            any("流星雨结构异常" in x for x in _p2), "%s" % (_p2[:2] or "无"))
    else:
        problems.append("负控制无法执行：本次没有流星雨条目")
        print("  [FAIL] 负控制无法执行：本次没有流星雨条目")

    # ★ 负控制：族名写错必须**报错**，不得静默忽略（静默忽略＝把「没跑」说成「跑过了」）
    try:
        build(2015, 2016, types=["meteor_shower"], verbose=False)
        _raised = False
    except ValueError:
        _raised = True
    chk("★ 负控制：未知族名必须抛 ValueError（不得静默忽略）", _raised, "未知族名")

    # 负控制：区间外不带进来
    chk("★ 负控制：区间收口（2015—2025 内不含 2014 年条目）",
        all(int(str(r["event_time_bj"])[:4]) >= 2015 for r in rows),
        "最早 %s" % min(str(r["event_time_bj"])[:4] for r in rows))

    # 幂等：同区间重跑，字节一致
    import tempfile
    ev2, _ = build(2015, 2025, types=list(FAMILIES), verbose=False)
    rows2 = to_history_rows(ev2)
    with tempfile.TemporaryDirectory() as tmp:
        p1, n1, h1 = write_json(rows, os.path.join(tmp, "a.json"))
        p2, n2, h2 = write_json(rows2, os.path.join(tmp, "b.json"))
    chk("★ 幂等：同区间重跑产物逐字节相同", h1 == h2 and n1 == n2,
        "sha1 %s / %s" % (h1[:12], h2[:12]))

    print("[history_events] selftest：通过 %d 项，失败 %d 项" % (ok, len(problems)))
    return 0 if not problems else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="生成历史天象数据集（月食／流星雨／行星天象，皆自算）")
    ap.add_argument("--from", dest="y0", type=int, default=1900,
                    help="起始年（含）。下限受星历约束：de421 覆盖自 1899-07-28 起")
    ap.add_argument("--to", dest="y1", type=int, default=None,
                    help="结束年（含）。默认＝**去年**（今年不是历史）")
    ap.add_argument("--types", default="lunar_eclipse",
                    help="收哪几族，逗号分隔。可用：%s（默认只出月食；"
                         "三族全量约 20 分钟）" % ",".join(FAMILIES))
    ap.add_argument("--with-planets", action="store_true",
                    help="v1.0.0 旧开关，等价于在 --types 里补上 planet（保留兼容）")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--wp-site", default="", help="WordPress 站点地址，如 https://example.com")
    ap.add_argument("--wp-user", default="")
    ap.add_argument("--wp-app-password", default="")
    ap.add_argument("--dry-run", action="store_true", help="只算不写盘")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    import datetime as _dt
    y1 = args.y1 if args.y1 is not None else (_dt.date.today().year - 1)
    if args.y0 < 1900:
        print("[history_events] 起始年 %d 早于 1900：de421 只覆盖 1899-07-28 起，"
              "更早年份须换 de422/de431（本机未安装）⇒ 拒绝生成，以免静默降级。" % args.y0,
              file=sys.stderr)
        return 2
    if y1 < args.y0:
        print("[history_events] 结束年早于起始年", file=sys.stderr)
        return 2

    t0 = time.time()
    types = [t.strip() for t in str(args.types).split(",") if t.strip()]
    if not types:
        print("[history_events] --types 为空：没有要生成的族。"
              "可用：%s" % ",".join(FAMILIES), file=sys.stderr)
        return 2
    ev, stat = build(args.y0, y1, types=types, with_planets=args.with_planets)
    rows = to_history_rows(ev)
    print("[history_events] %d—%d：族=%s｜原始 %d 条 → 落库行 %d 条，用时 %.0f s"
          % (args.y0, y1, ",".join(types), len(ev), len(rows), time.time() - t0))

    # 空集守卫
    if not rows:
        print("[history_events] 致命：0 条产物（空集守卫）", file=sys.stderr)
        return 3

    problems = check(ev, rows, args.y0, y1)
    if problems:
        print("[history_events] 致命：%d 项检查未过，不写盘：%s"
              % (len(problems), "; ".join(problems[:5])), file=sys.stderr)
        return 3

    if args.dry_run:
        print("[history_events] dry-run：未写盘")
        return 0

    path, n, sha = write_json(rows, args.out)
    print("[history_events] 写出 %s（%d 行，sha1 %s）"
          % (os.path.relpath(path, REPO_ROOT), n, sha[:12]))

    if args.push:
        if not (args.wp_user and args.wp_app_password):
            print("[history_events] --push 需要 --wp-user 与 --wp-app-password", file=sys.stderr)
            return 2
        try:
            res = compute_sky.push_rest(rows, TABLE, args.wp_site,
                                        args.wp_user, args.wp_app_password)
            print("[history_events] 推送：%s" % json.dumps(res, ensure_ascii=False))
            compute_sky.flush_remote_cache(args.wp_site, args.wp_user, args.wp_app_password)
        except Exception as exc:  # noqa: BLE001
            print("[history_events] 推送失败：%s" % exc, file=sys.stderr)
            return 2
    else:
        print("[history_events] 未推送（加 --push 与凭据）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
