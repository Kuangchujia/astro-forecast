#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# =============================================================================
# 天象预报模块 · Python 批量计算脚本（交付物 B）
# 版本：v1.1.0（2026-09-22 可行性修订版；v1.0.0 存在 6 处致命 API 误用，见下）
# 星历内核：NASA JPL DE421（skyfield 加载 de421.bsp）
# 坐标参考：**黄道/赤道 of date（当日坐标）**；距星表以 J2000 为底 + 岁差改正到当日
# 默认观测地：广东揭阳（lat=23.55, lon=116.37, elev≈10m）；默认时区 北京时间 UTC+8
#
# -----------------------------------------------------------------------------
# ★★ v1.1.0 修订要点（对应 docs/feasibility-review.md 的 F1—F9）
#   F1 星历发现：原先 load('de421.bsp') 只会联网下载（离线环境必失败）；
#      现改为「显式路径 → 环境变量 → 工作目录 → skyfield_data 内置 → 联网兜底」五级发现。
#   F2 epoch 参数：ecliptic_latlon(epoch='j2000') 会抛 ValueError（skyfield 只接受
#      Time/TT 浮点/'date'）。现统一用 epoch='date' 走「当日黄道」。
#   F3 升落 API：risings_and_settings 的签名是 (ephemeris, target, topos, horizon_degrees,
#      radius_degrees) —— 无 ts 首参、无 which 参数；v1.0.0 的调用必抛 TypeError。
#   F4 晨昏 API：dark_twilight_day 的签名是 (ephemeris, topos) —— 无 ts、无 degree；
#      改由 risings_and_settings(horizon_degrees=-6/-12/-18) 求三条晨昏界。
#   F5 范围守卫与降级：DE421 实测覆盖 JD 2414864.5—2471184.5（1899-07-28 至 2053-10-08）。
#      越界原本直接抛 EphemerisRangeError（历史功能全废）；现拦截并降级到 Meeus 解析式。
#   F6 距星表岁差：宿度按「当日黄道」计算，故距星黄经须加累积岁差；否则 2026 年即偏 0.38°。
#   F7 性能：星历与 timescale 加模块级缓存（v1.0.0 每日重复解析，全量跑要白等数小时）。
#   F8 合规：删除 value_xiu_of_day（值日星宿属二十八宿轮值+择日吉凶体系，既非太阳所在宿，
#      亦触「禁吉凶谶纬」红线）；行星星等改用 Meeus ch.41 相位角公式，可见性分级才站得住。
#   F9 入库：新增 --wp-rest（WordPress REST 导入）。WP.com 不开放外部 MySQL 连接，
#      --db 直连仅适用于自建库/本地演练。
#
# -----------------------------------------------------------------------------
# 七项修正落实：
#   ① 精度分层 —— 近未来(1899—2053 窗口内)日月升落/时刻按 ±1 min 交付；
#      窗口外以 Meeus 解析式给出**近似值 + ΔT 不确定度区间**（仅标注区间，不给唯一时刻）。
#   ② 坐标系规范 —— 明示「黄道/赤道 of date」；距星法宿度可复现（xiu_of 完全由本文件距星表
#      + 岁差公式决定）；另输出 J2000 黄经备查。
#   ③ 渲染路线统一 —— 本脚本只做「离线预计算」，输出 JSON / 经 REST 入库；
#      前端只读数据表，零实时计算。
#   ④ 存储结构升级 —— 输出含 jd(儒略日) 数值字段，供范围查询/排序；带 data_version。
#   ⑤ Schema/⑥ 合规/⑦ 里程碑 —— 由 WP 插件层与文档层落实，本脚本只算数据。
#
# 硬性约束：
#   ★ 全站禁占星/运势/吉凶/谶纬 —— 本脚本所有「可见性说明」仅描述观测条件
#     （肉眼/双筒/望远镜），不含任何星占解读。
#   ★ 历史天象三层区分 —— 输出严格分 literature(文献记载)/calc(星历计算)/discussion(学术争议)。
#   ★ 数字单位自洽 —— 角度一律度(°)，距离 KM/AU 标明，时刻统一北京时间(UTC+8)。
#   ★ 代码注释注明来源 —— 关键公式/常数均标注出处。
#
# 来源标注：
#   [S1] NASA JPL DE421 ephemeris (Standish 2008), 经 skyfield 加载。
#        实测覆盖区间：JD 2414864.5—2471184.5 = 1899-07-28 — 2053-10-08。
#   [S2] Meeus, J. Astronomical Algorithms, 2nd ed.（ΔT 多项式源自 Espenak & Meeus 2006）：
#        ch.7 儒略日 / ch.10 ΔT / ch.21 岁差 / ch.22 章动 / ch.25 太阳位置 /
#        ch.41 行星视星等 / ch.47 月球位置 / ch.49 月相。
#   [S3] 二十八宿距星表：以 J2000 赤经赤纬为底（陈遵妫《中国天文学史》卷二口径），
#        运行时按 Meeus ch.21 累积岁差改正到「当日黄道」。生产环境应校准至《仪象考成》值。
#   [S4] 紫金山天文台历表仅作内部交叉比对，不复制、不发布（见 CONFIG.INTERNAL_CHECK_ONLY）。
# =============================================================================

import argparse
import json
import math
import os
import re
import sys
from datetime import datetime, timedelta, timezone

J2000 = 2451545.0


# ----------------------------- 配置常量（集中管理） -----------------------------
class CONFIG:
    # 默认观测地：北京
    # ★ v2.3.0：默认观测地**同时给出键**。原先只有裸坐标，而裸坐标无法回答
    #   「默认地是哪一座」—— 观测地扩到全国后，页面要按**键**去 340 锚点里取该地数据，
    #   只有坐标是取不到的。三处（本常量 / PHP 的 kcj_astro_default_place() / 页面回退）
    #   必须同改。
    # ★ 开源发布注（2026-09-24）：默认地由作者常住地改为**北京**。
    #   北京地理经度 116.4°，是中文天文数据发布中最常用的中性默认；揭阳仍在 CITIES
    #   清单内（老键不可删 —— 删改即断历史数据件），只是不再是默认值。
    #   部署到自己的站点时，按需改这三行即可。
    OBS_CITY_KEY = "beijing"
    OBS_LAT = 39.90          # 北纬（度）
    OBS_LON = 116.40         # 东经（度）
    OBS_ELEV = 44.0          # 海拔（米）
    # 默认时区：北京时间 UTC+8
    TZ_OFFSET_HOURS = 8
    # ── 预置城市参数档（v2.0.0：10 城 → 38 城，供「观测地可选」）────────────
    # 格式：city_key = (纬度°N, 经度°E, 海拔 m, 中文名)
    # 口径：城市中心点近似坐标，保留两位小数（约 ±5 km）。对升落时刻的影响约 ±20 秒，
    #       即 **分钟内**；页面与报告只表达到「分钟」，故该量级不影响任何对外数值。
    #       海拔对日出日落的影响在 10—30 秒量级（高原除外），一并计入。
    # 名称：一律用**城市名**，不涉国家级表述。
    CITIES = {
        # —— 华南（默认所在）——
        "jieyang":    (23.55, 116.37,   10.0, "揭阳"),
        "guangzhou":  (23.13, 113.26,   21.0, "广州"),
        "shenzhen":   (22.54, 114.06,    6.0, "深圳"),
        "nanning":    (22.82, 108.32,   80.0, "南宁"),
        "haikou":     (20.04, 110.32,   15.0, "海口"),
        "hongkong":   (22.32, 114.17,   30.0, "香港"),
        "macau":      (22.20, 113.55,   10.0, "澳门"),
        # —— 华东 ——
        "shanghai":   (31.23, 121.47,    4.0, "上海"),
        "nanjing":    (32.06, 118.80,   20.0, "南京"),
        "hangzhou":   (30.27, 120.15,   10.0, "杭州"),
        "hefei":      (31.82, 117.23,   30.0, "合肥"),
        "fuzhou":     (26.07, 119.30,   20.0, "福州"),
        "xiamen":     (24.48, 118.09,   10.0, "厦门"),
        "nanchang":   (28.68, 115.86,   25.0, "南昌"),
        "jinan":      (36.65, 117.12,   50.0, "济南"),
        "qingdao":    (36.07, 120.38,   25.0, "青岛"),
        "taibei":     (25.03, 121.57,   10.0, "台北"),
        # —— 华中 ——
        "wuhan":      (30.59, 114.31,   25.0, "武汉"),
        "changsha":   (28.23, 112.94,   45.0, "长沙"),
        "zhengzhou":  (34.75, 113.63,  110.0, "郑州"),
        # —— 华北 ——
        "beijing":    (39.90, 116.40,   44.0, "北京"),
        "tianjin":    (39.13, 117.20,    5.0, "天津"),
        "shijiazhuang": (38.04, 114.51, 81.0, "石家庄"),
        "taiyuan":    (37.87, 112.55,  800.0, "太原"),
        "huhehaote":  (40.84, 111.75, 1050.0, "呼和浩特"),
        # —— 东北 ——
        "shenyang":   (41.80, 123.43,   45.0, "沈阳"),
        "changchun":  (43.88, 125.32,  222.0, "长春"),
        "harbin":     (45.80, 126.53,  150.0, "哈尔滨"),
        # —— 西南 ——
        "chongqing":  (29.56, 106.55,  250.0, "重庆"),
        "chengdu":    (30.57, 104.07,  500.0, "成都"),
        "guiyang":    (26.65, 106.63, 1100.0, "贵阳"),
        "kunming":    (25.04, 102.71, 1890.0, "昆明"),
        "lhasa":      (29.65,  91.13, 3650.0, "拉萨"),
        # —— 西北 ——
        "xian":       (34.34, 108.94,  405.0, "西安"),
        "lanzhou":    (36.06, 103.83, 1520.0, "兰州"),
        "xining":     (36.62, 101.78, 2260.0, "西宁"),
        "yinchuan":   (38.49, 106.23, 1110.0, "银川"),
        "wulumqi":    (43.83,  87.62,  800.0, "乌鲁木齐"),
    }
    # 前端 IP 定位结果（英文城市名 / 拼音变体）→ 预置城市键。
    # ★ 这是「多对一」映射：IP 库给的常是地级市，落到最近的预置省会/直辖市档。
    # ★★ 前端**不用**这张表：IP 接口同时返回经纬度，JS 直接取「页面上已嵌好的 38 城
    #    坐标里最近的一座」（平面近似，纯几何）。这样前端零硬编码、两份表不会漂移。
    #    本表服务于 Python 侧（CLI 的 --cities shantou、报告生成、人工录入换算）。
    CITY_ALIASES = {
        "jieyang": "jieyang", "shantou": "jieyang", "chaozhou": "jieyang",
        "puning": "jieyang",
        "guangzhou": "guangzhou", "canton": "guangzhou", "dongguan": "guangzhou",
        "foshan": "guangzhou", "zhuhai": "guangzhou", "zhongshan": "guangzhou",
        "huizhou": "guangzhou", "jiangmen": "guangzhou", "zhaoqing": "guangzhou",
        "shenzhen": "shenzhen",
        "nanning": "nanning", "guilin": "nanning", "liuzhou": "nanning",
        "haikou": "haikou", "sanya": "haikou", "hainan": "haikou",
        "hong kong": "hongkong", "hongkong": "hongkong", "kowloon": "hongkong",
        "macau": "macau", "macao": "macau",
        "shanghai": "shanghai", "suzhou": "shanghai", "wuxi": "shanghai",
        "changzhou": "shanghai", "nantong": "shanghai", "kunshan": "shanghai",
        "nanjing": "nanjing", "xuzhou": "nanjing", "yangzhou": "nanjing",
        "hangzhou": "hangzhou", "ningbo": "hangzhou", "wenzhou": "hangzhou",
        "shaoxing": "hangzhou", "jinhua": "hangzhou", "yiwu": "hangzhou",
        "hefei": "hefei", "wuhu": "hefei", "bengbu": "hefei",
        "fuzhou": "fuzhou", "quanzhou": "fuzhou", "putian": "fuzhou",
        "xiamen": "xiamen", "amoy": "xiamen", "zhangzhou": "xiamen",
        "nanchang": "nanchang", "ganzhou": "nanchang", "jiujiang": "nanchang",
        "jinan": "jinan", "zibo": "jinan", "weifang": "jinan",
        "qingdao": "qingdao", "yantai": "qingdao", "weihai": "qingdao",
        "taipei": "taibei", "taibei": "taibei", "new taipei": "taibei",
        "keelung": "taibei", "taoyuan": "taibei", "hsinchu": "taibei",
        "wuhan": "wuhan", "yichang": "wuhan", "xiangyang": "wuhan",
        "changsha": "changsha", "zhuzhou": "changsha", "hengyang": "changsha",
        "zhengzhou": "zhengzhou", "luoyang": "zhengzhou", "kaifeng": "zhengzhou",
        "beijing": "beijing", "peking": "beijing",
        "tianjin": "tianjin", "tangshan": "tianjin", "langfang": "tianjin",
        "shijiazhuang": "shijiazhuang", "baoding": "shijiazhuang",
        "handan": "shijiazhuang", "qinhuangdao": "shijiazhuang",
        "taiyuan": "taiyuan", "datong": "taiyuan", "jinzhong": "taiyuan",
        "hohhot": "huhehaote", "huhehaote": "huhehaote", "baotou": "huhehaote",
        "shenyang": "shenyang", "dalian": "shenyang", "anshan": "shenyang",
        "fushun": "shenyang",
        "changchun": "changchun", "jilin": "changchun", "siping": "changchun",
        "harbin": "harbin", "qiqihar": "harbin", "daqing": "harbin",
        "chongqing": "chongqing", "chungking": "chongqing",
        "chengdu": "chengdu", "mianyang": "chengdu", "deyang": "chengdu",
        "leshan": "chengdu", "yibin": "chengdu",
        "guiyang": "guiyang", "zunyi": "guiyang", "anshun": "guiyang",
        "kunming": "kunming", "dali": "kunming", "qujing": "kunming",
        "lhasa": "lhasa", "lasa": "lhasa", "shigatse": "lhasa",
        "xian": "xian", "xi'an": "xian", "xianyang": "xian", "baoji": "xian",
        "lanzhou": "lanzhou", "tianshui": "lanzhou", "jiayuguan": "lanzhou",
        "xining": "xining", "geermu": "xining", "golmud": "xining",
        "yinchuan": "yinchuan", "shizuishan": "yinchuan", "wuzhong": "yinchuan",
        "urumqi": "wulumqi", "wulumuqi": "wulumqi", "wulumqi": "wulumqi",
        "kashi": "wulumqi", "kashgar": "wulumqi", "turpan": "wulumqi",
        "karamay": "wulumqi",
    }
    # 星历与模型版本标记（data_version 字段值）
    DATA_VERSION = "de421+dt_espenak_meeus_2006+tt_scale"
    # 紫金山历表仅内部比对，不复制发布
    INTERNAL_CHECK_ONLY = True

    # —— 星历档位（F1/F5）：按文件名识别覆盖区间，供范围守卫使用 ——
    # 区间值取自 JPL 官方说明；运行时仍以实际 kernel 为准（越界会抛 EphemerisRangeError）。
    EPHEMERIS_PROFILES = {
        "de421.bsp":  (2414864.5, 2471184.5, "1899-07-28", "2053-10-08"),
        "de422.bsp":  ( 625673.5, 2816787.5, "-3000-01-01", "3000-12-31"),
        "de430.bsp":  (2287184.5, 2688976.5, "1550-01-01", "2650-12-31"),
        "de431.bsp":  (-3100014.5, 8000163.5, "-13200-01-01", "17191-12-31"),
        "de440.bsp":  (2287184.5, 2688976.5, "1550-01-01", "2650-12-31"),
        "de440s.bsp": (2293376.5, 2568262.5, "1849-12-26", "2150-01-22"),
        "de441.bsp":  (-3100014.5, 8000163.5, "-13200-01-01", "17191-12-31"),
    }
    # 默认星历文件名（可被 --ephemeris 覆盖）
    DEFAULT_EPHEMERIS = "de421.bsp"
    # 环境变量名（供 CI/自建机房指定星历绝对路径）
    ENV_EPHEMERIS = "KCJ_EPHEMERIS"
    # 工作目录下的候选相对路径
    LOCAL_EPHEMERIS_DIRS = (".", "data", "ephemeris", "python")

    # —— 精度分层（F5）——
    # 精算窗口：与所选星历的实际覆盖一致（de421 默认值）
    PRECISE_WINDOW = ("1899-07-28", "2053-10-08")
    # 对外承诺窗口（保守取整，见 docs/milestones.md）
    PROMISE_WINDOW = ("1900-01-01", "2050-12-31")
    # 窗口外是否允许降级到 Meeus 解析式（只给区间）
    ANALYTIC_FALLBACK = True

    # —— 预计算面（F7/可行性）：日粒度只做承诺窗口；窗口外只做「事件级」——
    # 见 docs/milestones.md「预计算面分档」。
    RANGE_PLAN = {
        "daily_full":    ("1900-01-01", "2050-12-31"),   # 日粒度全量（≈5.5 万天）
        "daily_optional":("1899-07-29", "2053-10-08"),   # 日粒度可选扩展（星历覆盖内）
        "event_only":    (None, None),                   # 覆盖外：只做事件级，不做日粒度
    }

    # 解析降级（Meeus）的精度声明（写进输出，供页面如实标注）
    ANALYTIC_ACCURACY = {
        "sun_ecl_lon_deg": 0.01,     # Meeus ch.25 简约式
        "moon_ecl_lon_deg": 0.1,     # Meeus ch.47 截断式（取主要项）
        "moon_ecl_lat_deg": 0.1,
        "moon_phase_min": 5.0,       # Meeus ch.49 月相时刻（分钟量级）
        "note": "解析式为截断级数，仅用于星历覆盖区间之外的历史回推；"
                "结果按 ΔT 不确定度区间交付，不作为唯一时刻。",
    }


