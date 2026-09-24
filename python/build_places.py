#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建「全国观测地清单」—— 地级锚点（预计算）＋ 县级可选点（就近绑定）。

数据来源（均为公开接口，取证见 --report）
────────────────────────────────────────
* 行政区划边界与**中心点**：阿里 DataV GeoAtlas
    https://geo.datav.aliyun.com/areas_v3/bound/{adcode}_full.json
  每个 feature 的 properties 含 adcode / name / level / center / centroid /
  childrenNum / parent.adcode。`center` 是**政府驻地**点，本脚本取它（不是多边形质心）。
* 海拔：opentopodata（SRTM 90m 数据集）
    https://api.opentopodata.org/v1/srtm90m?locations=lat,lon
  单请求最多 100 个点、限速 1 次/秒、每日 1000 次 ⇒ 本脚本按 90 点/请求、1.1 秒间隔。

产物（两件，同一轮产出、sha1 互证）
────────────────────────────────────
  wp-astro-forecast/data/places_cn.json      ← canonical（含审计字段，构建侧与校验器读）
    provinces[34]  省 / 直辖市 / 特区（显示名统一为 **中国香港 / 中国澳门 / 中国台湾**）
    anchors[N]     地级锚点：key / adcode / cn / prov / lat / lon / elev / coord_src / curated
    places[~2850]  县级可选点：adcode / cn / prov / anchor / lat / lon / km
    notes[]        采集过程中的裁定与例外（供复核）
  wp-astro-forecast/assets/places-cn.json    ← 紧凑件（**前端**读：PHP 出无 JS 基线、JS 升级县级）
    形状为**数组的数组**而非对象数组（省下的全是重复的键名），并记 canonical 的 src_sha1
    ⇒ 页面不必内嵌百余 KB；它是全站共享的静态资源，浏览器只下一次。
    ⚠ 两件必须同一轮产出：`src_sha1` 就是这条判据的凭据。

口径与裁定（都写进 --report，便于复核）
────────────────────────────────────────
1. **直辖市**（京津沪渝）：其孩子全是区 ⇒ **锚点＝直辖市自身**，孩子＝县级。
2. **港澳**：其孩子是区 ⇒ **锚点＝特区自身**，孩子＝县级。显示名走中国香港 / 中国澳门。
3. **台湾省**：本数据源无下级（`710000_full.json` 不存在）⇒ **锚点＝台湾省（中心＝台北）**，无县级。
4. **省直辖县级**（济源 / 仙桃 / 潜江 / 天门 / 神农架 / 海南各县 / 新疆兵团市 等，
   `childrenNum == 0` 但不是直辖市的孩子）⇒ 作为**县级**，绑定到**本省内几何最近**的锚点。
5. **县级绑定规则**：优先绑**其 parent 地级锚点**（保证「省→市→县」级联自洽）；
   无 parent 锚点时绑**本省几何最近锚点**。距离＝两点平面近似直线距离（km，取整）。
6. **38 个既有城市**（`compute_sky.CONFIG.CITIES_LEGACY` 的人工校订档）
   **key、坐标、海拔三样一律保留**（`coord_src == 'curated'`），
   新锚点按 adcode 命名 key、坐标取 DataV 政府驻地（`coord_src == 'datav'`）。
   ⇒ 老键不失效、老数值不变。⚠ 首版只锁了 key 与海拔、坐标仍取 DataV，
   实测把揭阳挪了约 2 km；虽有秒级影响、对外只表达到分钟，仍按「既有对外数值不许
   静默漂移」的口径改为三样全锁。

用法
────
  python build_places.py                # 采集（带缓存）+ 生成
  python build_places.py --refresh      # 忽略缓存重新下载
  python build_places.py --report       # 只打印统计与裁定，不写盘
  python build_places.py --offline      # 只用缓存（缺缓存即报错，不静默）
