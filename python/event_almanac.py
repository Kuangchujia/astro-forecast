#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""event_almanac.py — 天象事件的**时刻求根**与事件行装配（v1.3.0）

━━━ 分工（与 compute_sky.py 的边界） ━━━
  · 天体量（黄经／黄纬／距离／月相角／角距）——**一律**走 compute_sky.py 的
    公开访问器（`body_ecl_lonlat` / `sun_body_lon_sep_deg` / `moon_sun_phase_deg`
    / `body_pair_separation_deg`）。本文件**不**自己算星历。
  · 本文件只做三件事：**求根 → 去重 + slug → 装配成 wp_astro_events 白名单行**。

━━━ 红线：不编造事件 ━━━
本模块**只**产出两类事件：
  ① **可算事件**——判据写成公式、能用 de421 精算并可与公开年历对拍（行星合冲、
     留、大距、互合；月食；流星雨极大）。
  ② **照录事件**——数值本身是**观测统计结论或权威机构预报结果**，无法由星历推出，
     故**照录权威来源并逐条标注出处**（流星雨 λ☉、日食目录）。
  绝不「为了让某个 Tab 有内容」而生成占位事件。某个类型一件都没有，就让它空着。

━━━ 时刻口径（三个尺度，混用会错） ━━━
  · 内部一律 **TT**（`t.tt`）—— 求根、排序、写 `jd_core` 都用它。
  · 交付一律 **北京时间**（= UTC+8）—— 由 `ts.tt_jd(jd).utc_datetime()` 一条路得出，
    **不另走** `compute_sky.jde_to_jd_ut()`。
    ★ 为什么要专门交代：项目自带 ΔT 模型（Espenak-Meeus 2006）在 2026—2030 给
      **63.0 s**，而 skyfield 时刻尺度的实际 TT−UT1 是 **69.1 s**（本轮实测）。
      两者差 **6.1 s**。单看对「分钟级」交付无影响，但**两处混用**会在同一份
      数据里引入 6 秒级不一致 —— 故本模块**只走一条路**。
  · 与 NASA 目录对拍时：NASA 表头写的是 **TD of Greatest Eclipse，即 TT**，
    **不是** UT。把它直接当北京时间用会差 69 s；已在 `_td_to_bj()` 里显式换算。

━━━ 复用的求根范式（都是本项目已实测校准过的，不另起炉灶） ━━━
  A. **判合/冲用 `sin(黄经差)` 定根，极值处再用 `cos` 别种类** —— 角度值在 ±180°
     处跳变，直接二分会把跳变点当根（`planet_retro.py` 2026-09-19 实测：火星
     2027-02-19 的**冲**被误标成**合**）。
  B. **求极值用「导数符号翻转 + 二分」，不用「序列最小值索引」** —— 平处的舍入
     抖动会造出假极值（`lunar_data.py` 2026-09-19 实测报出 25 天假窗口）。
  C. **粗扫向量化、精化落标量** —— 粗扫一次算几千点，只在变号区间做二分。

━━━ 明文纪律：显示字段一个字面标记都不留 ━━━
  本模块产出的每个字符串最终都会被 WP 端 `esc_html()` 直出（标题／摘要／观测指南／
  参数表一律如此，见 templates/astro-event-detail.php），**不会**经过 Markdown 渲染。
  故字符串里**不得**出现 `**粗体**` 之类的标记 —— 读者会看见两个字面星号。
  ★ 这不是新问题：v1.2.0 就修过模板里同样的写法（注释原文：「解析降级说明里写了
    Markdown 的 `**未使用**`，在 HTML 里不会变成粗体，用户会看到两个星号」）。
    本轮实测：2026 年 64 条里有 **51 条**中招（summary 21／obs_guide 17／params 39）。
  ⇒ 出口只有一个：`to_rows()` 统一过 `_plain()`（含 params 递归）。判据在 `--selftest`。

━━━ 用法 ━━━
  python event_almanac.py --range 2026 2030                    生成事件（表格）
  python event_almanac.py --range 2026 2030 --format json      JSON（events 白名单行）
  python event_almanac.py --range 2026 2030 --out events.json  写文件
  python event_almanac.py --verify                             与权威目录对拍
  python event_almanac.py --selftest                           自检（含空集守卫、slug 幂等）