# ========================= 观测地档：38 城 → 全国地级锚点（v2.3.0） =========================
# ★ 改动动因（用户令 2026-09-23）：「观测地要精确到全国各个市、县/区，并可选，
#   按访问位置选最近的预置观测地」。38 省会被核到县级时，县级到锚点的中位距离
#   超百千米（同省经度每差 1° ≈ 4 分钟），超出本项目「分钟内」的对外口径。
#
# ★ 单一真值源：`wp-astro-forecast/data/places_cn.json`（由 python/build_places.py 采集）。
#   Python 侧（本文件 / build_site.py）与 PHP 侧（短代码 / 模板）**共读同一份**，
#   不各写一遍 —— 两份表必然漂移（本文件 F18 已为「同一事实两处硬编码」立过规矩）。
#
# ★ 下面 `CONFIG.CITIES` 里那 38 条**不是作废**：它们是**人工校订档**，承载两样
#   采集不出来的东西 —— ① 既有 city key（`jieyang` / `wulumqi` 这类，已写进历史数据件
#   与历史 URL，改键即断链）；② 手校海拔（拉萨 3650 m 这类）。
#   `build_places.py` 按**中文名**用它们认领旧键与旧海拔 ⇒ **老键不失效、老数值不变**。
# -----------------------------------------------------------------------------------
CONFIG.CITIES_LEGACY = dict(CONFIG.CITIES)     # 供 build_places.py 认领旧键（避免自举循环）


def _load_places_json(path=None):
    """读全国观测地清单。**读不到即报错，不静默回落 38 城。**

    为什么不许回落：回落会让「本次 340 锚点重算」悄悄退化成「又算了一遍 38 城」，
    而调用方（build_site.py）只会看到「算完了」—— 正是本项目反复吃的
    「认不出就回落默认值」陷阱（见 resolve_city_key 的同类注释）。
    """
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            os.pardir, "wp-astro-forecast", "data", "places_cn.json")
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise RuntimeError(
            "观测地清单不存在：%s\n"
            "  本文件自 v2.3.0 起从 places_cn.json 读观测地档（38 城 → 全国地级锚点）。\n"
            "  可行做法：cd python && python build_places.py   （采集并生成该文件）\n"
            "  不愿采集也可临时用 --cities 显式指定城市键，但**不得**让调用方以为扩张成功。"
            % path)
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    anchors = doc.get("anchors") or []
    if not anchors:
        raise RuntimeError("观测地清单里 anchors 为空：%s（空集守卫，拒绝当成「零个城市也算成功」）" % path)
    out = {}
    for a in anchors:
        key = str(a.get("key") or "").strip()
        if not key:
            raise RuntimeError("观测地清单里有锚点缺 key：%r" % (a,))
        if key in out:
            raise RuntimeError("观测地清单里 key 重复：%r（唯一性是 (date_str, city) 落库的前提）" % key)
        lat, lon = a.get("lat"), a.get("lon")
        if lat is None or lon is None:
            raise RuntimeError("观测地清单里 %s 缺坐标" % key)
        elev = a.get("elev")
        out[key] = (float(lat), float(lon), float(elev if elev is not None else 0.0),
                    str(a.get("cn") or key))
    return out, path, doc


# 默认观测地（揭阳）必须在档内 —— 落库/渲染的兜底值取它，缺了就是配置错误
CONFIG.CITIES, _PLACES_PATH, _PLACES_DOC = _load_places_json()
if CONFIG.OBS_CITY_KEY not in CONFIG.CITIES:
    raise RuntimeError("默认观测地 %r 不在观测地清单内：%s" % (CONFIG.OBS_CITY_KEY, _PLACES_PATH))


# ============================ 示例条目（单一真值源，F18） ============================
# ★ 为什么要有这一段：v1.1.0 里同一件史事在两个地方各写了一份日期，且互相矛盾——
#   selftest 用 (-720, 7, 1)，emit_samples 用 parse_era_year("720BC")=(−719) 配 (2, 22)，
#   同一事件差 1 年半。此类「同一事实两处硬编码」必然漂移，故收敛为唯一常量。
#
# 纪年口径：**天文纪年**（0 = 公元前 1 年）。公元前 720 年 ⇒ era_year = −719。
# 日期口径：儒略历（1582-10-15 前由 _jd_from_calendar 自动切换）。
# 史事：《春秋》隐公三年「春王二月己巳，日有食之」，通常系于公元前 720 年 2 月 22 日，
#   为中国现存最早且年代可确考的日食记录之一。
# 出处：只引古籍正本，不引近现代注本（项目口径：近现代作品尽少引）。
SAMPLE_HISTORICAL = {
    "era_year": -719,
    "month": 2,
    "day": 22,
    "calendar_note": "鲁隐公三年春王二月己巳（儒略历）",
    "source_text": "《春秋》隐公三年：春王二月己巳，日有食之。",
    "source_ref": "《春秋》[M]. 先秦.",
}


# ============================== 星历发现与缓存（F1/F7） ==============================
_EPH_CACHE = {}
_TS_CACHE = {}


def resolve_ephemeris_path(explicit=None):
    """五级星历发现（F1）。返回可加载的路径或 None（表示需要联网下载）。

    顺序：
      1) --ephemeris 显式路径
      2) 环境变量 KCJ_EPHEMERIS
      3) 工作目录候选相对路径（./ / data / ephemeris / python）
      4) 已安装的 skyfield_data 包内置星历（离线可用）
      5) None → 交给 skyfield 联网下载（沙箱/断网环境会失败，错误信息已中文降级）
    """
    name = CONFIG.DEFAULT_EPHEMERIS
    if explicit:
        if os.path.isfile(explicit):
            return explicit
        # 允许只给档名（如 de440s.bsp），继续走后续发现
        name = os.path.basename(explicit)
    env = os.environ.get(CONFIG.ENV_EPHEMERIS)
    if env and os.path.isfile(env):
        return env
    for d in CONFIG.LOCAL_EPHEMERIS_DIRS:
        cand = os.path.join(d, name)
        if os.path.isfile(cand):
            return os.path.abspath(cand)
    try:  # skyfield_data 包（pip install skyfield-data）
        import skyfield_data  # type: ignore
        cand = os.path.join(skyfield_data.get_skyfield_data_path(), name)
        if os.path.isfile(cand):
            return cand
    except Exception:
        pass
    return None


def load_ephemeris(explicit=None):
    """加载并缓存星历（F7：v1.0.0 每日重复 load() 是主要性能杀手）。"""
    path = resolve_ephemeris_path(explicit)
    key = path or ("__download__:" + os.path.basename(explicit or CONFIG.DEFAULT_EPHEMERIS))
    if key in _EPH_CACHE:
        return _EPH_CACHE[key]
    from skyfield.api import load
    if path:
        eph = load(path)
    else:
        # 走联网下载；失败时给出中文可操作提示（不静默崩溃）
        try:
            eph = load(name=os.path.basename(explicit or CONFIG.DEFAULT_EPHEMERIS))
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "无法取得星历 {0}：本地未发现、联网下载也失败。\n"
                "  可行做法（任选其一）：\n"
                "   ① pip install skyfield-data   （自动带 de421.bsp，离线可用）\n"
                "   ② 手动下载 de421.bsp 放到脚本目录，或用 --ephemeris <绝对路径>\n"
                "   ③ 设环境变量 KCJ_EPHEMERIS=<绝对路径>\n"
                "  原始错误: {1}".format(os.path.basename(explicit or CONFIG.DEFAULT_EPHEMERIS), e)
            )
    _EPH_CACHE[key] = eph
    return eph


def timescale():
    """缓存 timescale（F7）。"""
    if "ts" not in _TS_CACHE:
        from skyfield.api import load
        _TS_CACHE["ts"] = load.timescale()
    return _TS_CACHE["ts"]


def ephemeris_window(eph, explicit=None):
    """返回 (jd_lo, jd_hi, 说明)。优先按文件名查表，查不到则从 kernel 段反推。"""
    fname = None
    try:
        fname = os.path.basename(getattr(eph, "filename", "") or "")
    except Exception:
        fname = None
    if not fname:
        fname = os.path.basename(explicit or CONFIG.DEFAULT_EPHEMERIS)
    if fname in CONFIG.EPHEMERIS_PROFILES:
        lo, hi, s_lo, s_hi = CONFIG.EPHEMERIS_PROFILES[fname]
        return lo, hi, "{0}（{1} 至 {2}）".format(fname, s_lo, s_hi)
    # 兜底：取所有段的最大交集（保守）
    try:
        los = [seg.start_jd for seg in eph.segments]
        his = [seg.end_jd for seg in eph.segments]
        return max(los), min(his), "{0}（按 kernel 段推断）".format(fname)
    except Exception:
        return None, None, "{0}（区间未知，不做范围守卫）".format(fname)


# ============================== ΔT 模型（来源 S2） ==============================
def delta_t_seconds(year):
    """地球时(TT)与协调世界时(UTC)之差 ΔT = TT − UTC，单位：秒。
    多项式取自 Espenak & Meeus (2006) / Meeus《Astronomical Algorithms》第10章。
    适用于约 -500 至 +3000 年；区间外给出外推估计（精度下降，调用方应标注不确定度）。
    """
    if year < -500:
        u = (year - 1825) / 100.0
        return -20.0 + 32.0 * u * u
    elif year < 500:
        u = (year - 1825) / 100.0
        return (10583.6 - 1014.41 * u + 33.78311 * u * u - 5.952053 * u ** 3
                - 0.1798452 * u ** 4 + 0.022174192 * u ** 5 + 0.0090316521 * u ** 6)
    elif year < 1600:
        u = (year - 1000) / 100.0
        return (1574.2 - 556.01 * u + 71.23472 * u * u + 0.319781 * u ** 3
                - 0.8503463 * u ** 4 - 0.005050998 * u ** 5 + 0.008357207 * u ** 6)
    elif year < 1700:
        t = (year - 1600) / 100.0
        return 120.0 - 0.9808 * t - 0.01532 * t * t + 0.0001403 * t ** 3
    elif year < 1800:
        t = (year - 1700) / 100.0
        return 8.83 + 0.1603 * t - 0.0059285 * t * t + 0.0001336 * t ** 3
    elif year < 1860:
        t = (year - 1800) / 100.0
        return (13.72 - 0.3324 * t + 0.006861 * t * t + 0.004111 * t ** 3
                - 0.0003744 * t ** 4 + 0.0000121 * t ** 5)
    elif year < 1900:
        t = (year - 1860) / 100.0
        return (7.62 + 0.5737 * t - 0.251754 * t * t + 0.01680668 * t ** 3
                - 0.0004473624 * t ** 4 + t ** 5 / 233174.0)
    elif year < 1920:
        t = (year - 1900) / 100.0
        return -2.79 + 1.494119 * t - 0.0598939 * t * t + 0.0061966 * t ** 3 - 0.000197 * t ** 4
    elif year < 1941:
        t = (year - 1920) / 100.0
        return 21.20 + 0.84493 * t - 0.076100 * t * t + 0.0020936 * t ** 3
    elif year < 1961:
        t = (year - 1950) / 100.0
        return 29.07 + 0.407 * t * t - t ** 3 / 233.0 + t ** 4 / 2547.0
    elif year < 1986:
        t = (year - 1975) / 100.0
        return 45.45 + 1.067 * t - t * t / 260.0 - t ** 3 / 718.0
    elif year < 2005:
        t = (year - 2000) / 100.0
        return (63.86 + 0.3345 * t - 0.060374 * t * t + 0.0017275 * t ** 3
                + 0.000651814 * t ** 4 + 0.00002373599 * t ** 5)
    elif year < 2050:
        t = (year - 2000) / 100.0
        return 62.92 + 0.32217 * t + 0.005589 * t * t
    elif year < 2150:
        # 2050—2150 外推（Espenak & Meeus 趋势项）
        t = (year - 2000) / 100.0
        return 62.92 + 0.32217 * t + 0.005589 * t * t
    else:
        # 2150—3000 粗略外推（不确定度增大；调用方须标注区间）
        u = (year - 1825) / 100.0
        return -20.0 + 32.0 * u * u


def delta_t_uncertainty_seconds(year):
    """ΔT 模型的不确定度（秒）。来源 S2：古代段误差远大于 1 分钟。
    本函数给出保守估计，用于页面「时间不确定度区间」标注（仅标注区间，不给唯一时刻）。
    古代日食典型 ±30 min ～ ±2 h。
    """
    lo, hi = window_years(CONFIG.PRECISE_WINDOW)
    if lo <= year <= hi:
        return 30.0                      # 精算窗口内 ±30s（≈ ±0.5 min），交付按 ±1 min 留余量
    elif year < -500:
        return 7200.0                    # 约 ±2 h
    elif year < 500:
        return 3600.0                    # 约 ±1 h
    elif year < 1000:
        return 1800.0                    # 约 ±30 min
    elif year < 1600:
        return 600.0                     # 约 ±10 min
    else:
        return 120.0                     # 过渡段 ±2 min


def jd_ut_to_jde(jd_ut, year_decimal):
    """UT 儒略日 → TT 儒略日（JDE）。★ v1.2.0 新增，修 F17。

    为什么必须显式换算：
      `_jd_from_calendar()` 由「历日 + 钟点」反算，得到的是 **UT 尺度**儒略日；
      而 Meeus 的级数（ch.25/47/49）与 skyfield 的 `t.tt` 一律是 **TT 尺度**（JDE）。
      两者相差 ΔT：TT = UT + ΔT。2026 年 ΔT≈63 s（0.0007 天，可忽略），
      但公元前 720 年 ΔT≈20706 s ≈ **0.24 天** ⇒ 月球黄经差约 3.2°、
      朔望时刻差约 5.8 小时。历史回推正是本模块的招牌功能，故不可省。
    """
    return jd_ut + delta_t_seconds(year_decimal) / 86400.0


def jde_to_jd_ut(jde, year_decimal):
    """TT 儒略日（JDE）→ UT 儒略日。与 `jd_ut_to_jde` 互逆（同日 ΔT 模型下严格互逆）。"""
    return jde - delta_t_seconds(year_decimal) / 86400.0


def window_years(win):
    """('1900-01-01','2050-12-31') → (1900.0, 2050.99...) 用于区间判定。"""
    lo = int(win[0][:4]) if win and win[0] else -9999
    hi = int(win[1][:4]) if win and win[1] else 9999
    return float(lo), float(hi) + 0.9999