"""
from __future__ import print_function

import argparse
import hashlib
import io
import json
import math
import os
import re
import sys
import time

try:
    from urllib.request import urlopen, Request
    from urllib.error import HTTPError, URLError
except ImportError:  # pragma: no cover
    from urllib2 import urlopen, Request, HTTPError, URLError

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PLUGIN = os.path.join(ROOT, "wp-astro-forecast")
OUT_JSON = os.path.join(PLUGIN, "data", "places_cn.json")
# 前端紧凑资产（PHP 渲染无 JS 基线用 provinces+anchors；JS 升级为县级清单用 places）。
# ★ 为什么要另出一份、而不把上面那份塞进页面：
#   上面那份 502 KB / indent=1，且含 notes、source、generated_at 等**审计字段**。
#   页面要的是「能放进 <select> 的最小集」。塞进去会让每页 HTML 多出百余 KB，
#   而它是**全站共享、可缓存的静态资源**，单独出文件后浏览器只下一次。
# ★ 两份不许各写一遍（会漂移）：本文件**同一轮**写出，紧凑件里记 canonical 的 sha1，
#   verify_package.py 有判据对拍 ⇒ 「同一轮产出」是可验证的。
OUT_ASSET = os.path.join(PLUGIN, "assets", "places-cn.json")
CACHE = os.path.join(HERE, "_geo_cache")

GEO = "https://geo.datav.aliyun.com/areas_v3/bound/%s_full.json"
ELEV = "https://api.opentopodata.org/v1/srtm90m"

# 直辖市（其孩子是「区」，锚点取直辖市自身）
MUNICIPAL = {"110000", "120000", "310000", "500000"}
# 特别行政区（同口径：锚点取特区自身）
SAR = {"810000", "820000"}
# 台湾省（本数据源无下级）
TAIWAN = "710000"
# 非行政区划的伪 feature（九段线）
SKIP_ADCODE = {"100000_JD"}

# 显示名覆盖：港澳台一律用「中国香港 / 中国澳门 / 中国台湾」口径
PROV_NAME_FIX = {
    "810000": u"中国香港",
    "820000": u"中国澳门",
    "710000": u"中国台湾",
}
# 锚点中文名覆盖（去掉「市」等后缀由 name_short 统一处理，这里只处理特例）
ANCHOR_NAME_FIX = {
    "710000": u"台北",   # 台湾省无下级，中心点即台北
    "810000": u"香港",
    "820000": u"澳门",
}

# 38 个既有城市键（与 compute_sky.CONFIG.CITIES 的第一批一致）——
# 仅用于「按中文名认领旧键」，值一律从 compute_sky 现读，不在此重写一份。
LEGACY_KEYS = (
    "jieyang", "guangzhou", "shenzhen", "nanning", "haikou", "hongkong", "macau",
    "shanghai", "nanjing", "hangzhou", "hefei", "fuzhou", "xiamen", "nanchang",
    "jinan", "qingdao", "taibei", "wuhan", "changsha", "zhengzhou",
    "beijing", "tianjin", "shijiazhuang", "taiyuan", "huhehaote",
    "shenyang", "changchun", "harbin",
    "chongqing", "chengdu", "guiyang", "kunming", "lhasa",
    "xian", "lanzhou", "xining", "yinchuan", "wulumqi",
)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")


# --------------------------------------------------------------------------
# 网络（带缓存）
# --------------------------------------------------------------------------
def _http_bytes(url, timeout=40, tries=3):
    last = None
    for i in range(tries):
        try:
            req = Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urlopen(req, timeout=timeout) as r:
                return r.read()
        except HTTPError as e:
            if e.code == 404:
                return None            # 明确的「没有」，不当网络故障重试
            last = e
        except Exception as e:         # URLError / timeout / ssl
            last = e
        time.sleep(1.2 * (i + 1))
    raise RuntimeError("下载失败 %s：%s" % (url, last))


def cached_json(adcode, refresh=False, offline=False):
    """取 {adcode}.json。返回 (data|None, 来源)。None ＝ 上游明确 404。"""
    os.makedirs(CACHE, exist_ok=True)
    p404 = os.path.join(CACHE, "%s.missing" % adcode)
    p = os.path.join(CACHE, "%s.json" % adcode)
    if not refresh:
        if os.path.exists(p404):
            return None, "cache-404"
        if os.path.exists(p):
            with io.open(p, encoding="utf-8") as f:
                return json.load(f), "cache"
    if offline:
        raise RuntimeError("离线模式但缺缓存：%s" % adcode)
    b = _http_bytes(GEO % adcode)
    if b is None:
        io.open(p404, "w").close()
        return None, "http-404"
    d = json.loads(b.decode("utf-8"))
    with io.open(p, "wb") as f:
        f.write(json.dumps(d, ensure_ascii=False).encode("utf-8"))
    return d, "http"


def feats(d):
    """GeoJSON features（顺序即官方 subFeatureIndex 顺序）。"""
    if not d:
        return []
    fs = d.get("features") or []
    return [f for f in fs if isinstance(f.get("properties"), dict)]


# --------------------------------------------------------------------------
# 几何
# --------------------------------------------------------------------------
def dist_km(lat1, lon1, lat2, lon2):
    """平面近似直线距离。与 compute_sky.nearest_city / astro-place.js 同源常数。"""
    dy = (lat1 - lat2) * 111.2
    dx = (lon1 - lon2) * 111.2 * math.cos(math.radians((lat1 + lat2) / 2.0))
    return math.hypot(dx, dy)


def center_of(p):
    """取中心点：优先 center（政府驻地），回落 centroid（多边形质心）。"""
    c = p.get("center") or p.get("centroid")
    if not c or len(c) != 2:
        return None, None
    try:
        lon = float(c[0])
        lat = float(c[1])
    except (TypeError, ValueError):
        return None, None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None, None
    return lat, lon


def name_short(cn):
    """显示名去掉行政级别后缀（保留「自治州/地区/盟」的可读性）。"""
    s = (cn or u"").strip()
    s = re.sub(u"[特别]*行政区$", u"", s)
    s = re.sub(u"自治州$", u"州", s)
    s = re.sub(u"地区$", u"", s)
    s = re.sub(u"盟$", u"", s)
    s = re.sub(u"[省市]$", u"", s)
    return s


def is_prov_direct_county(rec):
    """`childrenNum == 0` 的孩子里，谁还是**县级**（省直辖县级行政区）。

    ★ 判据只能用 adcode，不能用 level：DataV 把「不设区的地级市」（东莞 441900、
      中山 442000、嘉峪关 620200、儋州 460400）与「省直辖县级市/县」
      （济源 419001、仙桃 429004、海南各县 469xxx、新疆兵团市 659xxx）
      **一律标成 `level == 'city'`** ⇒ 按 level 判会把东莞当成县级绑到广州（60 km 外）。
    ★ 可靠判据：省直辖县级行政区的 adcode **第 3 位（0 起算第 2 位）恒为 9**
      （4190xx / 4290xx / 4690xx / 6590xx）；不设区地级市该位为 1/2/0。
      ⇒ 该位是 '9' 即县级；否则视为**地级锚点**。
    """
    ad = rec.get("adcode") or ""
    return len(ad) >= 3 and ad[2] == "9"


# --------------------------------------------------------------------------
# 海拔
# --------------------------------------------------------------------------
def fetch_elevations(points, refresh=False, offline=False):
    """points = [(lat, lon), ...] → [elev, ...]（米，float）。

    失败点**返回 None 而不是 0** —— 「没查到」与「海平面」不是一回事。
    调用方对 None 必须回落（本脚本回落 0 并计入 accounted 报告）。
    """
    os.makedirs(CACHE, exist_ok=True)
    cache_p = os.path.join(CACHE, "elev.json")
    cache = {}
    if os.path.exists(cache_p) and not refresh:
        with io.open(cache_p, encoding="utf-8") as f:
            cache = json.load(f)
    todo = []
    for la, lo in points:
        k = "%.3f,%.3f" % (la, lo)
        if k not in cache:
            todo.append(k)
    if todo and not offline:
        batch = 90
        for i in range(0, len(todo), batch):
            chunk = todo[i:i + batch]
            url = ELEV + "?locations=" + "|".join(chunk)
            for attempt in range(3):
                try:
                    b = _http_bytes(url, timeout=45)
                    d = json.loads(b.decode("utf-8"))
                    if d.get("status") != "OK":
                        raise RuntimeError("接口 status=%s" % d.get("status"))
                    for k, r in zip(chunk, d.get("results") or []):
                        e = r.get("elevation")
                        cache[k] = (None if e is None else round(float(e), 1))
                    break
                except Exception as e:
                    if attempt == 2:
                        print("   ⚠ 海拔批次失败（%s）—— 该批 %d 点记 NULL" % (e, len(chunk)),
                              file=sys.stderr)
                        for k in chunk:
                            cache.setdefault(k, None)
                    time.sleep(1.6)
            time.sleep(1.1)      # 接口限速 1 次/秒
        with io.open(cache_p, "wb") as f:
            f.write(json.dumps(cache, ensure_ascii=False, indent=0).encode("utf-8"))
    elif todo and offline:
        for k in todo:
            cache.setdefault(k, None)
    out = []
    for la, lo in points:
        out.append(cache.get("%.3f,%.3f" % (la, lo)))
    return out


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def legacy_table():
    """现读 compute_sky 的**人工校订档**（`CITIES_LEGACY`，38 条），供「按中文名认领旧键」。

    ★ 必须读 `CITIES_LEGACY`，不能读 `CITIES`：v2.3.0 起 `CITIES` 本身就是
      **由本脚本产物 `places_cn.json` 反填**的（340 锚点）。若此处读 `CITIES`，
      就成了「用上次的产物认领本次的键」—— 自举循环：`places_cn.json` 一被删或
      被写坏，旧键认领表随之消失，340 条锚点会**全部改叫 adcode**，
      而脚本不会报任何错（它只是「认领到 0 条」），于是老键静默失效、
      历史数据件与历史 URL 同时断链。`CITIES_LEGACY` 是源码里的常量，不受产物影响。
    """
    sys.path.insert(0, HERE)
    import compute_sky
    base = getattr(compute_sky.CONFIG, "CITIES_LEGACY", None)
    if base is None:
        raise RuntimeError("compute_sky.CONFIG.CITIES_LEGACY 不存在 —— 旧键认领表缺失，"
                           "拒绝继续（静默生成 340 个 adcode 键会断掉历史 URL）")
    # ★ 返回**四元组**（key, lat, lon, elev），不是二元组：
    #   首版只认领了 key 与海拔，坐标仍取 DataV 的 center ⇒ 实测揭阳由
    #   (23.55, 116.37) 变成 (23.543778, 116.355733)，**挪了约 2 km**。
    #   2 km 对升落的影响在秒级、对外只表达到分钟 ⇒ 数值上无害，但那是
    #   「同一座城被静默挪了位置」，且与人工校订档的存在意义（锁住既有基线）相悖。
    #   本项目对「既有对外数值」的纪律是不许静默漂移，故坐标一并锁。
    return {v[3]: (k, float(v[0]), float(v[1]), float(v[2]))
            for k, v in base.items() if k in LEGACY_KEYS}


def _pick_anchor(cn, adcode, dlat, dlon, legacy):
    """定锚点的 (key, lat, lon, elev, coord_src)。

    优先级：**人工校订档**（按中文名）＞ DataV 政府驻地中心点。
    校订档命中时连坐标一起用 —— 老键必须站回老位置（见 legacy_table 的说明）。
    elev 未定者留 None，交给后面的海拔采集；**不得**在此填 0，
    否则 `a["elev"] is None` 的判据失效，那批点会**一个都不去取海拔**。
    """
    hit = legacy.get(cn)
    if hit:
        return hit[0], hit[1], hit[2], hit[3], "curated"
    return adcode, dlat, dlon, None, "datav"


def build(refresh=False, offline=False):
    prov_d, src = cached_json("100000", refresh, offline)
    ps = feats(prov_d)
    if not ps:
        raise RuntimeError("省级清单为空 —— 不做「成功地什么都没做」，直接判失败")
    print("[build_places] 省级 feature %d 个（来源 %s）" % (len(ps), src))

    legacy = legacy_table()
    print("[build_places] 认领旧键：%d 条（按中文名匹配）" % len(legacy))

    provinces = []
    anchors = []          # dict：key/adcode/cn/prov/lat/lon/elev/curated
    places = []           # dict：adcode/cn/prov/anchor/lat/lon/km
    notes = []

    for pf in ps:
        p = pf["properties"]
        pad = str(p.get("adcode") or "")
        if not pad or pad in SKIP_ADCODE:
            notes.append(u"跳过伪 feature：%s（%s）" % (pad, p.get("name")))
            continue
        pname = PROV_NAME_FIX.get(pad, p.get("name") or pad)
        pl0, plo0 = center_of(p)
        provinces.append({"adcode": pad, "name": pname})

        is_muni = pad in MUNICIPAL
        is_sar = pad in SAR
        is_tw = (pad == TAIWAN)

        # ── 直辖市 / 特区 / 台湾：锚点＝其自身 ───────────────────────────
        if is_muni or is_sar or is_tw:
            cn = ANCHOR_NAME_FIX.get(pad) or name_short(pname)
            key, ala, alo, elev, csrc = _pick_anchor(cn, pad, pl0, plo0, legacy)
            anchors.append({"key": key, "adcode": pad, "cn": cn, "prov": pad,
                            "lat": ala, "lon": alo, "elev": elev,
                            "coord_src": csrc, "curated": cn in legacy})
            kids, ksrc = cached_json(pad, refresh, offline)
            if not ksrc.endswith("404"):
                for kf in feats(kids):
                    kp = kf["properties"]
                    la, lo = center_of(kp)
                    if la is None:
                        continue
                    places.append({"adcode": str(kp.get("adcode") or ""),
                                   "cn": name_short(kp.get("name")),
                                   "prov": pad, "anchor": key,
                                   "lat": la, "lon": lo,
                                   # 距离按**锚点实际坐标**算（校订档与 DataV 可能不同）
                                   "km": int(round(dist_km(la, lo, ala, alo)))})
            else:
                notes.append(u"%s 无下级区划（%s）⇒ 只有一个可选点" % (pname, ksrc))
            continue

        # ── 普通省：先取直接孩子，再按 childrenNum 定锚点 ────────────────
        kids_d, ksrc = cached_json(pad, refresh, offline)
        kfs = feats(kids_d)
        if not kfs:
            notes.append(u"%s 无下级清单（%s）" % (pname, ksrc))
            continue
        lvl_anchor, lvl_leaf = [], []
        for kf in kfs:
            kp = kf["properties"]
            la, lo = center_of(kp)
            if la is None:
                notes.append(u"跳过（无中心点）：%s %s" % (kp.get("adcode"), kp.get("name")))
                continue
            rec = {"adcode": str(kp.get("adcode") or ""), "cn": name_short(kp.get("name")),
                   "prov": pad, "lat": la, "lon": lo,
                   "children": int(kp.get("childrenNum") or 0)}
            if rec["children"] > 0 or not is_prov_direct_county(rec):
                lvl_anchor.append(rec)
            else:
                lvl_leaf.append(rec)

        cn2key = {}
        for rec in lvl_anchor:
            cn = rec["cn"]
            key, ala, alo, elev, csrc = _pick_anchor(cn, rec["adcode"],
                                                     rec["lat"], rec["lon"], legacy)
            rec["key"] = key
            rec["elev"] = elev
            rec["curated"] = cn in legacy
            anchors.append({"key": key, "adcode": rec["adcode"], "cn": cn, "prov": pad,
                            "lat": ala, "lon": alo, "elev": elev,
                            "coord_src": csrc, "curated": rec["curated"]})
            cn2key[cn] = key
            # 该地级的孩子 = 县级
            gd, gsrc = cached_json(rec["adcode"], refresh, offline)
            n_gk = 0
            for gf in feats(gd):
                gp = gf["properties"]
                gla, glo = center_of(gp)
                if gla is None:
                    continue
                places.append({"adcode": str(gp.get("adcode") or ""),
                               "cn": name_short(gp.get("name")), "prov": pad,
                               "anchor": key, "lat": gla, "lon": glo,
                               # 距离按锚点实际坐标算（校订档与 DataV 可能不同）
                               "km": int(round(dist_km(gla, glo, ala, alo)))})
                n_gk += 1
            if n_gk == 0:
                notes.append(u"%s 无县级清单（%s）" % (cn, gsrc))

        # 省直辖县级：绑本省几何最近的锚点
        if lvl_leaf:
            if not lvl_anchor:
                notes.append(u"%s 一个地级锚点都没有，省直辖县级无法绑定 ⇒ 跳过 %d 个"
                             % (pname, len(lvl_leaf)))
            else:
                for rec in lvl_leaf:
                    best, bd = None, None
                    for a in lvl_anchor:
                        d = dist_km(rec["lat"], rec["lon"], a["lat"], a["lon"])
                        if bd is None or d < bd:
                            best, bd = a["key"], d
                    places.append({"adcode": rec["adcode"], "cn": rec["cn"], "prov": pad,
                                   "anchor": best, "lat": rec["lat"], "lon": rec["lon"],
                                   "km": int(round(bd))})
                notes.append(u"%s：%d 个省直辖县级按「本省最近锚点」绑定"
                             % (pname, len(lvl_leaf)))

    # ── 去重（adcode 唯一）──────────────────────────────────────────────
    seen = set()
    ded = []
    dup = 0
    for r in places:
        k = (r["adcode"], r["cn"], r["anchor"])
        if k in seen:
            dup += 1
            continue
        seen.add(k)
        ded.append(r)
    places = ded
    if dup:
        notes.append(u"县级去重：丢弃重复 %d 条" % dup)

    # ── 锚点海拔（未校订者向接口取）────────────────────────────────────
    need = [(a["lat"], a["lon"]) for a in anchors if a["elev"] is None]
    print("[build_places] 锚点 %d 个，其中 %d 个待取海拔" % (len(anchors), len(need)))
    if need:
        els = fetch_elevations(need, refresh, offline)
        it = iter(els)
        miss = 0
        for a in anchors:
            if a["elev"] is None:
                v = next(it)
                if v is None:
                    miss += 1
                    a["elev"] = 0.0
                else:
                    a["elev"] = round(float(v), 1)
        if miss:
            notes.append(u"海拔缺失 %d 个锚点 ⇒ 回落 0 m（海拔影响升落 10—30 秒，"
                         u"高原站点会偏大，留待补录）" % miss)
        for a in anchors:
            if a["elev"] is None:
                a["elev"] = 0.0

    doc = {
        "generated_by": "python/build_places.py",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "anchor_date": time.strftime("%Y-%m-%d"),
        "source": {
            "boundary": "阿里 DataV GeoAtlas areas_v3 (bound/{adcode}_full.json)；取 properties.center（政府驻地）",
            "elevation": "opentopodata srtm90m",
            "legacy": "compute_sky.CONFIG.CITIES 人工校订档（38 条，key 与海拔保留）",
        },
        "provinces": provinces,
        "anchors": anchors,
        "places": places,
        "notes": notes,
    }
    return doc


def _blen(s):
    """UTF-8 字节长度。落库列宽按**字节**判（线上列是 latin1），故一律按字节量。"""
    return len((s or u"").encode("utf-8"))


def report(doc):
    P, A, C = doc["provinces"], doc["anchors"], doc["places"]
    print("=" * 78)
    print(u"省/直辖市/特区：%d" % len(P))
    print(u"地级锚点：%d（其中沿用人工校订 key/坐标/海拔：%d）"
          % (len(A), sum(1 for a in A if a.get("curated"))))
    print(u"坐标来源：校订 %d ／ DataV %d"
          % (sum(1 for a in A if a.get("coord_src") == "curated"),
             sum(1 for a in A if a.get("coord_src") != "curated")))
    print(u"县级可选点：%d" % len(C))
    print(u"锚点海拔已取到：%d / %d" % (sum(1 for a in A if a["elev"]), len(A)))
    zero_e = [u"%s(%s)" % (a["cn"], a["key"]) for a in A if not a["elev"]]
    if zero_e:
        print(u"　└ 海拔为 0/缺失的锚点：%s" % u"、".join(zero_e))
    bad = [a for a in A if not (-90 <= a["lat"] <= 90 and -180 <= a["lon"] <= 180)]
    print(u"锚点坐标越界：%d" % len(bad))
    # ★ 落库列宽前置检查：锚点中文名进 `astro_daily_site.city_cn VARCHAR(32)`，
    #   而线上该表是 **latin1** ⇒ WordPress 按**字节**判 ⇒ 32 字节 ＝ **10 个汉字**上限。
    #   超了会**整行被拒**，而错误消息不含数字（F27 的同族事故）。此处按字节先量一遍：
    #   判据在**生成侧**，比让它在导入时炸掉强得多。
    wide = [(a["cn"], _blen(a["cn"])) for a in A if _blen(a["cn"]) > 32]
    print(u"锚点中文名超 city_cn(32 字节＝10 汉字) 的：%d 个%s"
          % (len(wide), (u"（" + u"、".join(u"%s %d B" % w for w in wide[:6]) + u"）") if wide else u""))
    widek = [a["key"] for a in A if _blen(a["key"]) > 32]
    print(u"锚点 key 超 city(32 字节) 的：%d 个" % len(widek))
    keys = [a["key"] for a in A]
    print(u"锚点 key 唯一：%s（重复 %d）" % (len(set(keys)) == len(keys), len(keys) - len(set(keys))))
    ak = set(keys)
    orphan = [c for c in C if c["anchor"] not in ak]
    print(u"县级绑定悬空：%d" % len(orphan))
    far = sorted(C, key=lambda c: -c["km"])[:8]
    print(u"县级里离锚点最远的 8 个（km）：" +
          u" / ".join(u"%s %d" % (c["cn"], c["km"]) for c in far))
    km = [c["km"] for c in C]
    if km:
        km2 = sorted(km)
        print(u"县级距离：中位 %d km ／ 90 分位 %d km ／ 最大 %d km"
              % (km2[len(km2) // 2], km2[int(len(km2) * 0.9)], km2[-1]))
    print(u"县级最多的 6 个锚点：")
    cnt = {}
    for c in C:
        cnt[c["anchor"]] = cnt.get(c["anchor"], 0) + 1
    for k, n in sorted(cnt.items(), key=lambda x: -x[1])[:6]:
        cn = next((a["cn"] for a in A if a["key"] == k), k)
        print(u"   %s（%s）%d 个" % (cn, k, n))
    zero = [a["cn"] for a in A if cnt.get(a["key"], 0) == 0]
    print(u"没有任何县级可选项的锚点：%d 个%s"
          % (len(zero), u"（前 12：" + u"、".join(zero[:12]) + u"）" if zero else u""))
    if doc.get("notes"):
        print("-" * 78)
        for n in doc["notes"]:
            print(u"· " + n)
    print("=" * 78)


def main(argv=None):
    ap = argparse.ArgumentParser(description="构建全国观测地清单（地级锚点 + 县级可选点）")
    ap.add_argument("--refresh", action="store_true", help="忽略缓存重新下载")
    ap.add_argument("--offline", action="store_true", help="只用缓存；缺缓存即报错")
    ap.add_argument("--report", action="store_true", help="只打印统计，不写盘")
    ap.add_argument("--out", default=OUT_JSON, help="输出 JSON 路径")
    args = ap.parse_args(argv)

    doc = build(args.refresh, args.offline)
    report(doc)
    if args.report:
        print("[build_places] --report：未写盘")
        return 0
    if not doc["anchors"] or not doc["places"]:
        print("[build_places] 致命：锚点或县级为空（空集守卫）⇒ 不写盘", file=sys.stderr)
        return 3
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    b = json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8")
    with io.open(args.out, "wb") as f:
        f.write(b)
    print(u"[build_places] 写出 %s（%d B ／ 锚点 %d ／ 县级 %d）"
          % (os.path.relpath(args.out, ROOT), len(b), len(doc["anchors"]), len(doc["places"])))

    # ── 前端紧凑资产（与上件同一轮产出，sha1 互证）──────────────────────
    sha = hashlib.sha1(b).hexdigest()
    asset = {
        "v": 1,
        "at": doc["anchor_date"],
        # canonical 的 sha1：PHP/JS 都不读它，它给**校验器**用 ——
        # 判据 = 「紧凑件声明的 sha1 == canonical 实际 sha1」⇒ 两件必同一轮产出。
        "src_sha1": sha,
        "anchor_count": len(doc["anchors"]),
        "provinces": [[p["adcode"], p["name"]] for p in doc["provinces"]],
        # [key, cn, prov, lat, lon]
        "anchors": [[a["key"], a["cn"], a["prov"], a["lat"], a["lon"]] for a in doc["anchors"]],
        # [adcode, cn, anchor, km]  —— 县级统一绑到一个**锚点**（预计算过升落的那一批）
        "places": [[c["adcode"], c["cn"], c["anchor"], c["km"]] for c in doc["places"]],
    }
    ab = json.dumps(asset, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    os.makedirs(os.path.dirname(OUT_ASSET), exist_ok=True)
    with io.open(OUT_ASSET, "wb") as f:
        f.write(ab)
    print(u"[build_places] 写出 %s（%d B ／ 紧凑；sha1 %s…）"
          % (os.path.relpath(OUT_ASSET, ROOT), len(ab), sha[:12]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