"""

import argparse
import datetime as dt
import json
import math
import os
import re
import sys
import warnings

warnings.filterwarnings("ignore")

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import compute_sky as cs  # noqa: E402  （同目录，唯一权威计算内核）

SCRIPT_VERSION = "1.1.0"
TZ_HOURS = 8

# 星历覆盖（写进每行的 ephemeris 列做溯源）
EPH_LABEL = "de421.bsp（1899-07-28 至 2053-10-08）"


# =============================================================================
# 照录表一：流星雨极大（λ☉）
# =============================================================================
# ★ 这张表**不是**本库自算的。极大时刻本身是**观测统计结论**——它取决于地球穿越
#   流星体带最密处的几何，而那团物质的分布无法从星历推出来。故 λ☉ 由外部给定。
#   本模块做的是**下一步**：「太阳视黄经何时达到该 λ☉」—— 这一步可以精算。
# ★ 三源互校（2026-09-23 检索，数值逐条比对）：
#     ① IMO《Meteor Shower Calendar》官方年历（imo.net/?p=1396）
#     ② RASC《Observer's Handbook 2025》p.254「TABLE OF METEOR SHOWERS FOR 2025」
#     ③ IMO working list 对照论文（Semantic Scholar 收录，Table 1）
#   结果：下表 13 群的 λ☉ **三源一致**，唯「狮子座流星雨」有三写法
#   235.16° / 235.27° / 235.30°（极差 0.14° ≈ 3.4 小时），本表取 IMO 年历的
#   235.27°，并在该条 params 里注明分歧 —— 不隐去。
# ★ ZHR = 天顶每时出现率（观测统计值，随年份与月光条件变化，仅作量级参考）。
METEOR_SHOWERS = (
    {"code": "QUA", "cn": "象限仪座流星雨", "lam": 283.16, "zhr": 120,
     "radiant": "赤经 230°／赤纬 +49°", "speed_kms": 41},
    {"code": "LYR", "cn": "天琴座流星雨", "lam": 32.32, "zhr": 18,
     "radiant": "赤经 271°／赤纬 +34°", "speed_kms": 49},
    {"code": "ETA", "cn": "宝瓶座η流星雨", "lam": 45.50, "zhr": 65,
     "radiant": "赤经 338°／赤纬 −01°", "speed_kms": 66},
    {"code": "SDA", "cn": "宝瓶座δ南流星雨", "lam": 125.00, "zhr": 16,
     "radiant": "赤经 340°／赤纬 −16°", "speed_kms": 41},
    {"code": "CAP", "cn": "摩羯座α流星雨", "lam": 127.00, "zhr": 5,
     "radiant": "赤经 307°／赤纬 −10°", "speed_kms": 23},
    {"code": "PER", "cn": "英仙座流星雨", "lam": 140.00, "zhr": 100,
     "radiant": "赤经 048°／赤纬 +58°", "speed_kms": 59},
    {"code": "KCG", "cn": "天鹅座κ流星雨", "lam": 145.00, "zhr": 3,
     "radiant": "赤经 286°／赤纬 +59°", "speed_kms": 25},
    {"code": "AUR", "cn": "御夫座α流星雨", "lam": 158.60, "zhr": 6,
     "radiant": "赤经 091°／赤纬 +39°", "speed_kms": 66},
    {"code": "DRA", "cn": "天龙座流星雨", "lam": 195.40, "zhr": 5,
     "radiant": "赤经 262°／赤纬 +54°", "speed_kms": 20},
    {"code": "ORI", "cn": "猎户座流星雨", "lam": 208.00, "zhr": 25,
     "radiant": "赤经 095°／赤纬 +16°", "speed_kms": 66},
    {"code": "STA", "cn": "金牛座南流星雨", "lam": 223.00, "zhr": 5,
     "radiant": "赤经 052°／赤纬 +13°", "speed_kms": 27},
    {"code": "NTA", "cn": "金牛座北流星雨", "lam": 230.00, "zhr": 5,
     "radiant": "赤经 058°／赤纬 +22°", "speed_kms": 29},
    {"code": "LEO", "cn": "狮子座流星雨", "lam": 235.27, "zhr": 15,
     "radiant": "赤经 152°／赤纬 +22°", "speed_kms": 71,
     "note": "λ☉ 三源有分歧：IMO 年历 235.27°／RASC 2025 235.30°／1999 版 235.16°，"
             "极差 0.14°≈3.4 小时；本表取 IMO 年历值。"},
    {"code": "GEM", "cn": "双子座流星雨", "lam": 262.20, "zhr": 120,
     "radiant": "赤经 112°／赤纬 +33°", "speed_kms": 35},
    {"code": "URS", "cn": "小熊座流星雨", "lam": 270.70, "zhr": 10,
     "radiant": "赤经 217°／赤纬 +76°", "speed_kms": 33},
)

METEOR_SOURCE_REF = (
    "IMO Meteor Shower Calendar（λ☉ 极大值）；RASC Observer's Handbook 2025 p.254；"
    "IMO working list 对照论文 Table 1。三源互校，分歧已如实标注。"
)

# =============================================================================
# 照录表二：日食目录（NASA GSFC / Fred Espenak）
# =============================================================================
# ★ 为什么日食**不**自算：本轮核实（2026-09-23）本机 skyfield 1.55 的
#   `skyfield.eclipselib` **只有 lunar_eclipses，没有日食函数**。日食要算准，
#   需要贝塞尔元素／影锥与地球椭球求交，属独立模块。
#   在它建成之前，**宁可照录权威目录并注明出处，也不自算后当成自己的结论**。
#   （月食不同：eclipselib 有 lunar_eclipses，且本轮已与 NASA 目录逐条对拍通过，
#     故月食走**自算**。这就是两条路并存的理由。）
# ★ 时刻口径：NASA 表头写 "TD of Greatest Eclipse"，**TD 即 TT**，不是 UT。
#   本表的 `td` 字段照录 TT 时刻，由 `_td_to_bj()` 现算北京时间（含 ΔT 折算）。
# ★ 两源互校：NASA SEdecade2021 与《21世纪日食列表》（百度百科）逐条数值一致
#   （含沙罗周期号、食分），仅秒位偶有 ±1 s 的四舍五入差。
SOLAR_ECLIPSE_CATALOG = (
    {"date_ut": "2026-02-17", "td": "12:13:05", "kind": "annular", "saros": 121,
     "mag": 0.963, "central": "2m20s",
     "region": "南极洲见环食；南阿根廷、智利、南非南部、南极圈一带见偏食"},
    {"date_ut": "2026-08-12", "td": "17:47:05", "kind": "total", "saros": 126,
     "mag": 1.039, "central": "2m18s",
     "region": "北极、格陵兰、冰岛、西班牙见全食；北美北部、西非、欧洲见偏食"},
    {"date_ut": "2027-02-06", "td": "16:00:47", "kind": "annular", "saros": 131,
     "mag": 0.928, "central": "7m51s",
     "region": "智利、阿根廷、南大西洋见环食；南美、南极洲、非洲南部与西部见偏食"},
    {"date_ut": "2027-08-02", "td": "10:07:49", "kind": "total", "saros": 136,
     "mag": 1.079, "central": "6m23s",
     "region": "摩洛哥、西班牙、阿尔及利亚、利比亚、埃及、沙特、也门、索马里见全食；"
               "非洲、欧洲、中东、亚洲南部与西部见偏食"},
    {"date_ut": "2028-01-26", "td": "15:08:58", "kind": "annular", "saros": 141,
     "mag": 0.921, "central": "10m27s",
     "region": "厄瓜多尔、秘鲁、巴西、苏里南、西班牙、葡萄牙见环食；"
               "北美东部、中南美、西欧、非洲西北部见偏食"},
    {"date_ut": "2028-07-22", "td": "02:56:39", "kind": "total", "saros": 146,
     "mag": 1.056, "central": "5m10s",
     "region": "澳大利亚、新西兰见全食；东南亚、东印度群岛见偏食"},
    {"date_ut": "2029-01-14", "td": "17:13:47", "kind": "partial", "saros": 151,
     "mag": 0.871, "central": None,
     "region": "北美、中美见偏食"},
    {"date_ut": "2029-06-12", "td": "04:06:13", "kind": "partial", "saros": 118,
     "mag": 0.458, "central": None,
     "region": "北极、斯堪的纳维亚、阿拉斯加、亚洲北部、加拿大北部见偏食"},
    {"date_ut": "2029-07-11", "td": "15:37:18", "kind": "partial", "saros": 156,
     "mag": 0.230, "central": None,
     "region": "智利南部、阿根廷南部见偏食"},
    {"date_ut": "2029-12-05", "td": "15:03:57", "kind": "partial", "saros": 123,
     "mag": 0.891, "central": None,
     "region": "阿根廷南部、智利南部、南极洲见偏食"},
    {"date_ut": "2030-06-01", "td": "06:29:13", "kind": "annular", "saros": 128,
     "mag": 0.944, "central": "5m21s",
     "region": "阿尔及利亚、突尼斯、希腊、土耳其、俄罗斯、中国北部、日本见环食；"
               "欧洲、北非、中东、亚洲、北极圈见偏食"},
    {"date_ut": "2030-11-25", "td": "06:51:37", "kind": "total", "saros": 133,
     "mag": 1.047, "central": "3m44s",
     "region": "纳米比亚、博茨瓦纳、南非、澳大利亚见全食；南大西洋、南极洲见偏食"},
)

SOLAR_SOURCE_REF = (
    "Eclipse Predictions by Fred Espenak, NASA's GSFC — Solar Eclipses 2021–2030"
    "（eclipse.gsfc.nasa.gov/SEdecade/SEdecade2021.html）；与《21世纪日食列表》互校。"
)

LUNAR_SOURCE_REF = (
    "自算：skyfield 1.55 eclipselib.lunar_eclipses（星历 de421）；"
    "已与 NASA GSFC Lunar Eclipses 2021–2030 目录逐条对拍（见 --verify）。"
)

# =============================================================================
# 照录表三：月食对拍底本（NASA GSFC，**只用于 --verify，不进事件集**）
# =============================================================================
# 字段：日期(UT 日期，NASA 按 UT 日列) / TD 食甚时刻 / 类型 / 食分(本影) / 沙罗
LUNAR_REFERENCE = (
    ("2026-03-03", "11:34:52", "total", 1.151, 133),
    ("2026-08-28", "04:14:04", "partial", 0.930, 138),
    ("2027-02-20", "23:14:06", "penumbral", -0.057, 143),
    ("2027-07-18", "16:04:09", "penumbral", -1.068, 110),
    ("2027-08-17", "07:14:59", "penumbral", -0.525, 148),
    ("2028-01-12", "04:14:13", "partial", 0.066, 115),
    ("2028-07-06", "18:20:57", "partial", 0.389, 120),
    ("2028-12-31", "16:53:15", "total", 1.246, 125),
    ("2029-06-26", "03:23:22", "total", 1.844, 130),
    ("2029-12-20", "22:43:12", "total", 1.117, 135),
    ("2030-06-15", "18:34:34", "partial", 0.502, 140),
    ("2030-12-09", "22:28:51", "penumbral", -0.163, 145),
)

# =============================================================================
# 中文名与阈值
# =============================================================================
KIND_CN = {
    "opposition": "冲日", "conjunction": "合日",
    "superior_conjunction": "上合", "inferior_conjunction": "下合",
    "greatest_elongation_east": "东大距", "greatest_elongation_west": "西大距",
    "station_retrograde": "留（转逆行）", "station_direct": "留（转顺行）",
    "planet_conjunction": "行星互合",
    "penumbral": "半影月食", "partial": "月偏食", "total": "月全食",
    "annular": "日环食", "hybrid": "全环食", "partial_solar": "日偏食",
}

# 行星互合的可观测性阈值：两天体**真角距**超过此值就不收。
# 为何要设：黄经相同不代表看上去近 —— 两行星黄纬可差十几度。
# 传统「合」只要求同度，但站上列出来的是给读者看的「天上挨在一起」，
# 取 6° 作界（肉眼判定「靠近」通常以 5° 为界，留 1° 余量），并在 params 里
# 记下真实角距，读者可自行判断。
PAIR_CONJ_MAX_SEP_DEG = 6.0


# =============================================================================
# 求根引擎
# =============================================================================
def _np():
    import numpy as _numpy
    return _numpy


def _jd_bj_str(jd_tt, tz_hours=TZ_HOURS):
    """TT 儒略日 → 北京时间字符串（YYYY-MM-DD HH:MM:SS）。

    ★ 唯一转换路径：走 `ts.tt_jd(...).utc_datetime()`，不另走 jde_to_jd_ut()。
      理由见模块 docstring「时刻口径」。
    """
    ts = cs.timescale()
    return (ts.tt_jd(jd_tt).utc_datetime() + dt.timedelta(hours=tz_hours)
            ).strftime("%Y-%m-%d %H:%M:%S")


def _bj_date(jd_tt, tz_hours=TZ_HOURS):
    """TT 儒略日 → 北京时间的日期（datetime.date）。"""
    ts = cs.timescale()
    return (ts.tt_jd(jd_tt).utc_datetime() + dt.timedelta(hours=tz_hours)).date()


def _tt_jd_from_td(date_str, hhmmss):
    """**TD（=TT）** 日期 + 时刻 → TT 儒略日。

    ★ 这一步是坑，必须走「日历儒略日 + 按 TT 记时分秒」，不能拿 UTC 时刻当 TT：
      NASA 目录表头写的是 "TD of Greatest Eclipse"，**TD 即 TT**。若把
      12:13:05 当 UTC 直接构造，得到的 TT 会偏 69.184 秒（32.184 s 力学时差
      + 37 s 闰秒），虽不足分钟，但会让「日食 vs 自算朔」的一致性检查
      **凭空多出 69 秒误差**，掩盖真实问题。
    ★ `t.utc` 是**日历儒略日**（不带尺度含义），故 `ts.utc(y,m,d,0,0,0).utc`
      就是该日 0h 的儒略日整数/半整数，拿它当基准再加时分秒即可。
    """
    y, m, d = (int(x) for x in date_str.split("-"))
    hh, mm, ss = (int(x) for x in hhmmss.split(":"))
    return cs.calendar_jd(y, m, d, hh + mm / 60.0 + ss / 3600.0)


def _td_to_bj(date_str, hhmmss, tz_hours=TZ_HOURS):
    """**TD（=TT）** 日期 + 时刻 → 北京时间字符串（YYYY-MM-DD HH:MM:SS）。"""
    ts = cs.timescale()
    jd_tt = _tt_jd_from_td(date_str, hhmmss)
    return (ts.tt_jd(jd_tt).utc_datetime() + dt.timedelta(hours=tz_hours)
            ).strftime("%Y-%m-%d %H:%M:%S")


def _bisect_sign(f, a, b, tol_s=20.0, max_iter=60):
    """在 [a, b]（TT 儒略日）内二分求 **f 的变号点**。

    f 必须接受单个 float，返回单个 float，且**在区间内连续**——
    故调用方须把它写成 `sin(黄经差)` 这类包裹量，不能直接用角度值。
    返回 (根 jd, 根处的 f 值)。
    """
    fa = f(a)
    for _ in range(max_iter):
        m = (a + b) / 2.0
        fm = f(m)
        if (fa > 0) == (fm > 0):
            a, fa = m, fm
        else:
            b = m
        if abs(b - a) * 86400.0 < tol_s:
            break
    root = (a + b) / 2.0
    return root, f(root)


def _scan_sign_changes(jds, vals):
    """粗扫序列里相邻两点**符号位不同**的下标（返回 i，区间为 [i, i+1]）。

    ★ 用 `signbit` 而不是 `(v[i] > 0) != (v[i+1] > 0)`：后者把 0 归到「非正」，
      当序列恰好落在 0 上时两侧都不算变号，会漏掉一个真根。
    """
    n = _np()
    sb = n.signbit(n.asarray(vals, dtype=float))
    return [int(i) for i in n.where(sb[:-1] != sb[1:])[0]]


def _refine_extremum_jd(f, a, b, tol_s=20.0):
    """在 [a, b] 内求 **f 的极值点**（＝ f' 的零点），二分导数。

    ★ 只用于「已知 a、b 之间恰有一个极值」的窄区间；粗定位由
      `_scan_sign_changes(rate_series)` 完成。
    """
    h = 0.02  # 天，≈29 分钟；与 planet_retro.refine_zero 同口径

    def deriv(jd):
        return (f(jd + h) - f(jd - h)) / (2.0 * h)

    return _bisect_sign(deriv, a, b, tol_s=tol_s)[0]


def _root_of_angle_diff(angle_fn, jd0, jd1, step=0.25, tol_s=20.0):
    """求 `angle_fn(jd)` 的零点，`angle_fn` 返回**角度差**（度，可能跳变）。

    做法：粗扫用 `sin(弧度)`（在 ±180° 包裹下连续），精化时仍对 sin 二分，
    最后回到角度值。**不**直接对角度二分 —— 见 planet_retro.py 的实测教训。
    """
    n = _np()
    jds = n.arange(jd0, jd1, step)
    if len(jds) < 2:
        return []
    vals = n.sin(n.radians(n.asarray(angle_fn(jds), dtype=float)))
    out = []
    for i in _scan_sign_changes(jds, vals):
        root, _ = _bisect_sign(
            lambda j: math.sin(math.radians(float(angle_fn(j)))), jds[i], jds[i + 1],
            tol_s=tol_s)
        out.append(root)
    return out


# =============================================================================
# 地影几何（月食接触时刻用；口径与 eclipselib 内部一致）
# =============================================================================
_R_SUN_KM = 696340.0
_R_MOON_KM = 1737.1


def lunar_shadow_geometry(eph, t):
    """地影几何（全部为**弧度**）：返回 dict(sep, r_moon, r_pen, r_um)。

    口径**照抄** skyfield `eclipselib.lunar_eclipses` 内部（Danjon 1.01 放大）：
      sep    = **月心到影轴的角距**（＝月心方向 与 **反日点**方向 之夹角）
      r_moon = arcsin(R_moon / |月地距|)
      r_pen  = 1.01·π_m + π_s + s_s        （半影半径）
      r_um   = 1.01·π_m + π_s − s_s        （本影半径）
    其中 π_m = R_E/|月地距|、π_s = R_E/|地日距|、s_s = R_sun/|地日距|。

    ★★ `sep` 这个量极易算反，必须交代清楚（本轮实测 2026-09-23 踩到）：
      「月心方向与**太阳**方向的夹角」在食甚处接近 **180°**（满月时日月对望），
      而「月心到**影轴**的角距」在食甚处接近 **0**。两者是**补角**关系。
      初版直接用了 `to_sun.separation_from(to_moon)` ⇒ 食甚处算出 3.1353 rad（≈179.6°）
      而不是 0.0063 rad：食分算出来是巨大的负数、接触时刻的判据量恒为正 ⇒
      **一个根都找不到**（表现为「接触时刻字段全空」）。故此处显式取补角。
      eclipselib 内部取的是 `angle_between(earth_to_sun, moon_to_earth)`，
      而 `moon_to_earth = −(earth_to_moon)`，所以它天然就是补角。

    ★ 与 eclipselib 的另一处差别：本函数用 `.apparent()`（含光行时迭代），
      它只对方向施周年光行差。实测两者 sep 之差 **1.07e-5 弧度（≈2.2″）**
      —— 正是月球在 1.3 秒光行时里走过的角度量级（0.55″/s × 1.3 s ≈ 0.7″，
      方向差再乘上几何因子）。故**不是**可以忽略的小量，但换算到时刻上
      只有 1—2 秒（见 --verify 第 4 列：恒定 −70 s）。
    ★ 本模块**全用本函数的几何**算食分、食甚与接触时刻，eclipselib 只当
      **定位器**（找出有哪些食）—— 这样同一行里不会出现两套几何的接缝。
      ⚠ 初稿曾把这里写成「与 eclipselib 差 < 1e-6 弧度」，是**未实测的断言**；
        实测 1.07e-5，已改。声明精度前先量。
    """
    from skyfield.constants import ERAD
    earth = eph['earth']
    sun = eph['sun']
    moon = eph['moon']
    to_sun = earth.at(t).observe(sun).apparent()
    to_moon = earth.at(t).observe(moon).apparent()
    d_sun_km = to_sun.distance().km
    d_moon_km = to_moon.distance().km
    sep = math.pi - to_sun.separation_from(to_moon).radians      # ← 补角，见上文
    pi_m = (ERAD / 1e3) / d_moon_km
    pi_s = (ERAD / 1e3) / d_sun_km
    s_s = _R_SUN_KM / d_sun_km
    pi_1 = 1.01 * pi_m
    return {
        "sep": float(sep),
        "r_moon": float(math.asin(_R_MOON_KM / d_moon_km)),
        "r_pen": float(pi_1 + pi_s + s_s),
        "r_um": float(pi_1 + pi_s - s_s),
        "moon_distance_km": float(d_moon_km),
    }


def refine_greatest(eph, jd_guess, half_window=0.3):
    """在 `jd_guess` ± `half_window` 天内精化**食甚**（月心到影轴角距取极小）。

    ★ 为什么不能直接用 eclipselib 给的时刻：两者其实都对（都落在 NASA 目录
      ±2 s 内），但**分属两套几何**。本模块既然用 `lunar_shadow_geometry` 算
      食分与接触时刻，食甚就应当同源，否则同一行里会出现 2 秒级的内部接缝。
    ★ 为什么用「导数过零 + 二分」而不取「序列最小值」：极小点附近函数极平
      （sep 的二阶系数约 6e-3 rad/hr²），序列抖动能轻易造出假极小 ——
      与 `lunar_data.py` 2026-09-19 那次同族。
    """
    h = 0.01

    def deriv(jd):
        return (lunar_shadow_geometry(eph, cs.timescale().tt_jd(jd + h))["sep"]
                - lunar_shadow_geometry(eph, cs.timescale().tt_jd(jd - h))["sep"]) / (2 * h)

    a, b = jd_guess - half_window, jd_guess + half_window
    fa = deriv(a)
    for _ in range(90):
        m = (a + b) / 2.0
        fm = deriv(m)
        if (fa > 0) == (fm > 0):
            a, fa = m, fm
        else:
            b = m
        if abs(b - a) * 86400.0 < 0.05:
            break
    return (a + b) / 2.0


def _shadow_contacts(eph, jd_greatest, kind):
    """求月食各接触时刻（TT 儒略日）。返回 dict，缺项为 None。

    接触判据（sep 与半径比较，全部为角度）：
      半影食始/终  sep = r_pen + r_moon
      初亏/复圆    sep = r_um  + r_moon
      食既/生光    sep = r_um  − r_moon      （仅全食有）
    求法：从食甚向两侧按固定步长外推找变号区间，再二分。步长 0.05 天（≈72 分钟）
    —— 各阶段半时长实测 0.49—2.86 小时，故步长内至多一个根。
    """
    forward_map = {"p4": True, "u4": True, "u3": True,
                   "p1": False, "u1": False, "u2": False}
    spec = [("p1", "r_pen", +1), ("u1", "r_um", +1)]
    if kind == "total":
        spec += [("u2", "r_um", -1), ("u3", "r_um", -1)]
    spec += [("u4", "r_um", +1), ("p4", "r_pen", +1)]

    out = {}
    for name, rkey, sign in spec:
        forward = forward_map[name]

        def g(jd, rkey=rkey, sign=sign, forward=forward):
            gg = lunar_shadow_geometry(eph, cs.timescale().tt_jd(jd))
            v = gg["sep"] - (gg[rkey] + sign * gg["r_moon"])
            return v if forward else -v

        step = 0.05
        found = None
        for k in range(1, 60):
            jd_a = jd_greatest + (step * (k - 1) if forward else -step * (k - 1))
            jd_b = jd_greatest + (step * k if forward else -step * k)
            ga, gb = g(jd_a), g(jd_b)
            if (ga > 0) != (gb > 0):
                found = _bisect_sign(g, min(jd_a, jd_b), max(jd_a, jd_b), tol_s=20.0)[0]
                break
        out[name] = found
    return out


# =============================================================================
# 生成器一：行星与太阳（合 / 冲 / 上合 / 下合）
# =============================================================================
def gen_sun_planet(eph, y0, y1):
    out = []
    n = _np()
    ts = cs.timescale()
    jd0 = ts.utc(y0, 1, 1).tt - 40.0
    jd1 = ts.utc(y1 + 1, 1, 1).tt + 40.0
    for p in cs.PLANETS:
        cn = cs.PLANETS_CN[p]
        roots = _root_of_angle_diff(
            lambda jds, p=p: cs.sun_body_lon_sep_deg(eph, p, cs.timescale().tt_jd(jds)),
            jd0, jd1, step=0.25)
        for jd in roots:
            t = cs.timescale().tt_jd(jd)
            sep = float(cs.sun_body_lon_sep_deg(eph, p, t))
            import numpy as _n2
            cs_ = float(_n2.cos(_n2.radians(sep)))
            insp = _apparent_row(eph, p, t)
            if cs_ < 0:
                kind = "opposition"
                zh = "冲日"
                summ = ("%s与太阳黄经相差 180°，日落时东升、午夜中天、日出时西落，"
                        "整夜可见。地心距 %.3f AU，视星等约 %s 等。" %
                        (cn, insp["distance_au"], _mag_str(insp["mag"])))
                guide = ("冲日前后数周为全年最佳观测期。日落后即从东方升起，"
                         "午夜前后升至最高，肉眼即可见。")
            elif p in ("mercury", "venus"):
                if insp["distance_au"] < insp["earth_sun_distance_au"]:
                    kind, zh = "inferior_conjunction", "下合"
                    summ = ("%s行至太阳与地球之间，黄经与太阳相同。地心距 %.3f AU，"
                            "为一轮会合周期中距地最近之时；此时呈细弯月相（需望远镜）。" %
                            (cn, insp["distance_au"]))
                    guide = ("下合期间与太阳同升同落，淹没于日光中，不可观测。"
                             "此后约一至两周内为观测其最细月相的时刻。")
                else:
                    kind, zh = "superior_conjunction", "上合"
                    summ = ("%s行至太阳背后，黄经与太阳相同。日心距 %.3f AU，"
                            "地心距 %.3f AU，为一轮会合周期中距地最远之时。" %
                            (cn, insp["helio_distance_au"], insp["distance_au"]))
                    guide = "上合期间与太阳同升同落，淹没于日光中，不可观测。"
            else:
                kind, zh = "conjunction", "合日"
                summ = ("%s与太阳黄经相同，位于太阳背后。地心距 %.3f AU，"
                        "淹没于日光中。" % (cn, insp["distance_au"]))
                guide = "合日前后与太阳同升同落，淹没于日光中，不可观测。"
            out.append(_raw("planet", "%s-%s" % (_ascii(p), kind), t, zh,
                            "%s%s" % (cn, zh), summ, guide,
                            {"planet": p, "planet_cn": cn, "kind": kind,
                             "lon_sep_deg": round(sep, 4),
                             "distance_au": round(insp["distance_au"], 6),
                             "helio_distance_au": round(insp["helio_distance_au"], 6),
                             "earth_sun_distance_au": round(insp["earth_sun_distance_au"], 6),
                             "apparent_magnitude": _mag_str(insp["mag"]),
                             "criterion": "sin(黄经差) 过零，cos<0 判冲、cos>0 判合；"
                                          "内行星再以「地心距 < 地日距」分下合/上合"},
                            "ephemeris_de421"))
    return out


# =============================================================================
# 生成器二：行星「留」（入逆 / 复顺）
# =============================================================================
def gen_planet_stations(eph, y0, y1):
    out = []
    n = _np()
    ts = cs.timescale()
    jd0 = ts.utc(y0, 1, 1).tt - 40.0
    jd1 = ts.utc(y1 + 1, 1, 1).tt + 40.0
    step = 0.5
    for p in cs.PLANETS:
        cn = cs.PLANETS_CN[p]

        def lon_at(jds, p=p):
            return cs.body_ecl_lonlat(eph, p, cs.timescale().tt_jd(jds))[0]

        jds = n.arange(jd0, jd1, step)
        lon = n.asarray(lon_at(jds), dtype=float)
        # 解缠（去 0/360 跳变），保证差分是真角位移
        d = n.diff(lon)
        d = (d + 180.0) % 360.0 - 180.0
        unwrapped = n.concatenate([[lon[0]], lon[0] + n.cumsum(d)])
        rate = n.gradient(unwrapped, step)      # 度/天

        def rate_at(jd):
            h = 0.5
            lo, hi = lon_at(jd - h), lon_at(jd + h)
            dd = (float(hi) - float(lo) + 180.0) % 360.0 - 180.0
            return dd / (2.0 * h)

        for i in _scan_sign_changes(jds, rate):
            jd = _bisect_sign(rate_at, jds[i], jds[i + 1], tol_s=20.0)[0]
            t = cs.timescale().tt_jd(jd)
            # 由正转负 ⇒ 进入逆行；由负转正 ⇒ 恢复顺行
            going_retro = bool(float(rate_at(jd - 1.0)) > 0)
            insp = _apparent_row(eph, p, t)
            if going_retro:
                kind, zh = "station_retrograde", "留（转逆行）"
                summ = ("%s地心视黄经日变率由正转负，此刻为**留**，此后转入逆行。"
                        "地心距 %.3f AU，视星等约 %s 等。" %
                        (cn, insp["distance_au"], _mag_str(insp["mag"])))
                guide = ("「留」前后数日行星在天球上的位置几乎不动，随后开始倒退。"
                         "肉眼不可辨（日位移仅角分量级），需连续数夜照相比对。")
            else:
                kind, zh = "station_direct", "留（转顺行）"
                summ = ("%s地心视黄经日变率由负转正，此刻为**留**，逆行结束、恢复顺行。"
                        "地心距 %.3f AU，视星等约 %s 等。" %
                        (cn, insp["distance_au"], _mag_str(insp["mag"])))
                guide = ("留后行星恢复自西向东的顺行。肉眼不可辨，需连续数夜照相比对。")
            out.append(_raw("planet", "%s-%s" % (_ascii(p), kind), t, zh,
                            "%s%s" % (cn, zh), summ, guide,
                            {"planet": p, "planet_cn": cn, "kind": kind,
                             "lon_deg": round(float(cs.body_ecl_lonlat(eph, p, t)[0]), 4),
                             "lon_rate_deg_per_day_at_station": round(rate_at(jd), 6),
                             "distance_au": round(insp["distance_au"], 6),
                             "apparent_magnitude": _mag_str(insp["mag"]),
                             "criterion": "地心视黄经日变率过零（粗扫符号翻转 + 二分导数）；"
                                          "日变率由正转负＝入逆，由负转正＝复顺"},
                            "ephemeris_de421"))
    return out


# =============================================================================
# 生成器三：内行星大距（东 / 西）
# =============================================================================
def gen_planet_elongations(eph, y0, y1):
    """内行星大距（东/西）。

    ★★ 这里踩过一个坑，必须写下来（2026-09-23 实测）：
      「距角序列的极值点」**不全是**大距 —— 它一轮会合周期里有两个极值：
        · **极大**（rate 由正转负）＝ 大距 ← **只要这个**；
        · **极小**（rate 由负转正）＝ **合**，此刻 sep ≈ 0（水星实测 0.18°—4.9°）。
      初版把两者都收，于是水星一年报出 12 次「大距」（真值 6 次），
      且其中一半的时刻 sep 只有 0.2°—5° —— 一眼就是假的。
      教训的形状与 `lunar_data.py` 那次相反：那次是**假极值**（平处抖动），
      这次是**真极值但不是要的那个**。「导数过零」只说明是驻点，
      **驻点的种类要另外判**，不能把「找到驻点」当成「找到目标事件」。
    """
    out = []
    n = _np()
    ts = cs.timescale()
    jd0 = ts.utc(y0, 1, 1).tt - 40.0
    jd1 = ts.utc(y1 + 1, 1, 1).tt + 40.0
    step = 0.5
    for p in ("mercury", "venus"):
        cn = cs.PLANETS_CN[p]

        def sep_at(jds, p=p):
            return cs.body_pair_separation_deg(eph, p, 'sun', cs.timescale().tt_jd(jds))

        jds = n.arange(jd0, jd1, step)
        sep = n.asarray(sep_at(jds), dtype=float)
        rate = n.gradient(sep, step)

        def rate_at(jd):
            h = 0.5
            return (float(sep_at(jd + h)) - float(sep_at(jd - h))) / (2.0 * h)

        for i in _scan_sign_changes(jds, rate):
            # 只取**极大**：rate 由正转负
            if not (rate[i] > 0 >= rate[i + 1]):
                continue
            jd = _bisect_sign(rate_at, jds[i], jds[i + 1], tol_s=20.0)[0]
            t = cs.timescale().tt_jd(jd)
            max_sep = float(sep_at(jd))
            lon_sep = float(cs.sun_body_lon_sep_deg(eph, p, t))
            east = lon_sep > 0
            kind = "greatest_elongation_east" if east else "greatest_elongation_west"
            zh = "东大距" if east else "西大距"
            insp = _apparent_row(eph, p, t)
            summ = ("%s与太阳的**地心视角距**达本轮极大 %.2f°（%s）。%s"
                    "此时行星黄经%s太阳，%s。" %
                    (cn, max_sep, zh,
                     "东大距指行星位于太阳以东，" if east else "西大距指行星位于太阳以西，",
                     "大于" if east else "小于",
                     "日落后现身西方低空，为本轮最佳的昏见观测时机"
                     if east else "日出前现身东方低空，为本轮最佳的晨见观测时机"))
            guide = ("大距前后各一周为最佳观测窗口。%s视星等约 %s 等，"
                     "在暮色/晨光中需选地平开阔、无遮挡处。" %
                     ("日落后向西方低空寻找。" if east else "日出前向东方低空寻找。",
                      _mag_str(insp["mag"])))
            out.append(_raw("planet", "%s-%s" % (_ascii(p), kind), t, zh,
                            "%s%s" % (cn, zh), summ, guide,
                            {"planet": p, "planet_cn": cn, "kind": kind,
                             "elongation_deg": round(max_sep, 4),
                             "lon_sep_deg": round(lon_sep, 4),
                             "east_of_sun": bool(east),
                             "distance_au": round(insp["distance_au"], 6),
                             "apparent_magnitude": _mag_str(insp["mag"]),
                             "criterion": "**真角距**（非黄经差）的**极大**：粗扫真角距序列的"
                                          "导数符号翻转 + 二分；且**只取 rate 由正转负的极大**"
                                          "（由负转正的极小是「合」，sep≈0，不是大距）"},
                            "ephemeris_de421"))
    return out


# =============================================================================
# 生成器四：行星互合
# =============================================================================
_PAIR_ASCII = {
    "mercury": "mercury", "venus": "venus", "mars": "mars",
    "jupiter": "jupiter", "saturn": "saturn",
}


def gen_planet_pairs(eph, y0, y1):
    out = []
    n = _np()
    ts = cs.timescale()
    jd0 = ts.utc(y0, 1, 1).tt - 40.0
    jd1 = ts.utc(y1 + 1, 1, 1).tt + 40.0
    plist = list(cs.PLANETS)
    for ia in range(len(plist)):
        for ib in range(ia + 1, len(plist)):
            a, b = plist[ia], plist[ib]
            ca, cb = cs.PLANETS_CN[a], cs.PLANETS_CN[b]
            roots = _root_of_angle_diff(
                lambda jds, a=a, b=b: (
                    n.asarray(cs.body_ecl_lonlat(eph, a, cs.timescale().tt_jd(jds))[0])
                    - n.asarray(cs.body_ecl_lonlat(eph, b, cs.timescale().tt_jd(jds))[0])
                    + 180.0) % 360.0 - 180.0,
                jd0, jd1, step=0.25)
            for jd in roots:
                t = cs.timescale().tt_jd(jd)
                dsep = float(cs.body_pair_separation_deg(eph, a, b, t))
                if dsep > PAIR_CONJ_MAX_SEP_DEG:
                    continue          # 只「同经度」而实际相隔很远 —— 不收
                insp_a = _apparent_row(eph, a, t)
                insp_b = _apparent_row(eph, b, t)
                zh = "%s合%s" % (ca, cb)
                summ = ("%s与%s地心视黄经相同，天球上角距 %.2f°，为一次行星相合。"
                        "两者视星等分别约 %s 等、%s 等。" %
                        (ca, cb, dsep, _mag_str(insp_a["mag"]), _mag_str(insp_b["mag"])))
                guide = ("肉眼可见的双星伴月式景观：两行星同处一小片天区，"
                         "角距 %.2f°（约 %d 个满月视直径），双筒镜可同框。"
                         "具体观测时段取决于当日太阳位置，越远离太阳越易见。" %
                         (dsep, int(round(dsep / 0.5))))
                out.append(_raw("planet",
                                "%s-%s-conjunction" % (_ascii(a), _ascii(b)), t, zh,
                                zh, summ, guide,
                                {"planet_a": a, "planet_a_cn": ca,
                                 "planet_b": b, "planet_b_cn": cb, "kind": "planet_conjunction",
                                 "separation_deg": round(dsep, 4),
                                 "magnitude_a": _mag_str(insp_a["mag"]),
                                 "magnitude_b": _mag_str(insp_b["mag"]),
                                 "pair_sep_threshold_deg": PAIR_CONJ_MAX_SEP_DEG,
                                 "criterion": "两行星黄经差（sin 包裹）过零；"
                                              "再以**真角距 ≤ %.0f°** 过滤 —— "
                                              "黄经相同不等于看上去近" %
                                              PAIR_CONJ_MAX_SEP_DEG},
                                "ephemeris_de421"))
    return out


# =============================================================================
# 生成器五：月食（自算）
# =============================================================================
def gen_lunar_eclipses(eph, y0, y1):
    """月食：eclipselib 只当**定位器**，食甚／食分／接触时刻全用本模块的几何算。"""
    from skyfield import eclipselib
    out = []
    ts = cs.timescale()
    times, kinds, _details = eclipselib.lunar_eclipses(
        ts.utc(y0, 1, 1), ts.utc(y1 + 1, 1, 1), eph)
    for t0, k in zip(times, kinds):
        jd = refine_greatest(eph, t0.tt)
        t = cs.timescale().tt_jd(jd)
        g = lunar_shadow_geometry(eph, t)
        sep, r_moon, r_um, r_pen = g["sep"], g["r_moon"], g["r_um"], g["r_pen"]
        twice = 2.0 * r_moon
        # 与 eclipselib 同式：食分 = （影半径 + 月半径 − 月心距轴）/ 月直径
        umag = (r_um + r_moon - sep) / twice
        pmag = (r_pen + r_moon - sep) / twice
        if sep < r_um - r_moon:
            kind = "total"
        elif sep < r_um + r_moon:
            kind = "partial"
        else:
            kind = "penumbral"
        contacts = _shadow_contacts(eph, jd, kind)
        d_moon_km = g["moon_distance_km"]
        grem = (t.utc_datetime() + dt.timedelta(hours=TZ_HOURS))
        # ★ 日期取**北京时间**日期：2028-12-31 那次全食，北京时已跨到 2029-01-01，
        #   若按 UT 日命名会与读者看到的日期差一天。
        bj_date = grem.strftime("%Y%m%d")
        zh = KIND_CN[kind]
        dur_um = None
        if contacts.get("u1") and contacts.get("u4"):
            dur_um = (contacts["u4"] - contacts["u1"]) * 24.0
        tot = None
        if kind == "total" and contacts.get("u2") and contacts.get("u3"):
            tot = (contacts["u3"] - contacts["u2"]) * 24.0
        vis_txt = _lunar_visibility_txt(grem)
        if kind == "penumbral":
            summ = ("月球只进入地球**半影**，月面整体轻微变暗，肉眼多难察觉。"
                    "食甚时半影食分 %.3f，月心距影轴 %.5f 弧度。" % (pmag, sep))
            guide = ("半影月食亮度变化极小，肉眼基本看不出差别；"
                     "可在食甚前后用固定曝光的相机连拍比对月面亮度。")
        elif kind == "partial":
            summ = ("月球部分进入地球**本影**，本影食分 %.3f，即月面直径约 %.0f%% "
                    "没入本影。本影食阶段历时约 %s，地心月距 %.0f km。"
                    % (umag, umag * 100.0, _dur_txt(dur_um), d_moon_km))
            guide = ("肉眼可直接观看，无需任何防护。进入本影的一侧明显变暗、泛出暗红。"
                     "双筒镜或长焦相机可清晰记录本影边界移动。")
        else:
            summ = ("月球全部进入地球**本影**，本影食分 %.3f，全食阶段持续约 %s"
                    "（本影食全程约 %s）。地心月距 %.0f km。全食时月面呈暗红色"
                    "（即所谓「红月」），成因是阳光经地球大气折射与散射后投到月面。"
                    % (umag, _dur_txt(tot), _dur_txt(dur_um), d_moon_km))
            guide = ("肉眼可直接观看，无需任何防护。全食前后可观月面明暗与色调变化；"
                     "双筒镜可辨月面细节。")
        ev = _raw("lunar_eclipse", kind, t, zh,
                  "%s（%s）" % (zh, grem.strftime("%Y-%m-%d")), summ, guide,
                  {"eclipse_kind": kind,
                   "eclipse_kind_cn": zh,
                   "umbral_magnitude": round(umag, 4),
                   "penumbral_magnitude": round(pmag, 4),
                   "moon_shadow_axis_sep_rad": round(sep, 8),
                   "moon_distance_km": round(d_moon_km, 1),
                   "greatest_eclipse_bj": grem.strftime("%Y-%m-%d %H:%M:%S"),
                   "contacts_bj": {k: (_jd_bj_str(v) if v else None)
                                   for k, v in sorted(contacts.items())},
                   "duration_umbral_phase_hr": (round(dur_um, 4) if dur_um else None),
                   "duration_totality_hr": (round(tot, 4) if tot else None),
                   "global_visibility": vis_txt,
                   "criterion": "eclipselib.lunar_eclipses 定位（找出有哪些食）；"
                                "食甚由本模块对「月心到影轴角距」的导数过零二分精化；"
                                "月食类型与食分由该角距同本影/半影半径比较得出；"
                                "接触时刻（半影食始/初亏/食既/生光/复圆/半影食终）"
                                "由同一几何二分求得 —— 全行**同一套几何**，无内部接缝",
                   "source_ref": LUNAR_SOURCE_REF},
                  "ephemeris_de421")
        ev["slug_base"] = "lunar-eclipse-%s-%s" % (kind, bj_date)
        out.append(ev)
    return out


def _dur_txt(days):
    if not days:
        return "—"
    mins = days * 24.0 * 60.0
    h, m = int(mins // 60), int(round(mins % 60))
    if m == 60:
        h, m = h + 1, 0
    return ("%d 小时 %d 分" % (h, m)) if h else ("%d 分" % m)


def _lunar_visibility_txt(grem_bj):
    """粗略可见区域（仅按**食甚时刻**的北京时小时数给出半球倾向）。

    ★ 严格判定需按观测地算月球高度角，本函数**不**做那一步，故只给倾向性描述，
      并在文本里明说「按观测地另算」。不得据此宣称「中国可见」。
    """
    h = grem_bj.hour
    if 0 <= h < 6:
        return "食甚落在北京时凌晨，中国可见（月球位于西方低空至地平线，越往食甚后越接近月落）"
    if 6 <= h < 18:
        return "食甚落在北京时白昼，中国境内不可见（月球在地平线下）；见食区域见国际预报"
    return "食甚落在北京时晚间，中国可见（月球位于东方低空，食甚前刚升起）"


# =============================================================================
# 生成器六：流星雨极大（由照录的 λ☉ 求根）
# =============================================================================
def gen_meteor_peaks(eph, y0, y1):
    """流星雨极大：求「太阳**J2000 黄经**达该群约定 λ☉」的时刻。

    ★★ 历元必须用 **J2000**，不能用当日真黄道（本轮实测 2026-09-23 踩到）：
      IMO／RASC 的流星雨表头明写 **λ 2000**（J2000.0 黄道）。初版用
      `epoch="date"` 求根，对拍发现系统性偏差 —— 2026 年两者相差 **0.363°**，
      折合太阳平运动 **约 8.8 小时**，足以把极大日整体挪过午夜。
      ⇒ 外部口径的表，就用外部口径的历元去比对，不能「统一用 date」了事。
      （这与模块顶部那条「黄经差里 epoch 无所谓」并不矛盾：那里会相减抵消，
        这里是**绝对黄经**，抵消不了。）

    ★ 求根同样走 `sin` 包裹 —— 黄经差在 ±180° 处跳变，直接对角度二分会
      收敛到跳变点而不是零点（与「合/冲」同一坑）。
    """
    out = []
    n = _np()
    ts = cs.timescale()
    for sh in METEOR_SHOWERS:
        for y in range(y0, y1 + 1):
            target = sh["lam"]

            def diff(jd, target=target):
                lon = float(cs.body_ecl_lonlat(eph, 'sun', cs.timescale().tt_jd(jd),
                                               epoch="j2000")[0])
                return (lon - target + 180.0) % 360.0 - 180.0

            # 粗定位：以年内「λ☉ 达 target」的估计日为中心，开一个 ±25 天的窗口，
            # 按 0.5 天粗扫找到唯一一个变号区间，再二分。**不**靠月份边界兜。
            approx_doy = int(round(((target - 280.0) % 360.0) / 0.98564736)) % 365
            base = dt.date(y, 1, 1) + dt.timedelta(days=approx_doy)
            jd_c = ts.utc(base.year, base.month, base.day, 12).tt
            jds = n.arange(jd_c - 25.0, jd_c + 25.0, 0.5)
            svals = n.sin(n.radians(n.asarray([diff(j) for j in jds], dtype=float)))
            idx = _scan_sign_changes(jds, svals)
            if not idx:
                raise RuntimeError(
                    "流星雨 %s %d 年：在 %s±25 天内找不到 λ☉=%.2f° 的过零点 —— "
                    "不得静默跳过（这会无声地少一条事件）"
                    % (sh["code"], y, base.isoformat(), target))
            i = min(idx, key=lambda k: abs(jds[k] - jd_c))
            jd, _ = _bisect_sign(
                lambda j: math.sin(math.radians(diff(j))), jds[i], jds[i + 1],
                tol_s=20.0)
            t = cs.timescale().tt_jd(jd)
            bj = _jd_bj_str(jd)
            zh = sh["cn"]
            params = {
                "shower_code": sh["code"],
                "shower_cn": zh,
                "lambda_sun_deg": sh["lam"],
                "lambda_epoch": "J2000.0",
                "zhr_reference": sh["zhr"],
                "radiant": sh["radiant"],
                "geocentric_speed_kms": sh["speed_kms"],
                "actual_sun_ecl_lon_j2000_deg": round(
                    float(cs.body_ecl_lonlat(eph, 'sun', t, epoch="j2000")[0]), 5),
                "criterion": "极大时刻＝太阳**J2000 视黄经**达该群约定 λ☉ 之时"
                             "（λ☉ 表头为 J2000，故必须用 J2000 历元比对）。"
                             "λ☉ 照录 IMO/RASC，非本库自算（详见 source_ref）",
                "source_ref": METEOR_SOURCE_REF,
            }
            if sh.get("note"):
                params["lambda_source_conflict"] = sh["note"]
            out.append(_raw("meteor", sh["code"].lower(), t, zh,
                            "%s极大（%s）" % (zh, bj[:10]),
                            ("地球穿过%s流星体带的密集区，理论极大出现在太阳 J2000 视黄经 "
                             "%.2f° 之时。该群天顶每时出现率（ZHR）参考值约 %d，"
                             "流星速度约 %d km/s，辐射点在%s。" %
                             (zh, sh["lam"], sh["zhr"], sh["speed_kms"], sh["radiant"])),
                            ("极大时刻为**理论值**：实际峰值时刻与强度逐年不同，"
                             "受辐射点高度、月光、天气影响很大。"
                             "前半夜至黎明前辐射点升高后观测条件较好。"),
                            params, "ephemeris_de421"))
    return out


# =============================================================================
# 生成器七：日食（照录 NASA 目录 + 自算朔时刻做一致性检查）
# =============================================================================
def gen_solar_eclipses_catalog(eph, y0, y1, allow_unverified=False):
    out = []
    ts = cs.timescale()
    from skyfield import almanac
    for ent in SOLAR_ECLIPSE_CATALOG:
        y = int(ent["date_ut"][:4])
        if not (y0 <= y <= y1):
            continue
        bj = _td_to_bj(ent["date_ut"], ent["td"])
        bj_date = bj[:10]
        jd_tt = _tt_jd_from_td(ent["date_ut"], ent["td"])
        # 自算「最近的朔」并与目录食甚比对（一致性检查，不是自算日食）
        # ★ 窗口取 ±3 天。日食必在朔，食甚与朔的时差上限不超过约 2 小时，
        #   故 3 天是极宽的界。
        # ★★ 这里曾经有个**真空洞**（2026-09-23 被负控制照出来）：窗口内找不到朔时
        #   原本走 `delta_h = None` → 直接放行。于是「目录日期写错到离朔两周」
        #   这种最该拦的错，恰恰**不触发**任何检查（因为窗口里根本没有朔可比）。
        #   且负控制当时还报了「未触发」，看上去像测试写错——两件事都被这一处造成。
        #   现改为：找不到朔本身就是错误，必须抛。
        t0 = ts.tt_jd(jd_tt - 3.0)
        t1 = ts.tt_jd(jd_tt + 3.0)
        tt, ph = almanac.find_discrete(t0, t1, almanac.moon_phases(eph))
        newmoons = [a.tt for a, b in zip(tt, ph) if int(b) == 0]
        if not newmoons:
            raise RuntimeError(
                "日食目录条目 %s 前后 ±3 天内找不到「朔」—— 日食必发生在朔，"
                "该条目的日期几乎肯定有误。不许静默放行。" % ent["date_ut"])
        nearest = min(newmoons, key=lambda j: abs(j - jd_tt))
        delta_h = (jd_tt - nearest) * 24.0
        if abs(delta_h) > 3.0 and not allow_unverified:
            raise RuntimeError(
                "日食目录条目 %s 与自算「朔」相差 %.2f 小时（> 3h）："
                "要么目录有误、要么本模块的朔判定有误 —— 不许静默放行。"
                % (ent["date_ut"], delta_h))
        kind = ent["kind"]
        zh = {"total": "日全食", "annular": "日环食",
              "partial": "日偏食", "hybrid": "全环食"}[kind]
        params = {
            "solar_eclipse_kind": kind,
            "solar_eclipse_kind_cn": zh,
            "saros_series": ent["saros"],
            "eclipse_magnitude": ent["mag"],
            "central_duration": ent["central"],
            "global_visibility": ent["region"],
            "catalog_date_ut": ent["date_ut"],
            "catalog_greatest_eclipse_TT": ent["date_ut"] + " " + ent["td"] + " TT",
            "greatest_eclipse_bj": bj,
            "date_scale_note": "条目标题／slug 的日期用**北京时间日期**（%s）；国际目录按 **UT 日期**"
                               "编号为 %s，两者可差一天。目录时刻是 **TD（=TT）**，"
                               "已按 ΔT＋闰秒折算为北京时间。" % (bj_date, ent["date_ut"]),
            "nearest_newmoon_offset_hr": (round(delta_h, 3) if delta_h is not None else None),
            "self_check": "食甚与自算「朔」的时差（小时）；日食必发生在朔，"
                          "本值应在 ±3 小时内 —— 它对不上即说明目录或本模块有问题",
            "criterion": "**照录** NASA GSFC 日食目录（本机 skyfield 无日食函数，"
                         "不自算）；朔时刻为本模块自算，用作一致性检查",
            "source_ref": SOLAR_SOURCE_REF,
        }
        out.append(_raw("solar_eclipse", kind, ts.tt_jd(jd_tt), zh,
                        "%s（%s）" % (zh, bj_date),
                        ("%s。沙罗周期第 %d 号，食分 %.3f%s。可见区域：%s。"
                         % (zh, ent["saros"], ent["mag"],
                            ("，中心食持续 %s" % ent["central"]) if ent["central"] else "",
                            ent["region"])),
                        ("日食**必须**使用专业滤光片（巴德膜或专用日食镜）观看，"
                         "严禁肉眼直视或用普通墨镜、X 光片代替。"
                         "本地见食情况（初亏/食甚/复圆时刻、最大食分）须按观测地另算，"
                         "本站给的是全球总体信息。"),
                        params, "catalog_nasa_gsfc"))
        out[-1]["slug_base"] = "solar-eclipse-%s-%s" % (kind, bj_date.replace("-", ""))
    return out


# =============================================================================
# 公共小工具
# =============================================================================
def _ascii(name):
    """行星英文名（用于 slug）：与星历目标名一致，便于反查。"""
    return _PAIR_ASCII.get(name, name)


def _mag_str(mag):
    return ("%.1f" % mag) if mag is not None else "—"


def _apparent_row(eph, body, t):
    """取行星的观测态（视距／日心距／地日距／视星等）。

    ★ 只调 compute_sky 的公开访问器 —— 事件模块不得自己算星等，也不得
      直接调私有 `_apparent`：那会在「升级后」静默换口径（见 compute_sky
      访问器段的说明）。
    """
    st = cs.body_view_state(eph, body, t)
    return {"distance_au": float(st["distance_au"]),
            "helio_distance_au": float(st["helio_distance_au"]),
            "earth_sun_distance_au": float(st["earth_sun_distance_au"]),
            "phase_angle_deg": float(st["phase_angle_deg"]),
            "mag": float(st["apparent_magnitude"]),
            "ecl_lat_deg": float(st["ecl_lat_deg"])}


def _raw(event_type, kind, t, kind_cn, title, summary, obs_guide, params, method):
    """构造一条**未定 slug** 的原始事件。"""
    return {
        "event_type": event_type,
        "kind": kind,
        "t": t,
        "title": title,
        "summary": summary,
        "obs_guide": obs_guide,
        "params": params,
        "method": method,
        "ephemeris": EPH_LABEL,
        "source_ref": (params.get("source_ref") or
                       (LUNAR_SOURCE_REF if event_type == "lunar_eclipse" else
                        SOLAR_SOURCE_REF if event_type == "solar_eclipse" else
                        "自算：星历 de421（见 params.criterion）")),
        "literature": None,
        "discussion": None,
        "time_uncertainty": None,
        "dt_model": None,
        "slug_base": None,     # 由 finalize 按类型填充
    }


# =============================================================================
# slug 与去重
# =============================================================================
_SLUG_SAFE = re.compile(r"[^a-z0-9\-]+")


def _slugify(text):
    s = str(text).strip().lower()
    s = s.replace("_", "-")
    s = _SLUG_SAFE.sub("-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s


def make_slug(ev, seq=0):
    """确定性 slug：`{event_type 的连字符形}-{主体}-{类型}-{YYYYMMDD}`，重复加 `-N`。

    ★ 为什么 slug 必须**确定性**：它是 `wp_astro_events.uk_slug` —— REST 导入按
      `slug` 查存在→更新，所以 slug 一变就会**新插一行**、旧行留成孤儿。
      重跑同一个区间必须逐字给出同一批 slug（`--selftest` 有幂等判据）。
    ★ 前缀硬绑 `event_type`（下划线换连字符）：这样「slug 前缀 == 类型」是可以
      机器验的不变量，前台上按类型分 Tab 与 URL 也自洽。
    """
    base = ev.get("slug_base")
    if not base:
        base = "%s-%s-%s" % (_slugify(ev["event_type"]),
                             _slugify(ev["kind"]), _bj_date(ev["t"].tt).strftime("%Y%m%d"))
    prefix = _slugify(ev["event_type"])
    if not base.startswith(prefix + "-"):
        base = prefix + "-" + base
    return base if seq <= 0 else "%s-%d" % (base, seq)


def dedup(events):
    """按 slug 去重。返回 (保留列表, 冲突列表)。

    ★ 同 slug 表示**同一事件被两条路径产出**（例如行星互合从 A|B 与 B|A 各出一次）。
      处理方式是**保留首条 + 报冲突**，绝不静默丢弃 —— 冲突本身就是「生成器有
      重叠」的信号，要能在 --selftest 里看见。
    """
    seen = {}
    kept = []
    conflicts = []
    for ev in events:
        base = make_slug(ev, 0)
        seq = seen.get(base, 0) + 1
        seen[base] = seq
        slug = base if seq == 1 else "%s-%d" % (base, seq)
        if seq > 1:
            conflicts.append((slug, base))
        ev2 = dict(ev)
        ev2["slug"] = slug
        kept.append(ev2)
    return kept, conflicts


# =============================================================================
# 装配成 REST 白名单行
# =============================================================================
# 与插件端 rest-import.php 的 kcj_astro_rest_columns('events') 一致。
EVENTS_WHITELIST = (
    "event_id", "event_type", "jd_core", "event_time_bj", "time_uncertainty",
    "dt_model", "post_id", "title", "slug", "summary", "params_json",
    "obs_guide", "obs_site", "literature", "discussion", "source_ref",
    "method", "ephemeris", "publish_status",
)
# 这些键**不发给服务端**：event_id 是自增主键（发过去会指定 PK）；
# post_id 由插件在写入后回填 CPT 时自己写。
NEVER_SEND = ("event_id", "post_id")

# 列宽裁剪（与 build_dataset.COL_MAXLEN 同源；超长会被 MySQL 拒行，见 F22）
# ★★ v2.2.6 续（2026-09-23）：单位是「**字节**」（线上列 latin1 ⇒ WP 的
#   strip_invalid_text() 一律按字节判长度，中文每字 3 字节）。
#   ★ 本表在此前**从未被 verify_package 对拍过** —— 它是对拍的「第三处来源」，
#     而当时的对拍只读 build_dataset／build_site 两处 ⇒ 这两行**静默漂移**到旧值：
#     `time_uncertainty: 64`、`ephemeris: 96`（另一处已改 191）。现对齐。
COL_MAXLEN = {
    "event_type": 32, "time_uncertainty": 191, "dt_model": 64, "title": 255,
    "slug": 191, "method": 32, "ephemeris": 191, "obs_site": 191,
    "source_ref": None,      # TEXT，不裁
    "summary": None, "obs_guide": None, "literature": None,
    "discussion": None, "params_json": None,
}


# ★ v2.2.6 续：裁剪日志。**裁剪永远不该发生** —— 它意味着列宽装不下真值，
#   属于静默数据失真（F22 就是这么丢掉 data_version 的；F27 是它的字节版）。
#   自测断言本表为空，把「列宽够不够」的判据放在**裁剪的上游**。
CLIP_LOG = []


def _utf8_len(s):
    """字符串的 **UTF-8 字节数**（列宽的真实口径）。"""
    return len(s.encode("utf-8"))


def _clip(s, key):
    """按列宽（**字节**）裁剪。★ v2.2.6 续：原用 `len(s)`／`s[:lim]`（字符），
    对中文等于把上限放大 3 倍 —— F27 的上游同族缺陷。"""
    if s is None:
        return None
    s = str(s)
    lim = COL_MAXLEN.get(key)
    if lim and _utf8_len(s) > lim:
        CLIP_LOG.append({"key": key, "bytes": _utf8_len(s), "chars": len(s),
                         "maxlen": lim, "head": s[:40]})
        b = s.encode("utf-8")
        return b[:lim].decode("utf-8", "ignore")
    return s


# ★ v1.1.0：明文净化。所有字符串都往 WP 端走 `esc_html()` 直出，**不经** Markdown 渲染，
#   故 `**粗体**` 只会以两个字面星号示人（模板里 v1.2.0 已修过同一类写法）。
#   在**出口**一次清掉，而不是逐个生成器去改 —— 生成器以后再加也自动受约束。
#   注：只去成对的 `**…**`；落单的 `*`（如「±3×10⁻⁶」之外的星号）不动，避免误伤。
_MD_EMPH = re.compile(r"\*\*(.+?)\*\*", re.S)


def _plain(s):
    """去掉 Markdown 强调标记；None 原样返回。"""
    if s is None:
        return None
    return _MD_EMPH.sub(r"\1", str(s))


def _plain_deep(obj):
    """递归净化（params 是嵌套 dict/list，逐层过 _plain）。"""
    if isinstance(obj, str):
        return _plain(obj)
    if isinstance(obj, dict):
        return {k: _plain_deep(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain_deep(v) for v in obj]
    return obj


def to_rows(events, publish_status=1):
    """原始事件 → wp_astro_events 白名单行（可直接喂 REST /import）。

    ★ v1.1.0：所有字符串字段（含 params 内层）经 `_plain()` 净化后才出口。
    """
    rows = []
    for ev in events:
        params = json.dumps(_plain_deep(ev["params"]), ensure_ascii=False, sort_keys=True)
        rows.append({
            "event_type": _clip(_plain(ev["event_type"]), "event_type"),
            "jd_core": round(float(ev["t"].tt), 6),
            "event_time_bj": _jd_bj_str(ev["t"].tt),
            "title": _clip(_plain(ev["title"]), "title"),
            "slug": _clip(_plain(ev["slug"]), "slug"),
            "summary": _clip(_plain(ev["summary"]), "summary"),
            "params_json": _clip(params, "params_json"),
            "obs_guide": _clip(_plain(ev["obs_guide"]), "obs_guide"),
            "literature": _clip(_plain(ev["literature"]), "literature"),
            "discussion": _clip(_plain(ev["discussion"]), "discussion"),
            "source_ref": _clip(_plain(ev["source_ref"]), "source_ref"),
            "method": _clip(_plain(ev["method"]), "method"),
            "ephemeris": _clip(_plain(ev["ephemeris"]), "ephemeris"),
            "time_uncertainty": _clip(_plain(ev["time_uncertainty"]), "time_uncertainty"),
            "dt_model": _clip(_plain(ev["dt_model"]), "dt_model"),
            "publish_status": int(publish_status),
        })
    return rows


# =============================================================================
# 总装
# =============================================================================
GENERATORS = ("planet_sun", "planet_station", "planet_elongation",
              "planet_pair", "lunar_eclipse", "meteor", "solar_eclipse")

_GEN_FN = {
    "planet_sun": None, "planet_station": None, "planet_elongation": None,
    "planet_pair": None, "lunar_eclipse": None, "meteor": None,
    "solar_eclipse": None,
}


def _gen_table():
    """生成器名 → 函数（延迟绑定，避免模块导入期就解析 lambda）。"""
    return {
        "planet_sun": gen_sun_planet,
        "planet_station": gen_planet_stations,
        "planet_elongation": gen_planet_elongations,
        "planet_pair": gen_planet_pairs,
        "lunar_eclipse": gen_lunar_eclipses,
        "meteor": gen_meteor_peaks,
        "solar_eclipse": gen_solar_eclipses_catalog,
    }


def build_events(y0, y1, eph=None, which=None, allow_unverified=False, verbose=True):
    """生成 [y0, y1] 区间的事件。返回 (事件列表, 统计 dict)。"""
    eph = eph or cs.load_ephemeris()
    which = list(which) if which else list(GENERATORS)
    unknown = [w for w in which if w not in GENERATORS]
    if unknown:
        raise ValueError("未知生成器：%s（可用：%s）" % (unknown, ",".join(GENERATORS)))
    table = _gen_table()
    raw = []
    counts = {}
    for name in which:
        before = len(raw)
        if name == "solar_eclipse":
            raw += table[name](eph, y0, y1, allow_unverified=allow_unverified)
        else:
            raw += table[name](eph, y0, y1)
        counts[name] = len(raw) - before

    raw.sort(key=lambda e: e["t"].tt)
    # ── 区间过滤：生成器一律向外留 40 天余量（免得年初/年末的事件因粗扫窗口
    #    从边界起算而漏收），故此处按**北京时间年份**收口。
    #    ★ 用北京年份而不是 TT 年份：交付给读者的是北京时间，跨年夜的月食
    #      在 TT 与北京时下可能差一天，四处（标题／slug／event_time_bj／分年）
    #      必须同一个口径。
    n_all = len(raw)
    raw = [e for e in raw if y0 <= _bj_date(e["t"].tt).year <= y1]
    dropped = n_all - len(raw)
    events, conflicts = dedup(raw)
    stat = {"counts": counts, "total": len(events), "slug_conflicts": conflicts,
            "by_type": {}, "boundary_dropped": dropped}
    for ev in events:
        stat["by_type"][ev["event_type"]] = stat["by_type"].get(ev["event_type"], 0) + 1
    if verbose:
        print("[event_almanac] 区间 %d—%d：共 %d 条（区间外边界事件已剔 %d 条）"
              % (y0, y1, len(events), dropped))
        for k in which:
            print("   %-18s %4d" % (k, counts.get(k, 0)))
        print("   按 event_type：" + "  ".join(
            "%s=%d" % (k, v) for k, v in sorted(stat["by_type"].items())))
        if conflicts:
            print("   ⚠ slug 冲突 %d 件（已加序号，但请核查生成器是否重叠）：" % len(conflicts))
            for slug, base in conflicts[:10]:
                print("      %s  ←  %s" % (slug, base))
    return events, stat


# =============================================================================
# 对拍（--verify）
# =============================================================================
# 参考值一律**照录官方年历**，不凭记忆写。本轮采用的三个权威源：
#   ① 香港天文台《2026 年行星觀測資料》（hko.gov.hk，官方 PDF）
#   ② 台北市立天文科學教育館《2026 年重要天象》（官方 PDF）
#   ③ NASA GSFC／Fred Espenak《Solar / Lunar Eclipses 2021—2030》
# ★ 本表曾写错过一个值（土星冲日记成 2026-09-22，实为 10-04）——
#   而那一次**自算值是对的、参考值是错的**。故 ``--verify`` 报红时，
#   先怀疑参考值，再怀疑自算值；两边都要有出处。
PLANET_REF_HKO_2026 = (
    # (planet, kind, 北京日期, 出处)
    ("mercury", "greatest_elongation_east", "2026-02-20", "①水星東大距"),
    ("mercury", "greatest_elongation_east", "2026-06-16", "①水星東大距"),
    ("mercury", "greatest_elongation_east", "2026-10-12", "①水星東大距"),
    ("mercury", "greatest_elongation_west", "2026-04-04", "①水星西大距"),
    ("mercury", "greatest_elongation_west", "2026-08-02", "①水星西大距"),
    ("mercury", "greatest_elongation_west", "2026-11-21", "①水星西大距"),
    ("venus", "greatest_elongation_east", "2026-08-15", "①金星東大距"),
    ("mars", "conjunction", "2026-01-09", "①火星合"),
    ("jupiter", "conjunction", "2026-07-29", "①木星合"),
    ("jupiter", "opposition", "2026-01-10", "①木星衝"),
    ("saturn", "conjunction", "2026-03-25", "①土星合"),
    ("saturn", "opposition", "2026-10-04", "①土星衝"),
)

# ②臺北天文館《2026 年重要天象》：3/3 月全食七個時刻（臺北時＝北京時＝UTC+8）
LUNAR_CONTACT_REF_2026_03_03 = (
    ("p1", "16:43", "半影食始"), ("u1", "17:50", "初虧"),
    ("u2", "19:04", "食既"), ("greatest", "19:34", "食甚"),
    ("u3", "20:03", "生光"), ("u4", "21:18", "復圓"),
    ("p4", "22:25", "半影食終"),
)


def _hhmmss_to_sec(s):
    """'HH:MM' 或 'HH:MM:SS' → 当日秒数。

    ★ 秒位必须处理：本轮实测踩到 —— 初版写成 `s.split(":")[:2]`，
      于是 '11:34:52' 被读成 11:34:00，**静默丢掉 52 秒**。后果不是报错，
      而是对拍残差从恒定的 −71 s 变成 −19…−67 s 的散乱值，
      看上去像「自算值不稳定」，实则**参考值被读错**。
    """
    parts = [int(x) for x in str(s).split(":")]
    while len(parts) < 3:
        parts.append(0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def verify(eph=None):
    """与权威年历对拍。返回 (总判据数, 通过数, 明细行列表)。"""
    eph = eph or cs.load_ephemeris()
    lines = []
    passed = total = 0

    def note(name, ok):
        nonlocal passed, total
        total += 1
        passed += int(bool(ok))
        return "" if ok else "  ✗"

    # ── 甲 · 月食：自算 vs NASA GSFC 目录 ──
    lines.append("甲 · 月食：自算（eclipselib）vs NASA GSFC《Lunar Eclipses 2021—2030》")
    lines.append("%-12s %-10s %-10s %-9s %-10s %-9s %s" %
                 ("日期(UT)", "NASA TD", "自算UT", "TD−UT", "类型", "食分差", "判"))
    got = gen_lunar_eclipses(eph, 2026, 2030)
    got_by_date = {}
    for ev in got:
        ts = cs.timescale()
        u = ts.tt_jd(ev["t"].tt).utc_datetime().replace(tzinfo=None)
        got_by_date[u.strftime("%Y-%m-%d")] = (ev, u)
    for date_ut, td, kind, umag, saros in LUNAR_REFERENCE:
        if date_ut not in got_by_date:
            lines.append("%-12s %-10s %-10s %-9s ✗ 未产出" % (date_ut, td, "—", "—"))
            note("", False)
            continue
        ev, u = got_by_date[date_ut]
        mine = u.strftime("%H:%M:%S")
        a, b, c = (int(x) for x in mine.split(":"))
        dsec = (a * 3600 + b * 60 + c) - _hhmmss_to_sec(td)
        dsec = (dsec + 43200) % 86400 - 43200          # 跨日归一
        kind_ok = ev["params"]["eclipse_kind"] == kind
        dmag = ev["params"]["umbral_magnitude"] - umag
        ok_time = abs(dsec + 69) <= 10                  # +69 s = TT−UTC，见模块 docstring
        bad = note("", ok_time) + note("", kind_ok) + note("", abs(dmag) <= 0.005)
        lines.append("%-12s %-10s %-10s %+7d s %-10s %+8.4f %s"
                     % (date_ut, td, mine, dsec, kind, dmag, bad or "✓"))
    lines.append("  注：NASA 表头为 **TD（=TT）**，非 UT；第 4 列即两者之差，"
                 "实测恒定在 −71±1 s（TT−UTC≈69.2 s），故时间以「dsec+69 ≤ ±10 s」判。")

    # ── 乙 · 流星雨：自算太阳 J2000 黄经 vs 照录 λ☉ ──
    lines.append("")
    lines.append("乙 · 流星雨：自算太阳 **J2000** 黄经 vs 照录 λ☉（判据 |Δ| ≤ 0.0005°）")
    mev = gen_meteor_peaks(eph, 2026, 2030)
    worst = 0.0
    for ev in mev:
        p = ev["params"]
        worst = max(worst, abs(p["actual_sun_ecl_lon_j2000_deg"] - p["lambda_sun_deg"]))
    lines.append("   共 %d 条，最大偏差 %.6f° →%s"
                 % (len(mev), worst, note("", worst <= 0.0005) or " ✓"))

    # ── 丙 · 日食：NASA 目录食甚 vs 自算「朔」 ──
    lines.append("")
    lines.append("丙 · 日食：NASA 目录食甚 vs 自算「朔」（日食必在朔，判据 |Δ| ≤ 3 h）")
    sev = gen_solar_eclipses_catalog(eph, 2026, 2030)
    worst_h = max(abs(e["params"]["nearest_newmoon_offset_hr"] or 0.0) for e in sev)
    lines.append("   共 %d 条，最大时差 %.3f h →%s"
                 % (len(sev), worst_h, note("", worst_h <= 3.0) or " ✓"))

    # ── 丁 · 行星事件 vs 香港天文台《2026 年行星觀測資料》 ──
    lines.append("")
    lines.append("丁 · 行星事件：自算 vs 香港天文台《2026 年行星觀測資料》（官方 PDF，判据 ±0 天）")
    pev = gen_sun_planet(eph, 2026, 2026) + gen_planet_elongations(eph, 2026, 2026)
    for planet, kind, ref_date, tag in PLANET_REF_HKO_2026:
        ref_d = dt.date(*[int(x) for x in ref_date.split("-")])
        mine = [_bj_date(e["t"].tt) for e in pev
                if e["params"].get("planet") == planet
                and e["params"].get("kind") == kind]
        hit = ref_d in mine
        near = min(((abs((m - ref_d).days), m) for m in mine), default=None)
        lines.append("   %-8s %-26s 参考 %s → 自算 %s%s"
                     % (planet, tag, ref_date,
                        ("有同日项" if hit else
                         ("最近 %s（差 %d 天）" % (near[1], near[0]) if near else "无")),
                        note("", hit)))
    lines.append("   出处：香港天文台《2026 年行星觀測資料》"
                 "（www.hko.gov.hk/tc/gts/astron2026/files/2026planetary.pdf）")

    # ── 戊 · 月食接触时刻 vs 台北天文館《2026 年重要天象》 ──
    lines.append("")
    lines.append("戊 · 2026-03-03 月全食各阶段：自算 vs 台北天文館（判据 ±2 分钟）")
    tot_ev = [e for e in gen_lunar_eclipses(eph, 2026, 2026)
              if e["params"]["eclipse_kind"] == "total"][0]
    c = tot_ev["params"]["contacts_bj"]
    for key, ref, zh in LUNAR_CONTACT_REF_2026_03_03:
        mine_s = (tot_ev["params"]["greatest_eclipse_bj"] if key == "greatest"
                  else c.get(key))
        if not mine_s:
            lines.append("   %-9s %s  ✗ 自算未产出" % (zh, ref))
            note("", False)
            continue
        my_sec = _hhmmss_to_sec(mine_s[11:19])
        d = my_sec - _hhmmss_to_sec(ref)
        lines.append("   %-9s 参考 %s → 自算 %s（差 %+d 秒）%s"
                     % (zh, ref, mine_s[11:19], d, note("", abs(d) <= 120)))
    lines.append("   出处：臺北市立天文科學教育館《2026 年重要天象》（官方 PDF）")
    return total, passed, lines


# =============================================================================
# 自检（--selftest）
# =============================================================================
def selftest(verbose=True):
    fails = []
    oks = []

    def chk(name, cond, detail=""):
        if cond:
            oks.append(name)
        else:
            fails.append("%s %s" % (name, detail))

    eph = cs.load_ephemeris()
    ev, stat = build_events(2026, 2028, eph=eph, verbose=False)

    # ── 1. 空集守卫：任何一类为 0 都必须出声 ──
    for k, v in stat["by_type"].items():
        chk("类型 %s 非空（%d）" % (k, v), v > 0)
    chk("七类生成器全部有产出", all(stat["counts"].get(k, 0) > 0 for k in GENERATORS),
        "counts=%s" % stat["counts"])

    # ── 2. slug 唯一 / 确定性 / 前缀绑定类型 ──
    slugs = [e["slug"] for e in ev]
    chk("slug 全局唯一", len(slugs) == len(set(slugs)),
        "重复 %d" % (len(slugs) - len(set(slugs))))
    chk("slug 前缀 == event_type（连字符形）",
        all(e["slug"].startswith(e["event_type"].replace("_", "-") + "-") for e in ev))
    chk("slug 长度 ≤ 191", all(len(s) <= 191 for s in slugs))
    ev26b, _ = build_events(2026, 2026, eph=eph, verbose=False)
    ev26c, _ = build_events(2026, 2026, eph=eph, verbose=False)
    chk("同一条命令重跑 slug 逐字相同（幂等 → UPSERT 不产生孤儿行）",
        [e["slug"] for e in ev26c] == [e["slug"] for e in ev26b])
    chk("同一条命令重跑 jd_core 逐字相同",
        [e["t"].tt for e in ev26c] == [e["t"].tt for e in ev26b])
    # ★ 跨区间一致（**带容差**，不是逐字比）——这一条专门交代一个边界：
    #   月食的定位依赖 eclipselib 的搜索区间，区间不同会让它有 ~1 秒级的抖动，
    #   故「同一事件在不同区间窗口下相差 ≤ 3 秒」才是可达的标准；
    #   要求逐字相同是把不可达的标准写成判据，只会造出永远红的灯。
    ev26a = [e for e in ev if _bj_date(e["t"].tt).year == 2026]
    same_slug = ([e["slug"] for e in ev26b] == [e["slug"] for e in ev26a])
    chk("跨区间（3 年窗口 vs 1 年窗口）slug 集合一致", same_slug,
        "%d vs %d" % (len(ev26b), len(ev26a)))
    if same_slug:
        worst = max(abs(a["t"].tt - b["t"].tt) * 86400.0
                    for a, b in zip(ev26b, ev26a))
        chk("跨区间同一事件时刻差 ≤ 3 秒（实得最大 %.2f 秒）" % worst, worst <= 3.0)

    # ── 3. 行装配：键齐备、不发 PK ──
    CLIP_LOG.clear()          # 模块级累积；自检前清空，避免上一次生成残留算到本次头上
    rows = to_rows(ev)
    chk("行键全在白名单内", all(set(r) <= set(EVENTS_WHITELIST) for r in rows))
    chk("不发 event_id / post_id", all(not (set(r) & set(NEVER_SEND)) for r in rows))
    chk("必填键无 None（event_type/jd_core/event_time_bj/title/slug/publish_status）",
        all(all(r[k] is not None for k in
                ("event_type", "jd_core", "event_time_bj", "title", "slug",
                 "publish_status")) for r in rows))
    chk("event_type 全部是 6 个规范值之一",
        all(r["event_type"] in ("solar_eclipse", "lunar_eclipse", "planet",
                                "meteor", "traditional", "historical") for r in rows))
    # ★ v2.2.6 续：按**字节**判（原先按字符 ⇒ 中文列等于没设防）
    chk("列宽未越界（按 UTF-8 字节）", all(
        (COL_MAXLEN.get(k) is None or r[k] is None or _utf8_len(str(r[k])) <= COL_MAXLEN[k])
        for r in rows for k in r))
    chk("★ 没有任何值被裁剪过（裁剪＝列宽装不下真值，属静默失真）",
        not CLIP_LOG, "裁剪 %d 处：%s" % (len(CLIP_LOG), CLIP_LOG[:3]))
    chk("params_json 可反序列化", all(
        isinstance(json.loads(r["params_json"]), dict) for r in rows))

    # ── 3b. 明文净化（v1.1.0）：显示字段不得留 Markdown 标记 ──
    #   WP 端一律 esc_html() 直出 ⇒ `**粗体**` 只会示人两个星号。
    #   判据一：真实产出里一个 `**` 都没有。
    dirty = sorted({k for r in rows for k, v in r.items()
                    if isinstance(v, str) and "**" in v})
    chk("产出各行无 Markdown 粗体标记（**）", not dirty, "仍有标记的字段：%s" % dirty)
    #   判据二（负控制）：净化函数本身必须真的会动手 —— 拿一条真的带标记的原始事件过一遍，
    #   若把 _plain 从 to_rows 里摘掉，本项必红（证明判据一不是恒真）。
    ts_t = cs.timescale().tt_jd(2461000.0)
    probe = _raw("planet", "probe", ts_t, "探针", "**粗体**标题", "**粗体**摘要",
                 "**粗体**指南", {"criterion": "**粗体**判据"}, "ephemeris_de421")
    probe["slug"] = "planet-probe-20260101"
    probe_row = to_rows([probe])[0]
    chk("负控制：净化前的字符串确实含标记（否则判据一恒真）",
        "**" in probe["title"] and "**" in probe["summary"])
    chk("负控制：过 to_rows 后标记被清除（含 params 内层）",
        "**" not in probe_row["title"] and "**" not in probe_row["summary"]
        and "**" not in probe_row["obs_guide"] and "**" not in probe_row["params_json"],
        "title=%r" % probe_row["title"])
    chk("正控制：净化只去标记、不改文字",
        probe_row["title"] == "粗体标题" and probe_row["summary"] == "粗体摘要"
        and json.loads(probe_row["params_json"])["criterion"] == "粗体判据")
    chk("净化不误伤落单星号（±3×10⁻⁶ 之类）", _plain("a*b") == "a*b")

    # ── 4. 不编造：方法名与来源必须自洽 ──
    for r in rows:
        m = r["method"]
        if r["event_type"] == "solar_eclipse":
            chk("日食 %s 标 catalog 方法" % r["slug"], m.startswith("catalog_"),
                "method=%s" % m)
        elif r["event_type"] in ("lunar_eclipse", "planet", "meteor"):
            chk("%s 标自算方法" % r["slug"], m == "ephemeris_de421", "method=%s" % m)
    chk("每行都有 source_ref", all(r["source_ref"] for r in rows))

    # ── 5. 求根引擎：三个已校准的哨兵值 ──
    ts = cs.timescale()
    # 5a 火星 2027-02-19 必须是「冲」不是「合」（planet_retro 的历史教训）
    mars = [e for e in ev if e["params"].get("planet") == "mars"
            and e["params"].get("kind") == "opposition"]
    d = [cs.timescale().tt_jd(e["t"].tt).utc_datetime().strftime("%Y-%m-%d") for e in mars]
    chk("火星 2027 年冲日落在 02-19 前后一天内",
        any(x in ("2027-02-18", "2027-02-19", "2027-02-20") for x in d), "得到 %s" % d)
    # 5b 地影几何与 eclipselib 同源（食甚处 sep 应一致到 1e-6 rad）
    from skyfield import eclipselib
    tt, kk, dd = eclipselib.lunar_eclipses(ts.utc(2026, 1, 1), ts.utc(2026, 4, 1), eph)
    mine = lunar_shadow_geometry(eph, tt[0])["sep"]
    chk("地影几何 sep 与 eclipselib 一致（|Δ| < 5e-5 rad ≈ 10″）",
        abs(mine - float(dd["closest_approach_radians"][0])) < 5e-5,
        "Δ=%.2e rad（实测约 1.1e-5，源自光行时迭代；见 lunar_shadow_geometry 说明）"
        % (mine - float(dd["closest_approach_radians"][0])))
    chk("负控制：sep 若取成补角外的那一侧（≈π），本条必红",
        mine < 0.05)
    # 5c 接触时刻必须包住食甚
    ev26 = gen_lunar_eclipses(eph, 2026, 2026)
    total_ = [e for e in ev26 if e["params"]["eclipse_kind"] == "total"][0]
    c = total_["params"]["contacts_bj"]
    chk("月全食接触时刻齐全且有次序（p1<u1<u2<食甚<u3<u4<p4）",
        all(c.get(x) for x in ("p1", "u1", "u2", "u3", "u4", "p4")) and
        c["p1"] < c["u1"] < c["u2"] < total_["params"]["greatest_eclipse_bj"]
        < c["u3"] < c["u4"] < c["p4"],
        "%s" % c)
    # 5d ★ `sep` 必须是**补角**口径：食甚处应趋于 0（而非 180°）。
    #    初版取的是「月心方向与太阳方向之夹角」，食甚处得到 3.1353 rad，
    #    后果是食分为巨大负数、接触时刻一个根都找不到 —— 锁死在这里。
    chk("食甚处 sep < 0.05 rad（补角口径正确；若取成 3.13 则本项必红）",
        max(e["params"]["moon_shadow_axis_sep_rad"] for e in ev
            if e["event_type"] == "lunar_eclipse") < 0.05,
        "max=%s" % max(e["params"]["moon_shadow_axis_sep_rad"] for e in ev
                       if e["event_type"] == "lunar_eclipse"))
    # 5e ★ 内行星大距每年恰 6 次（水星）——初版把 sep 的**极小**（＝合，sep≈0）
    #    也当成大距，一年报出 12 次、且半数时刻 sep 只有 0.2°—5°。
    for yr in (2026, 2027):
        n_m = len([e for e in ev if e["params"].get("planet") == "mercury"
                   and e["params"].get("kind", "").startswith("greatest_elongation")
                   and _bj_date(e["t"].tt).year == yr])
        chk("水星 %d 年大距恰 6 次（实得 %d）" % (yr, n_m), n_m == 6)
    chk("所有大距的距角 ≥ 17°（水星下界 18°、金星上界 47°）",
        all(e["params"]["elongation_deg"] >= 17.0 for e in ev
            if e["params"].get("kind", "").startswith("greatest_elongation")))

    # ── 6. 流星雨 λ☉ 命中 ──
    mev = gen_meteor_peaks(eph, 2026, 2026)
    chk("流星雨 %d 群全部命中 λ☉" % len(mev),
        all(abs(e["params"]["actual_sun_ecl_lon_j2000_deg"] - e["params"]["lambda_sun_deg"])
            <= 0.0005 for e in mev))
    # 6b ★ 两向锁死：若把历元换成 date，偏差必然远超阈值 ——
    #    证明「J2000 命中」不是恒真判据（这一条是给上面那条配的负控制）。
    e0 = mev[0]
    lon_date = float(cs.body_ecl_lonlat(eph, 'sun', e0["t"], epoch="date")[0])
    lon_j2000 = float(cs.body_ecl_lonlat(eph, 'sun', e0["t"], epoch="j2000")[0])
    dev = abs(((lon_date - lon_j2000 + 180) % 360) - 180)
    chk("负控制：历元若误用 date，偏差必然 > 0.05°（实得 %.4f°）" % dev, dev > 0.05)
    chk("负控制：λ☉ 判据在两历元下不能同时成立",
        not (abs(lon_date - e0["params"]["lambda_sun_deg"]) <= 0.0005
             and abs(lon_j2000 - e0["params"]["lambda_sun_deg"]) <= 0.0005))
    # 6c 源码级判据：流星雨生成器必须显式写 epoch="j2000"
    import inspect
    chk('流星雨生成器显式用 epoch="j2000"',
        'epoch="j2000"' in inspect.getsource(gen_meteor_peaks))

    # ── 7. 日食一致性检查会真的拦人（负控制） ──
    # ★ 必须用 `sys.modules[__name__]` 而不是 `import event_almanac as _self`：
    #   以 `python event_almanac.py` 直接运行时，本文件在 sys.modules 里的名字是
    #   **`__main__`**；再 import 一次会得到**第二个副本**，改副本的全局量对
    #   `__main__` 里的同名函数毫无影响 —— 负控制于是永远「不触发」，
    #   看上去像「检查没生效」，实则是**测试自己写错了模块对象**。
    _mod = sys.modules[__name__]
    orig = SOLAR_ECLIPSE_CATALOG[0]
    try:
        _mod.SOLAR_ECLIPSE_CATALOG = (
            dict(orig, date_ut="2026-02-27", td="12:13:05"),) + SOLAR_ECLIPSE_CATALOG[1:]
        raised = False
        try:
            gen_solar_eclipses_catalog(eph, 2026, 2026)
        except RuntimeError:
            raised = True
        chk("负控制：日食目录挑错日期必须被拦住", raised,
            "（未触发 ⇒ 检查形同虚设，或改错了模块对象）")
    finally:
        _mod.SOLAR_ECLIPSE_CATALOG = (orig,) + SOLAR_ECLIPSE_CATALOG[1:]
    # 正控制：改回来之后必须放行（否则判据是恒真的）
    chk("正控制：目录复原后必须放行（否则判据恒真）",
        len(gen_solar_eclipses_catalog(eph, 2026, 2026)) == 2)

    if verbose:
        print("event_almanac 自检：通过 %d 项 / 失败 %d 项" % (len(oks), len(fails)))
        for f in fails:
            print("   ✗ " + f)
    return 0 if not fails else 1


# =============================================================================
# CLI
# =============================================================================
def main(argv=None):
    ap = argparse.ArgumentParser(description="天象事件枚举（求根 + 装配）")
    ap.add_argument("--range", nargs=2, type=int, metavar=("Y0", "Y1"))
    ap.add_argument("--format", choices=["table", "json"], default="table")
    ap.add_argument("--out", type=str)
    ap.add_argument("--only", type=str, default="",
                    help="逗号分隔，限定生成器：" + ",".join(GENERATORS))
    ap.add_argument("--allow-unverified", action="store_true",
                    help="放行日食「食甚 vs 自算朔」时差 > 3h 的条目（默认不放行）")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)

    if a.selftest:
        return selftest()
    if a.verify:
        total, passed, lines = verify()
        print("\n".join(lines))
        print("\n对拍：%d/%d 项通过%s" % (passed, total, "" if passed == total else "  ✗"))
        return 0 if passed == total else 1
    if not a.range:
        ap.print_help()
        return 2

    y0, y1 = a.range
    which = [x.strip() for x in a.only.split(",") if x.strip()] or None
    eph = cs.load_ephemeris()
    ev, stat = build_events(y0, y1, eph=eph, which=which,
                            allow_unverified=a.allow_unverified)
    rows = to_rows(ev)

    if a.format == "json":
        text = json.dumps(rows, ensure_ascii=False, indent=2)
    else:
        text = "\n".join(
            "%-22s %-19s %-28s %s" % (r["event_type"], r["event_time_bj"],
                                      r["slug"], r["title"]) for r in rows)
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
        print("[event_almanac] 已写 %s（%d 行）" % (a.out, len(rows)))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