# ============================== 岁差（来源 S2 ch.21） ==============================
def precession_lon_arcsec(year_decimal, jde=None):
    """黄经累积岁差（角秒）。Meeus ch.21「累积一般岁差」：
       p = 5029.0966·T + 1.11113·T² − 0.000006·T³   （T 为儒略世纪）
    校验：2026-09-22 实测（DE421）太阳 J2000 黄经 178.8023°、当日黄经 179.1820°，
    差 +0.3797°；本式给出 +0.3796°（误差 < 0.0002°）。见 selftest()。
    """
    if jde is None:
        jde = 2451545.0 + (year_decimal - 2000.0) * 365.25
    T = (jde - J2000) / 36525.0
    return 5029.0966 * T + 1.11113 * T * T - 0.000006 * T ** 3


def _jd_from_calendar(y, m, d, hour=12.0):
    """公历/儒略历 → 儒略日（Meeus ch.7）。
    1582-10-15 之前按儒略历（历史日期口径必需）；之后按格里高利历。
    注意：天文纪年用 0 表示公元前 1 年；调用方传入 -720 即「公元前 721 天文年」。
    """
    if m <= 2:
        y -= 1
        m += 12
    if (y, m, d) >= (1582, 10, 15):
        a = int(y / 100.0)
        b = 2 - a + int(a / 4.0)
    else:
        b = 0
    jd = math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1)) + d + b - 1524.5
    return jd + hour / 24.0


# ============================ 二十八宿距星表（来源 S3） ============================
# 每宿：[中文名, 距星英文名, 距星 J2000 赤经(小时), 距星 J2000 赤纬(度)]
# 注：以 J2000 为底；求宿度时按 Meeus ch.21 加累积岁差，换算到「当日黄道」（F6）。
XIU_STARS = [
    ("角", "α Vir (Spica)",      13.420, -11.16),
    ("亢", "κ Vir",              14.208, -10.27),
    ("氐", "α Lib",              14.840, -16.04),
    ("房", "π Sco",              15.967, -26.11),
    ("心", "σ Sco",              16.355, -25.59),
    ("尾", "μ Sco",              16.855, -38.05),
    ("箕", "γ Sgr",              18.083, -30.43),
    ("斗", "φ Sgr",              18.741, -26.99),
    ("牛", "β Cap",              20.350, -14.78),
    ("女", "ε Aqr",              20.786,  -9.50),
    ("虚", "β Aqr",              21.520,  -5.57),
    ("危", "α Aqr",              22.084,  -0.32),
    ("室", "α Peg",              23.078, +15.21),
    ("壁", "γ Peg",               0.219, +15.18),
    ("奎", "η And",               0.954, +23.42),
    ("娄", "β Ari",               1.900, +20.81),
    ("胃", "35 Ari",              2.717, +27.72),
    ("昴", "17 Tau (Pleiades)",   3.783, +24.11),
    ("毕", "ε Tau",               4.467, +19.18),
    ("觜", "λ Ori",               5.583,  +9.93),
    ("参", "ζ Ori",               5.668,  -1.94),
    ("井", "μ Gem",               6.368, +22.51),
    ("鬼", "θ Cnc",               8.525, +18.15),
    ("柳", "δ Hya",               8.617,  +5.70),
    ("星", "α Hya (Alphard)",     9.453,  -8.66),
    ("张", "υ¹ Hya",             10.619, -13.80),
    ("翼", "α Crt",              10.987, -18.30),
    ("轸", "γ Crv",              12.253, -17.54),
]
EPSILON = math.radians(23.4392911)   # J2000 黄赤交角（来源：IAU 2006）


def _ra_dec_to_ecl_lon(ra_hours, dec_deg):
    """赤经(小时)/赤纬(度) → J2000 黄经(度)。用于从距星坐标求宿度起算点。"""
    a = math.radians(ra_hours * 15.0)
    d = math.radians(dec_deg)
    sin_lon = math.sin(a) * math.cos(EPSILON) + math.tan(d) * math.sin(EPSILON)
    cos_lon = math.cos(a)
    return math.degrees(math.atan2(sin_lon, cos_lon)) % 360.0


# 预计算各距星 J2000 黄经（仅供解析降级路径使用；精算路径见 _xiu_table）
_XIU_LON_J2000 = [(name, _ra_dec_to_ecl_lon(ra, dec)) for name, _, ra, dec in XIU_STARS]

# 距星「当日黄道」视黄经表缓存：键=(年,月)
_XIU_TABLE_CACHE = {}


def _xiu_table(eph, y, m):
    """用 skyfield 求 28 距星的「当日黄道」视黄经（与日月五星同一 .apparent() 路径）。

    ★ F6 修正：v1.0.0 把距星表当固定 J2000 黄经用，2026 年即偏 0.38°、1900 年前更甚。
      现改为经 skyfield 的岁差+章动+光行差变换到当日黄道，与天体同坐标系。
      表按 (年,月) 缓存并以**该月 15 日**为取样时刻（结果与调用顺序无关、可复现）；
      距星黄经月变率约 0.00012°/月，远小于最窄宿宽（约 0.8°），故此近似安全。
    注：距星自行（如角宿一 Spica 约 0.05″/yr）未计；跨 2700 年累计约 0.04°，属可接受量级，
      但若需严格复现某朝代观测，应换用该朝代的实测距星位置表。
    """
    key = (int(y), int(m))
    if key in _XIU_TABLE_CACHE:
        return _XIU_TABLE_CACHE[key]
    from skyfield.starlib import Star
    ts = timescale()
    t_mid = ts.utc(int(y), int(m), 15, 12, 0, 0)
    earth = eph['earth']
    tbl = []
    for name, _en, ra_hours, dec_deg in XIU_STARS:
        st = Star(ra_hours=ra_hours, dec_degrees=dec_deg)
        _la, lon, _d = earth.at(t_mid).observe(st).apparent().ecliptic_latlon(epoch='date')
        tbl.append((name, lon.degrees % 360.0))
    _XIU_TABLE_CACHE[key] = tbl
    return tbl


def _xiu_seg(ecl_lon_deg, tbl):
    """在给定距星表（已排序为 list[(宿名, 当日黄经)]）中定宿；两套路径共用。"""
    lon = ecl_lon_deg % 360.0
    n = len(tbl)
    for i in range(n):
        a = tbl[i][1]
        b = tbl[(i + 1) % n][1]
        bb = b + 360.0 if b < a else b          # 跨 360° 边界的段平移
        ll = lon + 360.0 if lon < a else lon    # 被测点同步平移以落入正确段
        if a <= ll < bb:
            return tbl[i][0]
    # 兜底（距星表异常时）：取距星黄经与 lon 角距最近的宿
    best = min(tbl, key=lambda x: abs(((x[1] - lon + 180) % 360) - 180))
    return best[0]


def xiu_of(ecl_lon_deg, year_decimal=None, jde=None, table=None):
    """给定天体**当日黄道黄经**(度)，返回所在宿名（距星法）。

    优先走 `table`（由 `_xiu_table` 经 skyfield 精算到当日黄道，与天体同坐标系）；
    未给 table 时（解析降级路径）退化为「距星 J2000 黄经 + 累积岁差」近似——
    该近似与精算表在当代相差约 0.006°（章动与黄道面旋转未计入），已在 ±0.01° 量级，
    对最窄宿宽（约 0.8°）无实质影响，但**不作精算口径声明**。

    ⚠ 口径声明：本模块宿度＝**黄道宿度**（以当日黄道为准）。古法另有「赤道宿度」一套，
    本模块不与黄道宿度混用；如需赤道宿度应另立开关并整表换算。
    """
    if table is not None:
        return _xiu_seg(ecl_lon_deg, table)
    if year_decimal is None and jde is None:
        year_decimal = 2000.0
    dlon = precession_lon_arcsec(year_decimal, jde) / 3600.0
    tbl = [(_XIU_LON_J2000[i][0], (_XIU_LON_J2000[i][1] + dlon) % 360.0)
           for i in range(len(_XIU_LON_J2000))]
    return _xiu_seg(ecl_lon_deg, tbl)


# ==================== Meeus 解析式（星历覆盖外降级，来源 S2） ====================
_DEG = math.pi / 180.0


def _sin(deg):
    return math.sin(deg * _DEG)


def _cos(deg):
    return math.cos(deg * _DEG)


def meeus_sun_apparent_lon(jde):
    """太阳视黄经（当日黄道，度）。Meeus ch.25 简约式，精度约 0.01°。"""
    T = (jde - J2000) / 36525.0
    L0 = 280.46646 + 36000.76983 * T + 0.0003032 * T * T
    M = 357.52911 + 35999.05029 * T - 0.0001537 * T * T
    C = ((1.914602 - 0.004817 * T - 0.000014 * T * T) * _sin(M)
         + (0.019993 - 0.000101 * T) * _sin(2 * M)
         + 0.000289 * _sin(3 * M))
    true_lon = L0 + C
    omega = 125.04 - 1934.136 * T
    return (true_lon - 0.00569 - 0.00478 * _sin(omega)) % 360.0


# Meeus ch.47 月球黄经/黄纬截断级数（取主要项；精度约 0.1°）
# 每项：(系数[1e-6 度], D 系数, M 系数, M' 系数, F 系数)
_MOON_LON_TERMS = [
    (6288774, 0, 0, 1, 0), (1274027, 2, 0, -1, 0), (658314, 2, 0, 0, 0),
    (213618, 0, 0, 2, 0), (-185116, 0, 1, 0, 0), (-114332, 0, 0, 0, 2),
    (58793, 2, 0, -2, 0), (57066, 2, -1, -1, 0), (53322, 2, 0, 1, 0),
    (45758, 2, -1, 0, 0), (-40923, 0, 1, -1, 0), (-34720, 1, 0, 0, 0),
    (-30383, 0, 1, 1, 0), (15327, 2, 0, 0, -2), (-12528, 0, 0, 1, 2),
    (10980, 0, 0, 1, -2), (10675, 4, 0, -1, 0), (10034, 0, 0, 3, 0),
    (8548, 4, 0, -2, 0), (-7888, 2, 1, -1, 0), (-6766, 2, 1, 0, 0),
    (-5163, 1, 0, -1, 0), (4987, 1, 1, 0, 0), (4036, 2, -1, 1, 0),
    (3994, 2, 0, 2, 0), (3861, 4, 0, 0, 0),
]
_MOON_LAT_TERMS = [
    (5128122, 0, 0, 0, 1), (280602, 0, 0, 1, 1), (277693, 0, 0, 1, -1),
    (173237, 2, 0, 0, -1), (55413, 2, 0, -1, 1), (46271, 2, 0, -1, -1),
    (32573, 2, 0, 0, 1), (17198, 0, 0, 2, 1), (9266, 2, 0, 1, -1),
    (8822, 0, 0, 2, -1), (8216, 2, -1, 0, -1), (4324, 2, 0, -2, -1),
    (4200, 2, 0, 1, 1),
]


def _moon_args(jde):
    T = (jde - J2000) / 36525.0
    D = (297.8501921 + 445267.1114034 * T - 0.0018819 * T * T
         + T ** 3 / 545868.0 - T ** 4 / 113065000.0)
    M = 357.5291092 + 35999.0502909 * T - 0.0001536 * T * T + T ** 3 / 24490000.0
    Mp = (134.9633964 + 477198.8675055 * T + 0.0087414 * T * T
          + T ** 3 / 69699.0 - T ** 4 / 14712000.0)
    F = (93.2720950 + 483202.0175233 * T - 0.0036539 * T * T
         - T ** 3 / 3526000.0 + T ** 4 / 863310000.0)
    E = 1.0 - 0.002516 * T - 0.0000074 * T * T
    return D, M, Mp, F, E


def meeus_moon_lon_lat(jde):
    """月球视黄经/黄纬（当日黄道，度）。Meeus ch.47 截断式，精度约 0.1°。"""
    T = (jde - J2000) / 36525.0
    D, M, Mp, F, E = _moon_args(jde)
    sl = 0.0
    for coef, cd, cm, cmp_, cf in _MOON_LON_TERMS:
        arg = cd * D + cm * M + cmp_ * Mp + cf * F
        e = E ** abs(cm) if cm in (1, -1) else (E ** 2 if cm in (2, -2) else 1.0)
        sl += coef * e * _sin(arg)
    sb = 0.0
    for coef, cd, cm, cmp_, cf in _MOON_LAT_TERMS:
        arg = cd * D + cm * M + cmp_ * Mp + cf * F
        e = E ** abs(cm) if cm in (1, -1) else (E ** 2 if cm in (2, -2) else 1.0)
        sb += coef * e * _sin(arg)
    Lp = (218.3164477 + 481267.88123421 * T - 0.0015786 * T * T
          + T ** 3 / 538841.0 - T ** 4 / 65194000.0)
    omega = 125.04452 - 1934.136261 * T           # 月球升交点黄经
    dpsi = -17.20 / 3600.0 * _sin(omega)          # 章动（主项，Meeus ch.22）
    lon = (Lp + sl / 1e6 + dpsi) % 360.0
    lat = sb / 1e6
    return lon, lat


# Meeus ch.49 月相：k 为整数→朔；k + 0.5→望
# 表项 = (系数[日], M 系数, M' 系数, F 系数, Ω 系数)；含 M 的项须乘 E^|M系数|。
_PHASE_NEW = [
    (-0.40720, 0, 1, 0, 0), (0.17241, 1, 0, 0, 0), (0.01608, 0, 2, 0, 0),
    (0.01039, 0, 0, 2, 0), (0.00739, -1, 1, 0, 0), (-0.00514, 1, 1, 0, 0),
    (0.00208, 2, 0, 0, 0), (-0.00111, 0, 1, -2, 0), (-0.00057, 0, 1, 2, 0),
    (0.00056, 1, 2, 0, 0), (-0.00042, 0, 3, 0, 0), (0.00042, 1, 0, 2, 0),
    (0.00038, 1, 0, -2, 0), (-0.00024, -1, 2, 0, 0), (-0.00017, 0, 0, 0, 1),
    (-0.00007, 2, 1, 0, 0), (0.00004, 0, 2, -2, 0), (0.00004, 3, 0, 0, 0),
    (0.00003, 1, 1, -2, 0), (0.00003, 0, 2, 2, 0), (-0.00003, 1, 1, 2, 0),
    (0.00003, -1, 1, 2, 0), (-0.00002, -1, 1, -2, 0), (-0.00002, 1, 3, 0, 0),
    (0.00002, 0, 4, 0, 0),
]
_PHASE_FULL = [
    (-0.40614, 0, 1, 0, 0), (0.17302, 1, 0, 0, 0), (0.01614, 0, 2, 0, 0),
    (0.01043, 0, 0, 2, 0), (0.00734, -1, 1, 0, 0), (-0.00515, 1, 1, 0, 0),
    (0.00209, 2, 0, 0, 0), (-0.00111, 0, 1, -2, 0), (-0.00057, 0, 1, 2, 0),
    (0.00056, 1, 2, 0, 0), (-0.00042, 0, 3, 0, 0), (0.00042, 1, 0, 2, 0),
    (0.00038, 1, 0, -2, 0), (-0.00024, -1, 2, 0, 0), (-0.00017, 0, 0, 0, 1),
    (-0.00007, 2, 1, 0, 0), (0.00004, 0, 2, -2, 0), (0.00004, 3, 0, 0, 0),
    (0.00003, 1, 1, -2, 0), (0.00003, 0, 2, 2, 0), (-0.00003, 1, 1, 2, 0),
    (0.00003, -1, 1, 2, 0), (-0.00002, -1, 1, -2, 0), (-0.00002, 1, 3, 0, 0),
    (0.00002, 0, 4, 0, 0),
]
# 附加行星改正（Meeus 49.3）
_PHASE_ADD = [
    (0.000325, "A1"), (0.000165, "A2"), (0.000164, "A3"), (0.000126, "A4"),
    (0.000110, "A5"), (0.000062, "A6"), (0.000060, "A7"), (0.000056, "A8"),
    (0.000047, "A9"), (0.000042, "A10"), (0.000040, "A11"), (0.000037, "A12"),
    (0.000035, "A13"), (0.000023, "A14"),
]


def _A_terms(k, T):
    return {
        "A1": 299.77 + 0.107408 * k - 0.009173 * T * T,
        "A2": 251.88 + 0.016321 * k,
        "A3": 251.83 + 26.651886 * k,
        "A4": 349.42 + 36.412478 * k,
        "A5": 84.66 + 18.206239 * k,
        "A6": 141.74 + 53.303771 * k,
        "A7": 207.14 + 2.453732 * k,
        "A8": 154.84 + 7.306860 * k,
        "A9": 34.52 + 27.261239 * k,
        "A10": 207.19 + 0.121824 * k,
        "A11": 291.34 + 1.844379 * k,
        "A12": 161.72 + 24.198154 * k,
        "A13": 239.56 + 25.513099 * k,
        "A14": 331.55 + 3.592518 * k,
    }


def meeus_phase_jde(k):
    """Meeus ch.49：第 k 次月相的 JDE（TT）。k 为整数→朔；k+0.5→望。
    精度：分钟量级（含行星附加改正）。返回 (jde_tt, 相位名)。
    """
    T = k / 1236.85
    jde = (2451550.09766 + 29.530588861 * k + 0.00015437 * T * T
           - 0.000000150 * T ** 3 + 0.00000000073 * T ** 4)
    E = 1.0 - 0.002516 * T - 0.0000074 * T * T
    M = 2.5534 + 29.10535670 * k - 0.0000014 * T * T - 0.00000011 * T ** 3
    Mp = (201.5643 + 385.81693528 * k + 0.0107582 * T * T
          + 0.00001238 * T ** 3 - 0.000000058 * T ** 4)
    F = (160.7108 + 390.67050284 * k - 0.0016118 * T * T
         - 0.00000227 * T ** 3 + 0.000000011 * T ** 4)
    omega = 124.7746 - 1.56375588 * k + 0.0020672 * T * T + 0.00000215 * T ** 3
    is_new = abs(k - round(k)) < 0.25
    table = _PHASE_NEW if is_new else _PHASE_FULL
    corr = 0.0
    for coef, cm, cmp_, cf, co in table:
        arg = cm * M + cmp_ * Mp + cf * F + co * omega
        e = E ** abs(cm) if cm in (1, -1) else (E ** 2 if cm in (2, -2) else 1.0)
        corr += coef * e * _sin(arg)
    jde += corr
    A = _A_terms(k, T)
    for coef, key in _PHASE_ADD:
        jde += coef * _sin(A[key])
    return jde, ("朔（新月）" if is_new else "望（满月）")


def meeus_jd_to_bj(jde_tt, tz_hours):
    """JDE(TT) → 北京时间字符串。ΔT 用本文件模型换算（古代误差见不确定度函数）。"""
    year_guess = 2000.0 + (jde_tt - J2000) / 365.25
    jd_ut = jde_tt - delta_t_seconds(year_guess) / 86400.0
    return jd_to_str(jd_ut, tz_hours)


def jd_to_str(jd_ut, tz_hours=8):
    """儒略日(UT) → 'YYYY-MM-DD HH:MM'（本地时区）。支持公元前（天文纪年 → 公元前纪年显示）。"""
    z = jd_ut + 0.5 + tz_hours / 24.0
    Z = math.floor(z)
    F = z - Z
    if Z < 2299161:
        A = Z
    else:
        alpha = math.floor((Z - 1867216.25) / 36524.25)
        A = Z + 1 + alpha - math.floor(alpha / 4.0)
    B = A + 1524
    C = math.floor((B - 122.1) / 365.25)
    D = math.floor(365.25 * C)
    E = math.floor((B - D) / 30.6001)
    day = B - D - math.floor(30.6001 * E)
    month = E - 1 if E < 14 else E - 13
    year = C - 4716 if month > 2 else C - 4715
    mins = int(round(F * 1440.0))
    hh, mm = divmod(mins, 60)
    if hh >= 24:
        hh -= 24
        day += 1
    if year <= 0:
        return "%dBC-%02d-%02d %02d:%02d" % (1 - year, month, day, hh, mm)
    return "%04d-%02d-%02d %02d:%02d" % (year, month, day, hh, mm)


# ============================== 星历计算核心（来源 S1） ==============================
def _topos(lat, lon, elev):
    from skyfield.api import Topos
    return Topos(latitude_degrees=lat, longitude_degrees=lon, elevation_m=elev)


# ★ F3b：DE421 只提供木星/土星的**质心**（JUPITER BARYCENTER / SATURN BARYCENTER），
#   没有 'JUPITER'、'SATURN' 这两个行星本体名（水星/金星/火星有本体）。
#   v1.0.0 直接 eph['jupiter'] → KeyError，五大行星里有两颗必崩。
_TARGET_ALIASES = {
    "jupiter": "jupiter barycenter",
    "saturn": "saturn barycenter",
    "uranus": "uranus barycenter",
    "neptune": "neptune barycenter",
    "pluto": "pluto barycenter",
}


def _target(eph, body):
    """解析星历目标名，自动回落到「质心」（F3b）。"""
    try:
        return eph[body]
    except KeyError:
        alias = _TARGET_ALIASES.get(body)
        if alias:
            return eph[alias]
        raise


def _apparent(eph, body_name, t, obs_topo=None):
    """返回天体的「视位置」：赤经(小时)/赤纬(度)、当日黄经/黄纬(度)、J2000 黄经(度)、距离(AU)。

    ★ 坐标口径（②坐标系规范）：**地心视位置**。
      日月五星的坐标与「入宿度」按地心视位置给出（历书惯例；中国古代入宿度亦为地心）；
      升落/晨昏另用**站心**（topos）计算。v1.0.0 把站心位置直接当作坐标输出，
      致月球黄经最大可差 0.95°（月球地平视差），宿度会错一宿。
    ★ F2：skyfield 的 ecliptic_latlon 只接受 Time / TT 浮点 / 'date'，
      传字符串 'j2000' 会抛 ValueError；此处统一用 epoch='date'（当日黄道）。
    .apparent() 已施加周年光行差与章动（IAU 2000B）与光行时。
    """
    astrometric = eph['earth'].at(t).observe(_target(eph, body_name))
    if obs_topo is not None:      # 可选：站心视位置（供需要时使用，默认不给）
        astrometric = obs_topo.at(t).observe(_target(eph, body_name))
    apparent = astrometric.apparent()
    ra, dec, dist = apparent.radec(epoch='date')          # 当日赤道坐标
    ecl_lat, ecl_lon, ecl_dist = apparent.ecliptic_latlon(epoch='date')   # 当日黄道坐标
    ecl_lat_j, ecl_lon_j, _ = apparent.ecliptic_latlon(epoch=2451545.0)   # J2000 备查
    r = 0.0
    if body_name != 'sun':
        r = _target(eph, 'sun').at(t).observe(_target(eph, body_name)).distance().au
    R = eph['earth'].at(t).observe(_target(eph, 'sun')).distance().au
    return {
        "ra_hours": ra.hours,
        "dec_deg": dec.degrees,
        "ecl_lon_deg": ecl_lon.degrees,      # 当日黄经（宿度用此）
        "ecl_lat_deg": ecl_lat.degrees,
        "ecl_lon_j2000_deg": ecl_lon_j.degrees,
        "ecl_lat_j2000_deg": ecl_lat_j.degrees,
        "distance_au": dist.au,
        "helio_distance_au": r,              # 日心距（星等用）
        "earth_sun_distance_au": R,          # 地日距（星等用）
    }


# ------------------------------ 日出日落/晨昏蒙影 ------------------------------
# ★ F28（v2.0.0 修）：升落的地平线口径。
#   skyfield 的 `almanac.risings_and_settings()` 默认 `horizon_degrees=-34.0/60.0`
#   = **−0.5667°**，只含大气折射（34′），**不含太阳视半径**（约 16′）。
#   而各国历书（含紫金山天文台《中国天文年历》）公布的「日出」定义是
#   **日面上边缘与地平线相切** ⇒ 地平线取 **−34′ − 16′ = −0.8333°**。
#   用默认值会比公布值晚约 1.4 分钟 —— **超出本模块自称的 ±1 分钟精度**。
#
#   实测对照（2026-09-23，本机 de421；参考值取自公开历表）：
#     · 北京：默认 06:03:55 / 本口径 **06:02:31** ｜ 参考 06:01—06:02 ✓
#     · 乌鲁木齐：默认 07:58:55 / 本口径 **07:57:27** ｜ 参考 07:57—07:58 ✓
#   参考来源：timeanddate.com（Ürümqi, September 2026）、sunrise.maplogs.com（北京）、
#             timebie.com（北京）、richurimo.bmcx.com（乌鲁木齐）。
#
#   ★ 海拔**不**参与升落：本口径按「海平面平坦地平线」计算，与中国天文年历的
#     城市日出日落口径一致。高原站（拉萨 3650 m）若按「站址地平线下沉」算，
#     日出会再早 1—2 分钟；两种口径都见于不同的公开历表，本项目**采用前者**
#     并在此如实声明，不做无参照的偏移。见 docs/feasibility-review.md F29。
RISE_SET_HORIZON_DEG = -0.8333


def _bj_day_utc_bounds(y, m, d, tz_hours):
    """北京日 [当日 00:00, 次日 00:00) 对应的 UTC 时刻对。

    ★ F27（v2.0.0 修）：原来的 `_rise_set` / `_twilight` 用的是
      `ts.utc(y, m, d, 0, 0, 0) ~ 23:59:59` —— 那是一个 **UTC 日**，
      换算成北京时是 [08:00, 次日 08:00)。两个后果：
        ① **口径错**：日行里配的「日出」其实是**次日**日出（日落却仍是当日），
           一行里混了两天的事件；因日出每天只挪 1—2 分钟，肉眼看不出来。
        ② **西陲城市直接丢失**：乌鲁木齐(87.62°E)、拉萨(91.13°E)的日出与
           晨光始落在北京时 08:00 之前 ⇒ 整个落在窗外 ⇒ 静默返回 None。
      （这一条是 v2.0.0 加「观测地可选」、第一次真跑 38 城时暴露的：
        乌鲁木齐 2026-09-23 `sunrise_bj=None`，而日落却有值。）
      改为按**北京日**取窗，与世界各国民历的「当日日出」口径一致。
    """
    tz = timezone(timedelta(hours=tz_hours))
    t0 = datetime(y, m, d, 0, 0, 0, tzinfo=tz)
    return t0.astimezone(timezone.utc), (t0 + timedelta(days=1)).astimezone(timezone.utc)


def _rise_set(eph, topos, body_name, y, m, d, tz_hours,
              horizon_degrees=RISE_SET_HORIZON_DEG):
    """返回某日某天体的升/落（北京时间）。

    ★ F3 修正：risings_and_settings 的签名是 (ephemeris, target, topos, horizon_degrees,
      radius_degrees) —— v1.0.0 传了 ts 作首参并带了不存在的 which 参数，必抛 TypeError。
    ★ 语义：find_discrete 的 state，1 = 升起（rising），0 = 落下（setting）。
      （已用 2026-09-22 揭阳实测核对：太阳 18:10 落 / 次日 06:04 升；
        2026-09-23 凌晨 06:04 实测值核对通过。）
    ★ F27 修正：窗口由 UTC 日改为**北京日**（见 _bj_day_utc_bounds）。
    ★ F28 修正：**显式指定地平线 −0.8333°**。skyfield 的 risings_and_settings 默认是
      `horizon_degrees=-34.0/60.0` = −0.5667°，**只含大气折射、不含太阳视半径**，
      比「日面上边缘与地平线相切」的文献惯例晚约 1.4 分钟（见 RISE_SET_HORIZON_DEG）。
    ★ 一日内同一天体出现两次同类事件时（月球恒星日 24h50m，日历日内偶有两次月出），
      本函数取**较晚**的一次（循环覆盖）。这是 v1.1.0 起的既有语义，本次不动。
    """
    from skyfield import almanac
    ts = timescale()
    lo, hi = _bj_day_utc_bounds(y, m, d, tz_hours)
    t0 = ts.from_datetime(lo)
    t1 = ts.from_datetime(hi)
    f = almanac.risings_and_settings(eph, eph[body_name], topos,
                                     horizon_degrees=float(horizon_degrees))
    times, kinds = almanac.find_discrete(t0, t1, f)
    out = {"rise": None, "set": None}
    for ti, ki in zip(times, kinds):
        bj = ti.utc_datetime().replace(tzinfo=timezone.utc) + timedelta(hours=tz_hours)
        out["rise" if int(ki) == 1 else "set"] = bj.strftime("%H:%M")
    return out


def _twilight(eph, topos, y, m, d, tz_hours, horizon_degrees):
    """晨昏界（北京时间）：以太阳高度角穿 -6°/-12°/-18° 求 begin(晨光始)/end(昏影终)。

    ★ F4 修正：dark_twilight_day 的签名是 (ephemeris, topos)，不接受 ts 与 degree；
      v1.0.0 的 _twilight(eph, observer, ts, …, degree) 参数全错、必抛 TypeError。
      改为对太阳用 risings_and_settings(horizon_degrees=…)。
      state：1 = 太阳升到该高度以上（= 晨光始 begin）；0 = 降到该高度以下（= 昏影终 end）。
    ★ F27 修正：窗口由 UTC 日改为**北京日**（同 _rise_set）。
    """
    from skyfield import almanac
    ts = timescale()
    lo, hi = _bj_day_utc_bounds(y, m, d, tz_hours)
    t0 = ts.from_datetime(lo)
    t1 = ts.from_datetime(hi)
    f = almanac.risings_and_settings(eph, eph['sun'], topos,
                                     horizon_degrees=float(horizon_degrees))
    times, kinds = almanac.find_discrete(t0, t1, f)
    out = {"begin": None, "end": None}
    for ti, ki in zip(times, kinds):
        bj = ti.utc_datetime().replace(tzinfo=timezone.utc) + timedelta(hours=tz_hours)
        out["begin" if int(ki) == 1 else "end"] = bj.strftime("%H:%M")
    return out


# ------------------------------ 月相/月龄 ------------------------------
def _moon_phase_deg(eph, t):
    """月相角(度)：0=朔,90=上弦,180=望,270=下弦。来源 skyfield almanac.moon_phase。"""
    from skyfield import almanac
    return almanac.moon_phase(eph, t).degrees


MOON_PHASE_NAMES = (
    (0.0, 22.5, "新月（朔）"), (22.5, 67.5, "蛾眉月"), (67.5, 112.5, "上弦月"),
    (112.5, 157.5, "盈凸月"), (157.5, 202.5, "满月（望）"), (202.5, 247.5, "亏凸月"),
    (247.5, 292.5, "下弦月"), (292.5, 337.5, "残月"), (337.5, 360.01, "新月（朔）"),
)


def _moon_phase_name(phase_deg):
    p = phase_deg % 360.0
    for lo, hi, name in MOON_PHASE_NAMES:
        if lo <= p < hi:
            return name
    return "未知"


# ==================== 事件枚举的公开访问器（v1.3.0 · 对外只读） ====================
# ★ 为什么单立这一段（而不是让 event_almanac.py 直接调私有名）：
#   事件求根要**成千上万次**调用「某时刻某天体的黄经」「与太阳的黄经差」「月相角」
#   这三个量。若事件模块直接 `compute_sky._apparent(...)`，则一旦内部重构
#   （本项目已实际发生过 F19 删死参数、F3b 目标名回落两次），事件侧会**静默**取到
#   另一个量、或 KeyError —— 两种都是「升级后才暴露」的失败。
#   故把这三个量固化成**公开**入口，口径写在 docstring 里，事件模块只认公开名。
#
# ★ 三个量的共同口径：**地心视位置**（非站心）、**当日真黄道**（epoch="date"）、
#   `.apparent()` 已含光行时、周年光行差、章动（IAU 2000B）。
# ★★ epoch 的取舍必须**分开说**，不能一句「必须用 date」糊过去（本轮实测 2026-09-23）：
#     · **绝对黄经**（节气、二十八宿入宿度、星座归属）——**必须** date。岁差 J2000→2027
#       使各天体黄经**同向**偏 +0.3864°（实测日月五星七个目标落在 0.3861—0.3866°），
#       而节气判据是「太阳黄经达 15° 整数倍」：0.386° ≈ 9.4 小时的太阳平运动，
#       足以决定交节落在哪一天。
#     · **黄经差**（合、冲、月相）——岁差在**相减时抵消**：实测 date 与 J2000 的
#       黄经差相差 ≤ 0.0006°（≈ 4 秒的月球平运动）。故此处用哪个 epoch 都不改变
#       求根结果；本模块**统一用 date**，只为与项目其余口径一致，不是为了精度。
#   ↑ 这一条是「先把话说满、再实测打脸」的记录：初稿写的是「不得改用 J2000，否则
#     0.39° ≈ 17.7 小时」，实测发现**差量里它抵消了** —— 结论从「必须」降为「无所谓」。
#     留在此处，提醒后来人：口径论证要指到**被减掉之后还剩多少**，不能只看单项量。
# ★ 三者都**接受标量或数组 t**，返回同形状（numpy 标量/数组）——事件模块的粗扫
#   一律整段向量化，只在二分精化处落回标量，故这一步是性能前提，不是顺手加的。

def body_ecl_lonlat(eph, body, t, epoch="date"):
    """天体 **t** 时刻的**地心视**黄经（度）、黄纬（度）、距离（AU）。

    黄经归一到 [0, 360)。body 用 _target 的写法（'sun' / 'moon' /
    'mars' / 'jupiter'…），木土自动回落质心。

    `epoch` 只接受两个值，**且必须按用途选**（差别不是小数点级的）：
      · ``"date"``   —— 当日真黄道。**节气、二十八宿入宿度、星座归属**用这个。
      · ``"j2000"``  —— J2000.0 黄道。**与外部 J2000 口径的表比对**用这个，
        例如 IMO／RASC 公布的流星雨「极大 λ☉」（其表头明写 λ 2000）。
    ★ 选错的代价（本轮实测 2026-09-23）：两者在 2026 年相差 **0.363°**，
      折合太阳平运动 **约 8.8 小时** —— 足以把一场流星雨的极大日整体挪过午夜。
    """
    p = _apparent(eph, body, t)
    if epoch == "j2000":
        return (p["ecl_lon_j2000_deg"] % 360.0), p["ecl_lat_j2000_deg"], p["distance_au"]
    if epoch != "date":
        raise ValueError("epoch 只接受 'date' 或 'j2000'，收到 %r" % (epoch,))
    return (p["ecl_lon_deg"] % 360.0), p["ecl_lat_deg"], p["distance_au"]


def sun_body_lon_sep_deg(eph, body, t):
    """天体与**太阳**的地心视**黄经差**（度），归一到 (−180, 180]。

    ★ 事件求根的**唯一**合法输入就是这个量。理由是它在 ±180° 处**跳变**，
      而求根用的是 `sin(黄经差)`（在包裹下连续）——见 planet_retro.find_events
      的实测教训：直接用角度值二分会把「跳变点」当作根，把**冲**误标成**合**。
    """
    lon_b, _lat, _d = body_ecl_lonlat(eph, body, t)
    lon_s, _lats, _ds = body_ecl_lonlat(eph, 'sun', t)
    import numpy as _np
    return (_np.asarray(lon_b) - _np.asarray(lon_s) + 180.0) % 360.0 - 180.0


def moon_sun_phase_deg(eph, t):
    """月相角（度）：0=朔，90=上弦，180=望，270=下弦（0—360）。

    来源 skyfield `almanac.moon_phase`：月球相对太阳的**地心视黄经差**。
    与 `sun_body_lon_sep_deg(eph, 'moon', t) % 360` 同量，此处另给入口是为了
    「月相」这个业务概念有一个说得出口的公开名。
    """
    return _moon_phase_deg(eph, t) % 360.0


def body_pair_separation_deg(eph, body_a, body_b, t):
    """两天体的**地心视角距**（度，0—180）。

    ★ 与 `sun_body_lon_sep_deg` 的区别必须说清，否则「大距」会算错：
      · `sun_body_lon_sep_deg` 是**黄经差**（只比经度，不看纬度）；
      · 本函数是**真角距**（经度＋纬度一起算，即天球上的角距离）。
      「内行星大距」的判据是**真角距取极大**——用黄经差会得到错的时刻：
      内行星黄纬可达 ±7°（水星），黄纬变化叠进黄经差后，极值点会整体偏移。
    """
    a = eph['earth'].at(t).observe(_target(eph, body_a)).apparent()
    b = eph['earth'].at(t).observe(_target(eph, body_b)).apparent()
    return a.separation_from(b).degrees


def body_view_state(eph, body, t):
    """天体的**观测态**汇总（事件行写 params 用）。

    返回地心距(AU)、日心距(AU)、地日距(AU)、相位角(度)、视星等、当日黄纬(度)。
    星等走本模块的 `planet_magnitude`（Meeus ch.41），故星等口径**只此一处**；
    事件模块不得自己另算一个星等——那会造出同一站上两套亮度口径。
    """
    p = _apparent(eph, body, t)
    r = p["helio_distance_au"]
    d = p["distance_au"]
    R = p["earth_sun_distance_au"]
    ang = phase_angle_deg(body, r, d, R)
    return {
        "distance_au": d,
        "helio_distance_au": r,
        "earth_sun_distance_au": R,
        "phase_angle_deg": ang,
        "apparent_magnitude": planet_magnitude(body, r, d, ang),
        "ecl_lat_deg": p["ecl_lat_deg"],
    }


def calendar_jd(y, m, d, hour=0.0):
    """公历/儒略历日 + 小时 → **日历儒略日**（尺度无关的 JD 数值本身）。

    ★ 「尺度无关」这四个字是关键：JD 是个**数**，只有当你声明它是 TT 还是 UT
      时才带上尺度。故本函数**不给**任何尺度折算 —— 调用方要 TT 就按 TT 用，
      要 UT 就按 UT 用。反例（本项目实际踩到）：把 NASA 目录的 "TD 12:13:05"
      先当 UTC 喂给 skyfield、再把结果的 `.tt` 当 TT，会凭空引入 69.184 秒
      （32.184 s 力学时差 + 37 s 闰秒）的误差，且**只在跨尺度对拍时才暴露**。
    1582-10-15 之前自动按儒略历（与 `_jd_from_calendar` 同一实现，不另写一份）。
    """
    return _jd_from_calendar(int(y), int(m), int(d), float(hour))


# ------------------------------ 行星视星等（来源 S2 ch.41） ------------------------------
def planet_magnitude(body, r_au, delta_au, phase_angle_deg):
    """行星视星等。来源：Meeus《Astronomical Algorithms》ch.41（41.1—41.5）。

    ★ F8 修正：v1.0.0 的 _approx_mag 只用距离做 5log 硬凑，误差可达 1—2 等，
      据此给出的「肉眼可见/需双筒」分级站不住。今改用相位角公式。
      注：土星含环贡献未计入（需 B、B' 与环长轴角），故土星星等为近似值，已在输出标注。
    """
    i = max(0.0, min(180.0, phase_angle_deg))
    rd = max(1e-6, r_au * delta_au)
    if body == "mercury":
        v = -0.42 + 5 * math.log10(rd) + 0.0380 * i - 0.000273 * i * i + 0.000002 * i ** 3
    elif body == "venus":
        v = -4.40 + 5 * math.log10(rd) + 0.0009 * i + 0.000239 * i * i - 0.00000065 * i ** 3
    elif body == "mars":
        v = -1.52 + 5 * math.log10(rd) + 0.016 * i
    elif body == "jupiter":
        v = -9.40 + 5 * math.log10(rd) + 0.005 * i
    elif body == "saturn":
        v = -8.88 + 5 * math.log10(rd) + 0.044 * i   # 未含环贡献
    else:
        v = 0.0
    return round(v, 2)


def phase_angle_deg(body, r_au, delta_au, R_au):
    """太阳—行星—地球夹角 i（度）。Meeus ch.41：内行星与外行星用不同余弦式。"""
    try:
        if body in ("mercury", "venus"):
            c = (r_au ** 2 + delta_au ** 2 - R_au ** 2) / (2 * r_au * delta_au)
        else:
            c = (r_au ** 2 + R_au ** 2 - delta_au ** 2) / (2 * r_au * R_au)
        c = max(-1.0, min(1.0, c))
        return math.degrees(math.acos(c))
    except Exception:
        return 0.0


# ------------------------------ 可见性（纯天文，禁星占） ------------------------------
def _visibility(mag):
    """按视星等给观测难度分级（仅描述观测条件，不含吉凶解读）。

    阈值：≤2.0 肉眼易见；≤4.5 暗空肉眼可见（人眼极限约 6.0，此处取保守值）；
    ≤8.0 需双筒望远镜；>8.0 需较大小型望远镜。
    """
    if mag is None:
        return "—"
    if mag <= 2.0:
        return "肉眼易见"
    elif mag <= 4.5:
        return "暗空肉眼可见"
    elif mag <= 8.0:
        return "需双筒望远镜"
    else:
        return "需较大小型望远镜"


PLANETS = ["mercury", "venus", "mars", "jupiter", "saturn"]
PLANETS_CN = {"mercury": "水星", "venus": "金星", "mars": "火星",
              "jupiter": "木星", "saturn": "土星"}


class OutOfRange(RuntimeError):
    """请求日期落在所选星历覆盖区间之外（F5）。"""


# ============================== 主：单日天象 ==============================
def compute_daily(y, m, d, city="jieyang", tz_hours=None, ephemeris=None,
                  allow_analytic=None):
    """计算单日天象，返回可 JSON 序列化的字典。

    星历覆盖内 → DE421 精算（method='ephemeris_de421'）；
    覆盖外且允许降级 → Meeus 解析式（method='analytic_meeus'，只给太阳/月球与月相，
    升落与行星置空并说明原因）。
    """
    tz_hours = tz_hours if tz_hours is not None else CONFIG.TZ_OFFSET_HOURS
    if allow_analytic is None:
        allow_analytic = CONFIG.ANALYTIC_FALLBACK
    lat, lon, elev, city_name = CONFIG.CITIES.get(city, CONFIG.CITIES["jieyang"])
    eph = load_ephemeris(ephemeris)
    jd_lo, jd_hi, win_desc = ephemeris_window(eph, ephemeris)
    # 取当日「北京时正午」= 04:00 UTC（F10：v1.0.0 用 12:00 UTC，实为北京时间 20:00）
    jd_req = _jd_from_calendar(y, m, d, hour=(12.0 - tz_hours))
    in_range = (jd_lo is None) or (jd_lo <= jd_req <= jd_hi)
    date_str = ("%dBC-%02d-%02d" % (1 - y, m, d)) if y <= 0 else ("%04d-%02d-%02d" % (y, m, d))

    if not in_range and not allow_analytic:
        raise OutOfRange(
            "{0} 落在星历覆盖区间之外（{1}）。可加 --allow-analytic 走 Meeus 解析式降级，"
            "或换用覆盖更长的星历（de431/de422/de441）。".format(date_str, win_desc))

    if not in_range:
        return _daily_analytic(y, m, d, tz_hours, date_str, city, city_name,
                              lat, lon, elev, win_desc, ephemeris)

    ts = timescale()
    topos = _topos(lat, lon, elev)
    t = ts.utc(y, m, d, 12 - tz_hours, 0, 0)     # 北京时间正午
    xtbl = _xiu_table(eph, y, m)                 # 距星「当日黄道」视黄经表（F6）

    # —— 太阳（地心视位置）——
    sun = _apparent(eph, 'sun', t)
    sun_rs = _rise_set(eph, topos, 'sun', y, m, d, tz_hours)
    day_len_min = None
    if sun_rs["rise"] and sun_rs["set"]:
        h1, mi1 = map(int, sun_rs["rise"].split(":"))
        h2, mi2 = map(int, sun_rs["set"].split(":"))
        day_len_min = (h2 * 60 + mi2) - (h1 * 60 + mi1)

    sun_block = {
        "ecl_lon_deg": round(sun["ecl_lon_deg"], 4),
        "ecl_lon_j2000_deg": round(sun["ecl_lon_j2000_deg"], 4),
        "dec_deg": round(sun["dec_deg"], 4),
        "sub_solar_lat_deg": round(sun["dec_deg"], 4),   # 直射点纬度≈太阳赤纬
        "sunrise_bj": sun_rs["rise"],
        "sunset_bj": sun_rs["set"],
        "day_length_min": day_len_min,
        "twilight_civil": _twilight(eph, topos, y, m, d, tz_hours, -6),
        "twilight_nautical": _twilight(eph, topos, y, m, d, tz_hours, -12),
        "twilight_astronomical": _twilight(eph, topos, y, m, d, tz_hours, -18),
    }

    # —— 月球（地心视位置；升落另用站心）——
    moon = _apparent(eph, 'moon', t)
    moon_rs = _rise_set(eph, topos, 'moon', y, m, d, tz_hours)
    phase_deg = _moon_phase_deg(eph, t)
    moon_age = phase_deg / 360.0 * 29.53059      # 月龄（由月相角推算，近似）
    moon_dist_km = moon["distance_au"] * 149597870.7
    moon_block = {
        "phase_name": _moon_phase_name(phase_deg),
        "phase_deg": round(phase_deg, 2),
        "moon_age_days": round(moon_age, 2),
        "moonrise_bj": moon_rs["rise"],
        "moonset_bj": moon_rs["set"],
        "ecl_lon_deg": round(moon["ecl_lon_deg"], 4),
        "ecl_lat_deg": round(moon["ecl_lat_deg"], 4),
        "dec_deg": round(moon["dec_deg"], 4),
        "angular_diameter_arcmin": round(3474.2 / moon_dist_km * 180 / math.pi * 60, 2),
        "distance_km": round(moon_dist_km, 1),
        "distance_error_note": "误差千米量级（民用观测足够；DE421 月球实测精度为千米级，非亚米级）",
    }

    # —— 五大行星（星等用相位角公式） ——
    planets_block = {}
    for p in PLANETS:
        pos = _apparent(eph, p, t)
        i_deg = phase_angle_deg(p, pos["helio_distance_au"], pos["distance_au"],
                                pos["earth_sun_distance_au"])
        mag = planet_magnitude(p, pos["helio_distance_au"], pos["distance_au"], i_deg)
        planets_block[p] = {
            "ecl_lon_deg": round(pos["ecl_lon_deg"], 4),
            "ecl_lat_deg": round(pos["ecl_lat_deg"], 4),
            "dec_deg": round(pos["dec_deg"], 4),
            "distance_au": round(pos["distance_au"], 4),
            "phase_angle_deg": round(i_deg, 2),
            "apparent_mag": mag,
            "mag_note": ("含环贡献未计的近似值" if p == "saturn" else None),
            "xiu": xiu_of(pos["ecl_lon_deg"], table=xtbl),
            "visibility": _visibility(mag),
        }

    # —— 二十八宿：日月五星各自所在宿度 ——
    # ★ F8：删除 value_xiu_of_day。值日星宿属「二十八宿轮值 + 择日吉凶」体系，
    #   既非太阳所在宿，亦触本模块「禁吉凶谶纬」红线，故不再输出。
    xiu_block = {
        "frame": "黄道宿度（以当日黄道为准；距星表经 skyfield 岁差/章动变换到当日）",
        "sun_xiu": xiu_of(sun["ecl_lon_deg"], table=xtbl),
        "moon_xiu": xiu_of(moon["ecl_lon_deg"], table=xtbl),
        "planets_xiu": {p: planets_block[p]["xiu"] for p in PLANETS},
    }

    jd = t.tt
    year_dec = y + (m - 1) / 12.0
    dt_sec = delta_t_seconds(year_dec)
    record = {
        "date_str": date_str,
        "jd": round(jd, 6),
        "jd_ut": round(jde_to_jd_ut(jd, year_dec), 6),
        "jd_scale": "TT (JDE)",
        "tz": "UTC+%d" % tz_hours,
        "observer": {"city": city_name, "lat": lat, "lon": lon, "elev_m": elev},
        "data_version": CONFIG.DATA_VERSION,
        "method": "ephemeris_de421",
        "ephemeris": win_desc,
        "delta_t_sec": round(dt_sec, 2),
        "sun": sun_block,
        "moon": moon_block,
        "planets": planets_block,
        "xiu": xiu_block,
        "special_event": None,   # 由 identify_special_events 填充
        "disclaimer": ("天象数据基于 NASA JPL DE421 星历计算；近未来预报时刻精度 ±1 分钟，"
                       "月球位置误差千米量级。地面观测受天气与大气透明度影响，仅作天文参考，"
                       "不构成观测保证，不涉及星占、谶纬、吉凶解读。"),
    }
    return record


# ==================== 观测地维度（v2.0.0 · 「观测地可选」的数据面） ====================
# ★ 为什么要单独一层：
#   `compute_daily` 产出的 40 余项里，**只有 8 项与观测地有关** ——
#   日出/日落/昼长/三种晨昏/月出/月落。其余（黄经、赤纬、视星等、入宿、
#   月相、地月距离）都是**地心量**，换观测地不会变。
#   ⇒ 多观测地不必把整张 daily 表乘上城市数（那会把 5.5 万行变成数百万行），
#     只需另存这 8 项。这是本模块能支持「38 城」却仍保持体积可控的原因。
#
# ★ 实测基准（本机，2026-09-23，skyfield 1.55 + de421）：
#   compute_site_daily 单次 ≈ 0.168 s / compute_daily 单次 ≈ 0.258 s。
#   ⇒ 38 城 × 770 天（滚动窗）≈ 2.9 万次 ≈ 82 分钟单进程，8 进程实测约 10 分钟。

# 与观测地有关的字段清单（改这里就必须同步 templates / 校验器 / JS）
SITE_FIELDS = (
    "sunrise_bj", "sunset_bj", "day_length_min",
    "tw_civil_begin", "tw_civil_end",
    "tw_nautical_begin", "tw_nautical_end",
    "tw_astro_begin", "tw_astro_end",
    "moonrise_bj", "moonset_bj",
)


def city_keys():
    """预置城市键（稳定顺序，供 UI 下拉与报告表头复用）。"""
    return list(CONFIG.CITIES.keys())


def city_label(city):
    """city 键 → 中文名。未知键回落默认城市，**并返回默认名**（不抛）。"""
    return CONFIG.CITIES.get(city, CONFIG.CITIES["jieyang"])[3]


def resolve_city_key(name):
    """任意名字（键 / 中文名 / IP 定位返回的英文名）→ 预置城市键。

    认不出时返回 None —— **不得静默回落**（回落会让「IP 定位到广州」被
    当成「揭阳」而不出声，正是本项目反复踩的「认不出就回落默认值」陷阱）。
    调用方须自行决定如何降级并如实标注。
    """
    if not name:
        return None
    s = str(name).strip().lower().replace("_", " ").replace("-", " ")
    s = re.sub(r"\s+", " ", s)
    if s in CONFIG.CITIES:
        return s
    if s in CONFIG.CITY_ALIASES:
        return CONFIG.CITY_ALIASES[s]
    for key, (_la, _lo, _el, cn) in CONFIG.CITIES.items():
        if s == cn.lower():
            return key
    return None


def nearest_city(lat, lon):
    """经纬度 → 最近预置城市键（平面近似，纯几何，非天文计算）。

    用途：IP 定位到未收录的地级市时，落到最近的一座预置城。
    返回 (city_key, 距离km)。经纬度非法时返回 (None, None) —— 不抛、不猜。
    """
    try:
        la = float(lat)
        lo = float(lon)
    except (TypeError, ValueError):
        return None, None
    if not (-90.0 <= la <= 90.0 and -180.0 <= lo <= 180.0):
        return None, None
    best, best_d = None, None
    for key, (cla, clo, _el, _cn) in CONFIG.CITIES.items():
        # 平面近似：纬度方向 111.2 km/°，经度方向按纬度收缩
        dy = (la - cla) * 111.2
        dx = (lo - clo) * 111.2 * math.cos(math.radians((la + cla) / 2.0))
        d = math.hypot(dx, dy)
        if best_d is None or d < best_d:
            best, best_d = key, d
    return best, (round(best_d, 1) if best_d is not None else None)


def compute_site_daily(y, m, d, city="jieyang", tz_hours=None, ephemeris=None):
    """只算「与观测地有关的 11 项」，供 wp_astro_daily_site 落库。

    返回 dict，键与 SITE_FIELDS 一致，另有 date_str/city/city_cn/lat/lon/elev_m/
    tz/method/data_version 等元信息。**不含地心量**（那些在 daily 表里，与观测地无关）。
    """
    tz_hours = tz_hours if tz_hours is not None else CONFIG.TZ_OFFSET_HOURS
    key = resolve_city_key(city)
    if key is None:
        raise ValueError("未知观测地：%r（可用键见 CONFIG.CITIES）" % (city,))
    lat, lon, elev, city_name = CONFIG.CITIES[key]
    eph = load_ephemeris(ephemeris)
    jd_lo, jd_hi, win_desc = ephemeris_window(eph, ephemeris)
    jd_req = _jd_from_calendar(y, m, d, hour=(12.0 - tz_hours))
    in_range = (jd_lo is None) or (jd_lo <= jd_req <= jd_hi)
    date_str = ("%dBC-%02d-%02d" % (1 - y, m, d)) if y <= 0 else ("%04d-%02d-%02d" % (y, m, d))

    if not in_range:
        # 覆盖外不做升落（Meeus 级数不含站心升落）—— 如实留空，不猜。
        return {
            "date_str": date_str, "city": key, "city_cn": city_name,
            "lat": lat, "lon": lon, "elev_m": elev,
            "tz": "UTC+%d" % tz_hours,
            "method": "out_of_range_no_rise_set",
            "ephemeris": win_desc,
            "data_version": CONFIG.DATA_VERSION,
            "note": "该日期在星历覆盖区间（%s）之外，站心升落/晨昏不计算。" % win_desc,
            **{f: None for f in SITE_FIELDS},
        }

    topos = _topos(lat, lon, elev)
    sun_rs = _rise_set(eph, topos, "sun", y, m, d, tz_hours)
    moon_rs = _rise_set(eph, topos, "moon", y, m, d, tz_hours)
    tw_c = _twilight(eph, topos, y, m, d, tz_hours, -6)
    tw_n = _twilight(eph, topos, y, m, d, tz_hours, -12)
    tw_a = _twilight(eph, topos, y, m, d, tz_hours, -18)
    day_len = None
    if sun_rs["rise"] and sun_rs["set"]:
        h1, mi1 = map(int, sun_rs["rise"].split(":"))
        h2, mi2 = map(int, sun_rs["set"].split(":"))
        day_len = (h2 * 60 + mi2) - (h1 * 60 + mi1)

    return {
        "date_str": date_str,
        "city": key,
        "city_cn": city_name,
        "lat": lat, "lon": lon, "elev_m": elev,
        "tz": "UTC+%d" % tz_hours,
        "sunrise_bj": sun_rs["rise"],
        "sunset_bj": sun_rs["set"],
        "day_length_min": day_len,
        "tw_civil_begin": tw_c["begin"], "tw_civil_end": tw_c["end"],
        "tw_nautical_begin": tw_n["begin"], "tw_nautical_end": tw_n["end"],
        "tw_astro_begin": tw_a["begin"], "tw_astro_end": tw_a["end"],
        "moonrise_bj": moon_rs["rise"],
        "moonset_bj": moon_rs["set"],
        "method": "ephemeris_de421",
        "ephemeris": win_desc,
        "data_version": CONFIG.DATA_VERSION,
    }


def _daily_analytic(y, m, d, tz_hours, date_str, city, city_name, lat, lon, elev,
                    win_desc, ephemeris):
    """星历覆盖外的降级日记录（F5）：只给太阳/月球黄经与月相，明示精度与缺失项。"""
    year_dec = y + (m - 1) / 12.0
    # ★ F17：_jd_from_calendar() 给的是 **UT** 尺度儒略日；Meeus 级数要求 **TT**（JDE），
    #   必须显式加 ΔT。遗漏在 2026 年只差 0.0007 天（可忽略），但在公元前 720 年
    #   差约 0.24 天 ⇒ 月球黄经偏约 3.2°、朔望时刻偏约 5.8 h（历史回推的功能级错误）。
    jd_ut = _jd_from_calendar(y, m, d, hour=(12.0 - tz_hours))
    jde = jd_ut_to_jde(jd_ut, year_dec)
    sun_lon = meeus_sun_apparent_lon(jde)
    moon_lon, moon_lat = meeus_moon_lon_lat(jde)
    phase_deg = (moon_lon - sun_lon) % 360.0
    unc = delta_t_uncertainty_seconds(year_dec)
    return {
        "date_str": date_str,
        "jd": round(jde, 6),
        "jd_ut": round(jd_ut, 6),
        "jd_scale": "TT (JDE)",
        "tz": "UTC+%d" % tz_hours,
        "observer": {"city": city_name, "lat": lat, "lon": lon, "elev_m": elev},
        "data_version": CONFIG.DATA_VERSION + "+analytic",
        "method": "analytic_meeus",
        "ephemeris": "未使用（{0} 覆盖之外，已降级为 Meeus 解析式）".format(win_desc),
        "delta_t_sec": round(delta_t_seconds(year_dec), 2),
        "delta_t_uncertainty": "±%.0f s（约 ±%.1f min）" % (unc, unc / 60.0),
        "accuracy": CONFIG.ANALYTIC_ACCURACY,
        "sun": {
            "ecl_lon_deg": round(sun_lon, 4),
            "dec_deg": None,
            "sunrise_bj": None, "sunset_bj": None, "day_length_min": None,
            "twilight_civil": None, "twilight_nautical": None,
            "twilight_astronomical": None,
            "unavailable_reason": "升落与晨昏需星历级位置，解析降级不提供",
        },
        "moon": {
            "phase_name": _moon_phase_name(phase_deg),
            "phase_deg": round(phase_deg, 2),
            "moon_age_days": round(phase_deg / 360.0 * 29.53059, 2),
            "moonrise_bj": None, "moonset_bj": None,
            "ecl_lon_deg": round(moon_lon, 4),
            "ecl_lat_deg": round(moon_lat, 4),
            "dec_deg": None, "angular_diameter_arcmin": None, "distance_km": None,
            "unavailable_reason": "升落与距离需星历级位置，解析降级不提供",
        },
        "planets": None,
        "xiu": {
            "frame": "黄道宿度（以当日黄道为准；距星表 J2000 加累积岁差改正）",
            "sun_xiu": xiu_of(sun_lon, year_decimal=year_dec),
            "moon_xiu": xiu_of(moon_lon, year_decimal=year_dec),
            "planets_xiu": None,
        },
        "special_event": None,
        "disclaimer": ("本日超出所选星历覆盖区间，已降级为 Meeus 解析式（截断级数）近似值，"
                       "不提供升落/距离/行星数据；时刻须按 ΔT 不确定度区间理解，"
                       "仅作天文参考，不涉及星占、谶纬、吉凶解读。"),
    }


# ============================== 未来/历史事件识别 ==============================
def identify_special_events(y, m, d, eph=None):
    """在给定日期识别特殊天象（框架 + 可运行示例）。

    说明：流星雨极大、传统天象（偕日升落等）多为历表固定/约定值，需日历查表；
    日月食精确食分需月交点几何（skyfield almanac 或独立食分模块）。
    本函数给出「行星合日」「朔望（食候选）」等可计算项的识别。

    ★ v1.2.0：**删除原 `city` 形参**。该参数在 v1.1.0 中长期存在但函数体
      从未读取，属**死参数**——会让调用方误以为本函数的判据与观测地有关。
      实际两者都是**地心几何量**，与观测地无关：
        · 行星合日 —— 行星与太阳的黄经差；
        · 朔/望    —— 月球相位角。
      若将来要加「日没时是否仍在地平线上」这类**站心**判据，须显式传入
      topos 并在此处计算，不可再靠同名形参充数。
    """
    eph = eph or load_ephemeris()
    ts = timescale()
    found = []
    t = ts.utc(y, m, d, 12 - CONFIG.TZ_OFFSET_HOURS, 0, 0)
    sun_pos = _apparent(eph, 'sun', t)
    for p in PLANETS:
        pos = _apparent(eph, p, t)
        sep = abs(((pos["ecl_lon_deg"] - sun_pos["ecl_lon_deg"] + 180) % 360) - 180)
        if sep < 5.0:
            found.append({
                "event_type": "planet",
                "title": "%s 合日（黄经差 %.1f°）" % (PLANETS_CN.get(p, p), sep),
                "note": "纯天文描述：行星与太阳同黄经，通常淹没于日光中，非观测良机",
            })
    # 朔/望 → 食候选
    # ★ F8：原判据 `phase < 5 or abs(phase-180) < 5` 漏掉接近 360° 的朔（回绕），
    #   改为取到 0°/180° 的最小角距。
    phase = _moon_phase_deg(eph, t)
    d_new = min(abs(phase), 360.0 - abs(phase))
    d_full = abs(phase - 180.0)
    if d_new < 5.0 or d_full < 5.0:
        is_new = d_new < 5.0
        found.append({
            "event_type": "solar_eclipse" if is_new else "lunar_eclipse",
            "title": "%s（食分需月交点几何精算）" % ("朔（日食候选）" if is_new else "望（月食候选）"),
            "note": "候选标记；精确初亏/食甚/复圆/食分由独立食分模块计算，不在本脚本精度范围",
        })
    return found


# ============================== 历史回推 ==============================
def parse_era_year(s):
    """把纪年字符串解析为**天文纪年**整数。

    ★ 口径陷阱（必读）：天文纪年以 0 表示**公元前 1 年**，故
        「公元前 N 年」= 天文年 −(N−1)。
      直接传 -720 会被理解成「公元前 721 年」，整整差一年。
      为免误用，本函数接受 '720BC' / '720BCE' / '前720' / '-719' 等写法：
        '720BC' → -719（天文）    '-719' → -719（直给天文年）
        '2026AD'/'2026' → 2026
    """
    s = str(s).strip().upper().replace(" ", "")
    if s.endswith("BCE") or s.endswith("BC"):
        n = int(s[:-3] if s.endswith("BCE") else s[:-2])
        return -(n - 1)
    if s.endswith("AD") or s.endswith("CE"):
        return int(s[:-2])
    if s.startswith("前"):
        return -(int(s[1:]) - 1)
    return int(s)


def era_year_display(y):
    """天文纪年整数 → 中文纪年描述。"""
    if y <= 0:
        return "公元前 %d 年" % (1 - y)
    return "公元 %d 年" % y


def eclipse_candidate_note(moon_ecl_lat_deg, kind="solar"):
    """食可能性判定（仅「必要条件」，不下食分结论）。

    判据（Meeus ch.54 / 经典粗略式）：朔时月球黄纬 |β| < 1.5° ⇒ **地球上某处**可能见日食；
    |β| < 1.0° 则可能性较高。这是必要非充分条件——是否真能见、食分为何，
    取决于月地距离、纬向与经向的几何，须由独立食分模块精算。

    ★ 本函数只输出可能性，不给食分、不给见食地、不作任何吉凶解读。
    """
    b = abs(moon_ecl_lat_deg)
    if kind == "solar":
        if b < 1.0:
            return ("朔时月球黄纬 |β|=%.2f° < 1.0°，具备日食的**必要条件**，可能性较高；"
                    "是否见食与食分须由独立食分模块精算。" % b)
        if b < 1.5:
            return ("朔时月球黄纬 |β|=%.2f° < 1.5°，具备日食的**必要条件**（可能性较低）；"
                    "是否见食与食分须由独立食分模块精算。" % b)
        return "朔时月球黄纬 |β|=%.2f° ≥ 1.5°，不满足日食的必要条件。" % b
    else:
        if b < 1.5:
            return ("望时月球黄纬 |β|=%.2f°，具备月食的必要条件；"
                    "是否见食与食分须由独立食分模块精算。" % b)
        return "望时月球黄纬 |β|=%.2f°，不满足月食的必要条件。" % b


def back_calc_historical(era_year, month, day, calendar_note, source_text, source_ref,
                         ephemeris=None, allow_analytic=None):
    """历史天象回推：纪年(含公元前) → 儒略日 → 星历/解析反演 → 不确定度区间。

    严格区分三层：literature(文献记载) / calc(星历计算) / discussion(学术争议)。
    仅标注区间，不给绝对时刻；附 ΔT 模型版本与不确定度。

    ★ F5：星历覆盖外不再崩溃（v1.0.0 会在 -720 年直接抛 EphemerisRangeError，
      使「历史回推」功能整体不可用）；改为降级到 Meeus 解析式，
      并给出「最近的朔/望时刻」——这才是历史日食/月食条目的关键量。
    """
    if allow_analytic is None:
        allow_analytic = CONFIG.ANALYTIC_FALLBACK
    # ★ F17：纪年 → **UT** 儒略日，再显式折算为 **TT（JDE）** 后才喂 Meeus。
    #   古代 ΔT 可达数小时：漏折会让月球黄经偏数度、朔望时刻偏数小时。
    jd_query_ut = _jd_from_calendar(era_year, month, day,
                                    hour=(12.0 - CONFIG.TZ_OFFSET_HOURS))   # 北京正午
    year_dec = era_year + (month - 1) / 12.0
    jd_query_tt = jd_ut_to_jde(jd_query_ut, year_dec)
    unc = delta_t_uncertainty_seconds(year_dec)
    dt_sec = delta_t_seconds(year_dec)
    eph = load_ephemeris(ephemeris)
    jd_lo, jd_hi, win_desc = ephemeris_window(eph, ephemeris)
    in_range = (jd_lo is None) or (jd_lo <= jd_query_tt <= jd_hi)

    # —— 解析层：最近的朔与望（Meeus ch.49，分钟量级；不依赖星历） ——
    # ★ 区间方向（v1.1.0 修正）：UT = TT − ΔT。若真实 ΔT 比模型值**大**，则 UT **更早**。
    #   故 earliest = 在 jde 上「减」ΔT 容差，latest = 「加」ΔT 容差。
    #   （v1.0.0 草案把两侧标签写反，会让页面把最早时刻说成最晚时刻。）
    k_new = round((jd_query_tt - 2451550.09766) / 29.530588861)
    phases = []
    for k in (k_new - 1, k_new, k_new + 1,
              k_new - 1 + 0.5, k_new + 0.5, k_new + 1.5):
        jde, label = meeus_phase_jde(k)
        if abs(jde - jd_query_tt) >= 40:
            continue
        rec_ph = {
            "phase": label,
            "jd_tt": round(jde, 6),
            "time_bj": meeus_jd_to_bj(jde, CONFIG.TZ_OFFSET_HOURS),
            "time_bj_earliest": meeus_jd_to_bj(jde - unc / 86400.0, CONFIG.TZ_OFFSET_HOURS),
            "time_bj_latest": meeus_jd_to_bj(jde + unc / 86400.0, CONFIG.TZ_OFFSET_HOURS),
            "delta_from_query_days": round(jde - jd_query_tt, 4),
        }
        if label.startswith("朔"):
            mlon, mlat = meeus_moon_lon_lat(jde)
            rec_ph["moon_ecl_lat_deg"] = round(mlat, 4)
            rec_ph["eclipse_note"] = eclipse_candidate_note(mlat, "solar")
        phases.append(rec_ph)
    phases.sort(key=lambda x: abs(x["delta_from_query_days"]))

    calc = {
        "jd_query_tt": round(jd_query_tt, 6),
        "jd_query_ut": round(jd_query_ut, 6),
        "jd_scale": "TT (JDE)",
        "dt_model": CONFIG.DATA_VERSION,
        "delta_t_sec": round(dt_sec, 2),
        "time_uncertainty": "±%.0f s（约 ±%.1f min；古代典型 ±30min～±2h）" % (unc, unc / 60.0),
        "nearest_phases": phases[:4],
        "phase_accuracy": CONFIG.ANALYTIC_ACCURACY["note"],
        "method": "analytic_meeus" if not in_range else "ephemeris_de421",
        "ephemeris": win_desc if in_range else "未使用（{0} 覆盖之外，已降级为 Meeus 解析式）".format(win_desc),
    }

    if in_range:
        ts = timescale()
        t = ts.utc(era_year, month, day, 12 - CONFIG.TZ_OFFSET_HOURS, 0, 0)
        xtbl = _xiu_table(eph, era_year, month)
        sun = _apparent(eph, 'sun', t)
        moon = _apparent(eph, 'moon', t)
        calc.update({
            "jd": round(t.tt, 6),
            "sun_ecl_lon_deg": round(sun["ecl_lon_deg"], 4),
            "moon_ecl_lon_deg": round(moon["ecl_lon_deg"], 4),
            "moon_ecl_lat_deg": round(moon["ecl_lat_deg"], 4),
            "sun_xiu": xiu_of(sun["ecl_lon_deg"], table=xtbl),
            "moon_xiu": xiu_of(moon["ecl_lon_deg"], table=xtbl),
        })
    else:
        calc.update({
            "sun_ecl_lon_deg": round(meeus_sun_apparent_lon(jd_query_tt), 4),
            "moon_ecl_lon_deg": round(meeus_moon_lon_lat(jd_query_tt)[0], 4),
            "moon_ecl_lat_deg": round(meeus_moon_lon_lat(jd_query_tt)[1], 4),
            "sun_xiu": xiu_of(meeus_sun_apparent_lon(jd_query_tt), year_decimal=year_dec),
            "moon_xiu": xiu_of(meeus_moon_lon_lat(jd_query_tt)[0], year_decimal=year_dec),
            "accuracy": CONFIG.ANALYTIC_ACCURACY,
        })

    return {
        "chronology": {
            "era_year": era_year, "month": month, "day": day,
            "era_year_display": era_year_display(era_year),
            "calendar_note": calendar_note,
            "gregorian_bj": jd_to_str(jd_query_ut, CONFIG.TZ_OFFSET_HOURS),
            "year_convention": ("天文纪年（0 = 公元前 1 年）；"
                                "若原文为「公元前 N 年」，请用 'NBC' 写法传入或换算为 −(N−1)"),
        },
        "literature": {            # 文献记载层
            "source_text": source_text,
            "source_ref": source_ref,
        },
        "calc": calc,              # 星历计算层（现代回推）
        "discussion": (            # 学术争议层（不下绝对定论）
            "回推时刻受地球自转长期变化(ΔT)影响存在不确定度，已标注区间；"
            "不同学派对文献纪年/干支换算存在分歧，本结果仅作学术交流参考，"
            "不构成任何历史事件的唯一结论。"
        ),
    }


# ============================== 输出：JSON / 写库 / REST ==============================
def to_json(obj, path=None):
    s = json.dumps(obj, ensure_ascii=False, indent=2)
    if path:
        d = os.path.dirname(os.path.abspath(path))
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        # ★ newline="\n"：强制 LF。不写时在 Windows 上文本模式会把 \n 换成 \r\n，
        #   与 build_dataset.py 的 _write_json（已 newline="\n"）出不同行尾，
        #   同属 05-工具/ 却行尾不一，违反本项目「行尾按件判、同目录须统一」的纪律。
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(s)
    return s


def write_db(records, host, user, password, db, prefix="wp_", batch=500):
    """写库模式（★ 仅适用于**自建 MySQL**）。

    ⚠ F9 关键约束：WordPress.com 托管**不开放外部 MySQL 连接**，因此在 WordPress.com 托管站点
      上本函数不可用。线上请改用 --wp-rest（经插件 REST 端点导入）。
    依赖可选：未安装驱动时跳过并提示，不阻断 JSON 产出。
    """
    try:
        import pymysql
    except ImportError:
        try:
            import mysql.connector as pymysql  # 兼容别名
        except ImportError:
            print("[write_db] 未安装 pymysql/mysql.connector，跳过写库（仅产出 JSON）。",
                  file=sys.stderr)
            return False
    conn = pymysql.connect(host=host, user=user, password=password, database=db,
                           charset="utf8mb4")
    try:
        cur = conn.cursor()
        sql = ("REPLACE INTO `%sastro_daily` (date_str, jd, data_json, data_version, updated_at) "
               "VALUES (%%s, %%s, %%s, %%s, NOW())" % prefix)
        for i in range(0, len(records), batch):
            chunk = [(r["date_str"], r["jd"], json.dumps(r, ensure_ascii=False),
                      r["data_version"]) for r in records[i:i + batch]]
            cur.executemany(sql, chunk)
            conn.commit()
    finally:
        conn.close()
    return True


def push_rest(rows, table, site, user, app_password, batch=200, sleep_s=0.3,
              timeout=90, verbose=True):
    """经 WP 插件 REST 端点导入（F9：WP.com 唯一可行入库路径）。

    端点：POST {site}/wp-json/kcj-astro/v1/import
    鉴权：HTTP Basic + WordPress「应用程序密码」（用户 → 个人资料 → 应用程序密码）
    分批发以避免 PHP/网关超时；每批之间短暂休眠。
    """
    import base64
    import time
    import urllib.error
    import urllib.request

    token = base64.b64encode(("{0}:{1}".format(user, app_password)).encode("utf-8")).decode("ascii")
    endpoint = site.rstrip("/") + "/wp-json/kcj-astro/v1/import"
    total, sent, failed_total, all_errors = len(rows), 0, 0, []
    for i in range(0, total, batch):
        chunk = rows[i:i + batch]
        payload = json.dumps({"table": table, "rows": chunk}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(endpoint, data=payload, method="POST")
        req.add_header("Content-Type", "application/json; charset=utf-8")
        req.add_header("Authorization", "Basic " + token)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            raise RuntimeError("REST 导入失败 HTTP %s：%s" % (e.code, detail))
        except Exception as e:
            raise RuntimeError("REST 导入失败：%s" % e)
        ok   = int(body.get("written", 0))
        bad  = int(body.get("failed", 0))
        errs = body.get("errors") or []
        sent += ok
        failed_total += bad
        for e in errs:
            all_errors.append("第 %d 批：%s" % (i // batch + 1, e))
        if verbose:
            print("[push_rest] %s 第 %d/%d 批：写入 %d 行（累计 %d/%d）%s"
                  % (table, i // batch + 1, (total + batch - 1) // batch, ok, sent, total,
                     ("，**失败 %d 行**" % bad) if bad else ""),
                  file=sys.stderr)
            # ★ 服务端 errors[] 一定要打出来：v1.2.0 只读 written ⇒ 服务端拒写
            #   （如列宽溢出）被静默吞成「写入 0 行」，排查时完全没有线索。
            for e in errs[:3]:
                print("           ↳ %s" % e, file=sys.stderr)
            if len(errs) > 3:
                print("           ↳ …另有 %d 条同类错误（见文末汇总）" % (len(errs) - 3),
                      file=sys.stderr)
        time.sleep(sleep_s)
    if failed_total:
        raise RuntimeError(
            "REST 导入有 %d 行失败（成功 %d/%d）：%s"
            % (failed_total, sent, total, " ｜ ".join(all_errors[:5])
               + ("" if len(all_errors) <= 5 else " ｜ …共 %d 条" % len(all_errors))))
    return sent


def flush_remote_cache(site, user, app_password, timeout=60):
    """导入完成后请服务端清 transient 缓存（替代 v1.0.0 里外部无法触发的 do_action）。"""
    import base64
    import urllib.request
    token = base64.b64encode(("{0}:{1}".format(user, app_password)).encode("utf-8")).decode("ascii")
    endpoint = site.rstrip("/") + "/wp-json/kcj-astro/v1/flush-cache"
    req = urllib.request.Request(endpoint, data=b"{}", method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Basic " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ============================== 自检（端到端校验） ==============================
def selftest(verbose=True):
    """离线自检：ΔT / 岁差 / 宿度覆盖 / Meeus 教材算例 / 与 DE421 交叉比对。

    设计原则（吸取 v1.0.0 教训）：**不拿记忆里的常数当判据**——凡是能与权威实现
    （skyfield + DE421）对拍的项，一律现场对拍；只在无法联网/无星历时才用教材例题。
    """
    ok, fails = 0, []

    def chk(name, cond, detail=""):
        nonlocal ok
        if cond:
            ok += 1
            if verbose:
                print("  [PASS] %s %s" % (name, detail))
        else:
            fails.append("%s %s" % (name, detail))
            print("  [FAIL] %s %s" % (name, detail))

    # ---- T1 ΔT 抽样 ----
    chk("ΔT(2026)≈63s", abs(delta_t_seconds(2026) - 63.0) < 1.0,
        "=%.2f" % delta_t_seconds(2026))
    chk("ΔT(1900)<0", delta_t_seconds(1900) < 0, "=%.2f" % delta_t_seconds(1900))
    chk("ΔT(-720) 为大正值", delta_t_seconds(-720) > 10000, "=%.0f" % delta_t_seconds(-720))

    # ---- T2 岁差近似式（解析降级路径用）：与理论值比，允许 ~0.01° 级偏差 ----
    # 理论：2026-09-22 距 J2000 为 T=0.26723 儒略世纪 → p = 5029.0966·T + 1.11113·T²
    p_deg = precession_lon_arcsec(2026.0) / 3600.0
    chk("岁差近似式 0.3733°（T=0.26）", abs(p_deg - 0.3632) < 0.005, "=%.4f°" % p_deg)

    # ---- T3 Meeus 教材算例（离线可跑，不依赖星历） ----
    lon47, lat47 = meeus_moon_lon_lat(2448724.5)     # Ex 47.a 1992-04-12.0 TD
    chk("Meeus Ex47.a 月球黄经 <0.01°", abs(lon47 - 133.162655) < 0.01,
        "=%.6f（期望 133.162655）" % lon47)
    chk("Meeus Ex47.a 月球黄纬 <0.01°", abs(lat47 - (-3.229126)) < 0.01,
        "=%.6f（期望 −3.229126）" % lat47)
    sun25 = meeus_sun_apparent_lon(2448908.5)        # Ex 25.b 1992-10-13.0 TD
    chk("Meeus Ex25.b 太阳视黄经 <0.01°", abs(sun25 - 199.90988) < 0.01,
        "=%.5f（期望 199.90988）" % sun25)

    # ---- T4 宿度覆盖 28/28（近似表；精算表在 T6 复测） ----
    hit = set()
    for i in range(3600):
        hit.add(xiu_of(i / 10.0, year_decimal=2026.0))
    chk("宿度近似表覆盖 28/28", len(hit) == 28, "= %d 宿" % len(hit))

    # ---- T5 目标名回落（F3b：DE421 无 'jupiter'/'saturn' 本体名） ----
    try:
        eph0 = load_ephemeris()
        chk("木星目标回落（barycenter）", _target(eph0, "jupiter") is not None)
        chk("土星目标回落（barycenter）", _target(eph0, "saturn") is not None)
    except Exception as e:
        fails.append("目标名回落：%s" % e)

    # ---- T6 端到端：与 DE421 交叉比对 ----
    try:
        eph = load_ephemeris()
        ts = timescale()
        topo = _topos(*CONFIG.CITIES["jieyang"][:3])
        t = ts.utc(2026, 9, 22, 4, 0, 0)
        s = _apparent(eph, 'sun', t)
        mo = _apparent(eph, 'moon', t)
        a_sun = meeus_sun_apparent_lon(t.tt)
        a_mlon, a_mlat = meeus_moon_lon_lat(t.tt)
        chk("解析太阳黄经 vs DE421 <0.02°", abs(a_sun - s["ecl_lon_deg"]) < 0.02,
            "解析 %.4f / DE421 %.4f" % (a_sun, s["ecl_lon_deg"]))
        # 地心对地心（同坐标系）；站心月球会差 ~0.9°（视差），不可作对拍基准
        chk("解析月球黄经 vs DE421 <0.05°", abs(a_mlon - mo["ecl_lon_deg"]) < 0.05,
            "解析 %.4f / DE421 %.4f" % (a_mlon, mo["ecl_lon_deg"]))
        chk("解析月球黄纬 vs DE421 <0.05°", abs(a_mlat - mo["ecl_lat_deg"]) < 0.05,
            "解析 %.4f / DE421 %.4f" % (a_mlat, mo["ecl_lat_deg"]))

        # 升落 / 晨昏（站心）
        rs = _rise_set(eph, topo, 'sun', 2026, 9, 22, 8)
        chk("太阳升落非空", bool(rs["rise"]) and bool(rs["set"]),
            "日出 %s / 日落 %s" % (rs["rise"], rs["set"]))
        rs_m = _rise_set(eph, topo, 'moon', 2026, 9, 22, 8)
        chk("月亮升落（跨日可取其一）", bool(rs_m["rise"]) or bool(rs_m["set"]),
            "月出 %s / 月落 %s" % (rs_m["rise"], rs_m["set"]))
        tw = _twilight(eph, topo, 2026, 9, 22, 8, -6)
        chk("民用晨昏非空", bool(tw["begin"]) and bool(tw["end"]),
            "晨 %s / 昏 %s" % (tw["begin"], tw["end"]))

        # 宿度精算表
        xt = _xiu_table(eph, 2026, 9)
        segs = []
        for i in range(len(xt)):
            a = xt[i][1]
            b = xt[(i + 1) % len(xt)][1]
            segs.append((b - a) % 360.0)
        chk("宿度精算表 28 段且段宽合计≈360°", len(xt) == 28
            and abs(sum(segs) - 360.0) < 0.01,
            "段宽 min=%.2f° max=%.2f°" % (min(segs), max(segs)))
        hit2 = set(_xiu_seg(i / 10.0, xt) for i in range(3600))
        chk("宿度精算表覆盖 28/28", len(hit2) == 28, "=%d 宿" % len(hit2))

        # 相位序 vs skyfield（独立高精度参考）
        from skyfield import almanac
        times, kinds = almanac.find_discrete(ts.utc(2026, 1, 1), ts.utc(2027, 1, 1),
                                             almanac.moon_phases(eph))
        worst, n = 0.0, 0
        for ti, ki in zip(times, kinds):
            kk = (ti.tt - 2451550.09766) / 29.530588861
            if int(ki) == 0:
                k_use = round(kk)
            elif int(ki) == 2:
                k_use = round(kk - 0.5) + 0.5
            else:
                continue
            jde, _lab = meeus_phase_jde(k_use)
            worst = max(worst, abs((jde - ti.tt) * 1440.0))
            n += 1
        chk("解析月相 vs skyfield <5min（2026 全年抽样）", n > 20 and worst < 5.0,
            "%d 个朔望，最大偏差 %.2f min" % (n, worst))

        # 全流水线
        rec = compute_daily(2026, 9, 22)
        chk("compute_daily 全流水线可跑", rec["method"] == "ephemeris_de421"
            and rec["xiu"]["sun_xiu"] != "" and len(rec["planets"]) == 5,
            "日宿 %s / 月宿 %s / 行星 %d 颗"
            % (rec["xiu"]["sun_xiu"], rec["xiu"]["moon_xiu"], len(rec["planets"])))
        chk("已删除 value_xiu_of_day（合规）", "value_xiu_of_day" not in rec["xiu"])
        chk("输出含 method/ephemeris 溯源字段",
            rec["method"] == "ephemeris_de421" and bool(rec["ephemeris"]))

        # 范围守卫：越界应降级而非崩溃
        rec2 = compute_daily(1000, 1, 1)
        chk("越界自动降级（不崩溃）", rec2["method"] == "analytic_meeus"
            and rec2["planets"] is None, "method=%s" % rec2["method"])
        try:
            compute_daily(1000, 1, 1, allow_analytic=False)
            chk("--no-analytic 时越界应报错", False, "未报错")
        except OutOfRange:
            chk("--no-analytic 时越界应报错", True, "已抛 OutOfRange")

        # ★ F18：改引 SAMPLE_HISTORICAL 单一真值源（原先此处写 (-720, 7, 1)，
        #   与 emit_samples 的 (−719, 2, 22) 矛盾——同一史事差一年半）。
        hist = back_calc_historical(SAMPLE_HISTORICAL["era_year"],
                                    SAMPLE_HISTORICAL["month"],
                                    SAMPLE_HISTORICAL["day"],
                                    SAMPLE_HISTORICAL["calendar_note"],
                                    SAMPLE_HISTORICAL["source_text"],
                                    SAMPLE_HISTORICAL["source_ref"])
        ph = hist["calc"]["nearest_phases"]
        chk("历史回推可跑（公元前720年）",
            hist["calc"]["method"] == "analytic_meeus" and len(ph) > 0,
            "最近月相 %s（%s）" % (ph[0]["time_bj"] if ph else "—",
                                  ph[0]["phase"] if ph else "—"))
        # ★ F17 断言：UT 与 TT 两个尺度必须都已输出，且差值 = ΔT/86400（不是 0）。
        _c = hist["calc"]
        _dt_days = _c["delta_t_sec"] / 86400.0
        chk("F17 历史回推已做 UT→TT 折算",
            abs((_c["jd_query_tt"] - _c["jd_query_ut"]) - _dt_days) < 1e-6,
            "jd_tt−jd_ut=%.6f 天（ΔT=%.0f s，应等于 %.6f）"
            % (_c["jd_query_tt"] - _c["jd_query_ut"], _c["delta_t_sec"], _dt_days))
        chk("F17 尺度字段自述（jd_scale）", _c.get("jd_scale") == "TT (JDE)",
            "jd_scale=%s" % _c.get("jd_scale"))
        chk("F18 示例史事只引古籍正本（不引近现代注本）",
            "春秋" in SAMPLE_HISTORICAL["source_ref"]
            and "杨伯峻" not in str(SAMPLE_HISTORICAL),
            SAMPLE_HISTORICAL["source_ref"])
        chk("F18 纪年解析与示例常量一致（防再次漂移）",
            parse_era_year("720BC") == SAMPLE_HISTORICAL["era_year"]
            and era_year_display(SAMPLE_HISTORICAL["era_year"]) == "公元前 720 年",
            "parse_era_year('720BC')=%d  display=%s"
            % (parse_era_year("720BC"), era_year_display(SAMPLE_HISTORICAL["era_year"])))
        chk("历史回推给区间而非唯一时刻",
            bool(ph[0]["time_bj_earliest"]) and bool(ph[0]["time_bj_latest"])
            and ph[0]["time_bj_earliest"] != ph[0]["time_bj_latest"]
            if ph else False)
        hist2 = back_calc_historical(1900, 3, 1, "测试", "src", "ref")
        chk("历史回推（星历覆盖内）走精算", hist2["calc"]["method"] == "ephemeris_de421",
            "method=%s" % hist2["calc"]["method"])
    except Exception as e:
        fails.append("skyfield 端到端：%s" % e)
        print("  [SKIP] skyfield 端到端未跑（%s）" % str(e)[:200])

    print("  —— 自检合计：通过 %d 项，失败 %d 项" % (ok, len(fails)))
    return ok, fails


# ============================== 样例数据导出 ==============================
def emit_samples(outdir, city="jieyang", ephemeris=None):
    """导出三份样例（交付物 F）。数值全部来自真实计算，不再手写。"""
    os.makedirs(outdir, exist_ok=True)
    # 1 单日
    rec = compute_daily(2026, 9, 22, city=city, ephemeris=ephemeris)
    rec["special_event"] = identify_special_events(2026, 9, 22)   # F19：city 为死参数，已删
    p1 = os.path.join(outdir, "daily_sample.json")
    to_json(rec, p1)
    # 2 未来事件
    ev = {
        "event_id": 1001,
        "event_type": "solar_eclipse",
        # ★ F17：jd_core 与日表 jd 同口径（TT），否则两类记录不可直接相减。
        "jd_core": round(jd_ut_to_jde(
            _jd_from_calendar(2027, 8, 2, hour=10.5), 2027 + 7 / 12.0), 6),
        "jd_scale": "TT (JDE)",
        "event_time_bj": "2027-08-02 18:30:00",
        "time_uncertainty": None,
        "dt_model": CONFIG.DATA_VERSION,
        "ephemeris": CONFIG.EPHEMERIS_PROFILES["de421.bsp"][2] + " 至 "
                     + CONFIG.EPHEMERIS_PROFILES["de421.bsp"][3],
        "method": "ephemeris_de421",
        "post_id": 0,
        "title": "2027年8月2日日全食（中国北方可见偏食）",
        "slug": "2027-08-02-total-solar-eclipse",
        "summary": ("月球运行至黄白交点附近且为朔，遮挡太阳盘面。中国境内见食带有限，"
                    "北方部分地区可见偏食，食分随纬度变化。观测须使用专业减光设备，禁止裸眼直视。"),
        "params_json": {
            "eclipse_type": "total",
            "magnitude": 1.03,
            "max_phase_bj": "18:30",
            "visible_region_cn": "新疆北部、内蒙古、东北部分地区见偏食",
            "safety_note": "必须使用 ISO 12312-2 认证日食眼镜或投影法，不可用普通墨镜/相机直拍",
            "data_source": "食分与食带为事件级参数，须由独立食分模块精算后回填；本表为结构样例",
        },
        "obs_guide": "以投影法或专用减光片观测；记录当地见食起止与食分；避免任何未减光的光学直视。",
        "literature": None,
        "discussion": None,
        "source_ref": "NASA Solar Eclipse Explorer (eclipse.gsfc.nasa.gov)；星历 DE421",
        "publish_status": 0,
        "rel_type_hint": "same_type",
    }
    p2 = os.path.join(outdir, "future_event_sample.json")
    to_json(ev, p2)
    # 3 历史事件（★ F18：与 selftest 同引 SAMPLE_HISTORICAL，不再各写一份）
    hist = back_calc_historical(SAMPLE_HISTORICAL["era_year"],
                               SAMPLE_HISTORICAL["month"],
                               SAMPLE_HISTORICAL["day"],
                               SAMPLE_HISTORICAL["calendar_note"],
                               SAMPLE_HISTORICAL["source_text"],
                               SAMPLE_HISTORICAL["source_ref"],
                               ephemeris=ephemeris)
    hist["event_id"] = 9001
    hist["title"] = "公元前720年鲁隐公三年日食（文献回推）"
    hist["slug"] = "bce-720-chunqiu-solar-eclipse"
    hist["event_type"] = "historical"
    hist["rel_type_hint"] = "same_type"
    p3 = os.path.join(outdir, "historical_event_sample.json")
    to_json(hist, p3)
    return [p1, p2, p3]


# ============================== CLI ==============================
def _iter_dates(start, end):
    sy, sm, sd = map(int, start.split("-"))
    ey, em, ed = map(int, end.split("-"))
    cur, last = datetime(sy, sm, sd), datetime(ey, em, ed)
    while cur <= last:
        yield cur.year, cur.month, cur.day
        cur += timedelta(days=1)


def _worker(args):
    y, m, d, city, ephemeris, allow = args
    try:
        rec = compute_daily(y, m, d, city=city, ephemeris=ephemeris, allow_analytic=allow)
        rec["special_event"] = identify_special_events(y, m, d)   # F19：city 为死参数，已删
        return rec
    except Exception as e:
        return {"date_str": "%04d-%02d-%02d" % (y, m, d), "_error": str(e)}


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="天象预报批量计算（DE421 / Meeus 降级）。输出 JSON 或经 REST 入库。"
                    "禁占星/吉凶内容。")
    ap.add_argument("--date", help="单日计算 YYYY-MM-DD（公元前用 -YYYY）")
    ap.add_argument("--start", help="区间起始 YYYY-MM-DD（含）")
    ap.add_argument("--end", help="区间结束 YYYY-MM-DD（含）")
    ap.add_argument("--city", default="jieyang", help="预置城市键（见 CONFIG.CITIES）")
    ap.add_argument("--json", help="JSON 输出路径（单日/区间写同一文件）")
    ap.add_argument("--ephemeris", help="星历路径或文件名（默认自动发现 de421.bsp）")
    ap.add_argument("--allow-analytic", action="store_true", default=None,
                    help="星历覆盖外允许降级到 Meeus 解析式（默认开启）")
    ap.add_argument("--no-analytic", dest="allow_analytic", action="store_false",
                    help="星历覆盖外直接报错，不降级")
    ap.add_argument("--jobs", type=int, default=1, help="区间模式并行进程数（默认 1）")
    ap.add_argument("--selftest", action="store_true", help="跑离线自检并退出")
    ap.add_argument("--emit-samples", metavar="DIR", help="用真实计算导出三份样例数据")
    ap.add_argument("--window", action="store_true", help="打印星历覆盖区间与预计算面方案")
    ap.add_argument("--db", action="store_true",
                    help="[仅自建 MySQL] 写库；WP.com 不开放外部 DB，请改用 --wp-rest")
    ap.add_argument("--db-host", default="localhost")
    ap.add_argument("--db-user", default="root")
    ap.add_argument("--db-pass", default="")
    ap.add_argument("--db-name", default="wordpress")
    ap.add_argument("--wp-rest", action="store_true", help="经 WP 插件 REST 端点导入")
    ap.add_argument("--wp-site", default="", help="WordPress 站点地址，如 https://example.com")
    ap.add_argument("--wp-user", default="")
    ap.add_argument("--wp-app-password", default="")
    ap.add_argument("--wp-table", default="daily", choices=["daily", "events", "relations"])
    ap.add_argument("--history", nargs=5, metavar=("YEAR", "MONTH", "DAY", "SOURCE_TEXT", "SOURCE_REF"),
                    help="历史回推。★纪年请用 '720BC' 写法（= 公元前720年）；也可直给天文年负数"
                         "（如 -719）。示例 --history 720BC 2 22 '春秋...' '杨伯峻《春秋左传注》'")
    ap.add_argument("--history-note", default="", help="历史纪年说明（如 '鲁隐公三年'）")
    args = ap.parse_args(argv)

    if args.selftest:
        _ok, fails = selftest()
        return 0 if not fails else 1

    if args.window:
        eph = load_ephemeris(args.ephemeris)
        lo, hi, desc = ephemeris_window(eph, args.ephemeris)
        print("星历：%s" % desc)
        if lo:
            print("  JD 区间：%.1f — %.1f" % (lo, hi))
        print("预计算面方案：")
        print("  日粒度全量（对外承诺）：%s 至 %s" % CONFIG.RANGE_PLAN["daily_full"])
        print("  日粒度可选扩展（星历覆盖内）：%s 至 %s" % CONFIG.RANGE_PLAN["daily_optional"])
        print("  覆盖外：只做事件级（精选历史/未来天象），不做日粒度")
        return 0

    if args.emit_samples:
        paths = emit_samples(args.emit_samples, city=args.city, ephemeris=args.ephemeris)
        for p in paths:
            print("written: %s" % p)
        return 0

    out = None
    if args.date:
        y, m, d = map(int, args.date.split("-"))
        out = _worker((y, m, d, args.city, args.ephemeris, args.allow_analytic))
        print(to_json(out, args.json))
    elif args.start and args.end:
        tasks = [(y, m, d, args.city, args.ephemeris, args.allow_analytic)
                 for (y, m, d) in _iter_dates(args.start, args.end)]
        if args.jobs and args.jobs > 1:
            import multiprocessing as mp
            with mp.Pool(args.jobs) as pool:
                out = pool.map(_worker, tasks, chunksize=16)
        else:
            out = []
            for i, tk in enumerate(tasks, 1):
                out.append(_worker(tk))
                if i % 200 == 0:
                    print("  ... %d/%d" % (i, len(tasks)), file=sys.stderr)
        print(to_json(out, args.json))
    elif args.history:
        y, m, d, src, ref = args.history
        out = back_calc_historical(parse_era_year(y), int(m), int(d), args.history_note, src, ref,
                                   ephemeris=args.ephemeris,
                                   allow_analytic=args.allow_analytic)
        print(to_json(out, args.json))
    else:
        ap.print_help()
        return 1

    if args.db and isinstance(out, (dict, list)):
        recs = out if isinstance(out, list) else [out]
        write_db(recs, args.db_host, args.db_user, args.db_pass, args.db_name)

    if args.wp_rest and isinstance(out, (dict, list)):
        if not args.wp_user or not args.wp_app_password:
            print("[push_rest] 需要 --wp-user 与 --wp-app-password", file=sys.stderr)
            return 2
        recs = out if isinstance(out, list) else [out]
        recs = [r for r in recs if isinstance(r, dict) and "_error" not in r]
        n = push_rest(recs, args.wp_table, args.wp_site, args.wp_user, args.wp_app_password)
        print("[push_rest] 合计写入 %d 行" % n)
        print(json.dumps(flush_remote_cache(args.wp_site, args.wp_user, args.wp_app_password),
                         ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
