-- =============================================================================
-- 天象预报模块 · 建表 SQL（交付物 A）
-- 站点：kuangchujia.com ｜ 适用 WordPress 自定义表（前缀 wp_，可用变量替换）
-- 依据：《WordPress 站点天象模块落地指令集》指令 02 + 需求文档 V2.0 §四
-- 正本关系：**本文件与插件内 includes/class-astro-db.php 必须逐列一致**；
--           dbDelta 版本在插件里（激活时自动执行），本文件供 DBA 手工导入或核对。
--           verify_package.py 有一项专做「SQL ↔ dbDelta 列集对拍」。
-- 字符集：utf8mb4 / utf8mb4_unicode_ci（支持生僻汉字）
-- 引擎：InnoDB
--
-- ★ v1.2.0 相对 v1.1.0 的变更（均为幂等性/可追溯性修复）：
--   1. daily 增 `special_event_ids`（与指令 02 的字段清单对齐）与 `created_at`；
--   2. daily 的 `date_str` 由普通索引改为 **UNIQUE**：
--      v1.1.0 只有 jd 唯一，导致同一日期在 jd 被修正后重导会**插出第二行**（同一天两条）。
--   3. relations 增 **UNIQUE uk_from_to_rel**：v1.1.0 无唯一键，
--      REST 反复导入同一关系会无限追加重复行。
--   4. events 增 `obs_site`（观测地）与 created_at/updated_at。
--   5. 全部 jd 列注释明确为 **TT 尺度**（见 compute_sky.py 的 F17 修正）。
--
-- ★ v1.2.1（2026-09-23）相对 v1.2.0 —— 修 F22「列宽溢出」：
--   `data_version` 与 `dt_model` 由 VARCHAR(32) 放宽到 **VARCHAR(64)**。
--   原因：F17 把版本号从 27 字符改成 36 字符（解析降级行 45 字符），列宽未同步
--   ⇒ 线上 REST 导入被 MySQL 拒收，回执 written:0 / failed:1。
--   ⚠ 已建库的站点：插件 v1.2.1 首次访问会经 dbDelta 自动 ALTER，无需手工执行。
--   ★ 同批修 F23：`event_type` 本文件原为 ENUM(...)，而 dbDelta 正本是 VARCHAR(32)
--     —— 两份「必须逐列一致」的正本类型不同，而 v1.2.0 的校验器只比列名，故一直没暴露。
--     现统一为 **VARCHAR(32)**（以 dbDelta 为准，它才是真正建表的那份；线上表本来就是 VARCHAR）。
--     原 ENUM 的取值清单移入 COMMENT，信息不丢。新增「列类型/列宽逐列一致」判据防复发。
--
-- ★ v2.2.6（2026-09-23）—— 修 F27「列宽小于真值**字节数**」：
--   `events.time_uncertainty` 由 VARCHAR(64) 放宽到 **VARCHAR(191)**。
--   与 F22 同族但不同错：F22 是声明宽度 < 真值**字符数**（32 < 36）；F27 是声明宽度
--   < 真值**字节数**（64 < 159）—— 真值「±数小时（极大时刻为 λ☉ 锚点下的**理论值**；
--   主要不确定度是实际峰值相对理论的偏离，逐年不同，非 ΔT 不确定度）」实测
--   **60 字符 / 159 字节**，字符数够、字节数不够。WordPress 的 wpdb 在字符集为
--   单字节（latin1）或值恰为纯 ASCII 时**按字节**截断 ⇒ 截断即判该行写入失败，
--   4,672 行全部 written=0 / failed=4672。
--   放宽到 191 的理由：191 ≥ 159（字节）且 ≥ 60（字符），**两种口径同时通过**；
--   191 又与 slug / obs_site 的既有口径一致，且是 utf8mb4 下的索引安全上限。
--   ⚠ 已建库的站点：插件 v2.2.6 首次访问会经 dbDelta 自动 ALTER，无需手工执行。
--
-- ★ v2.0.0（2026-09-23）相对 v1.2.1 —— 新增**表 4** `wp_astro_daily_site`：
--   把「日出/日落/昼长/三种晨昏/月出/月落」这 11 项与观测地有关的量单独成表，
--   支撑「今日天象 · 观测地默认为 IP 当地并可选」（38 城）。
--   本表不动 daily / events / relations 的任何列，**纯增量**：
--   已建库站点由 init 守卫跑 dbDelta 自动建表，无需手工执行 SQL。
--   同批：events 的注释补上「同类型亦可为历史侧」，并由接口层的 side 属性
--   把「未来预告」与「历史回溯」分开取数（见 includes/shortcodes.php）。
-- =============================================================================

SET NAMES utf8mb4;

-- -----------------------------------------------------------------------------
-- 表 1：wp_astro_daily —— 每日天象（日粒度）
--   预计算面（见 docs/milestones.md「预计算面分档」）：
--     承诺档 1900-01-01 至 2050-12-31（≈5.5 万天；实测约 0.25 s/日，4 进程约 1 小时）。
--   不再声称「5000 年 × 365 天全量」：实测约 128 CPU·小时，对个人站不可行。
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `wp_astro_daily` (
  `id`                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `date_str`          VARCHAR(10)     NOT NULL                COMMENT '展示用日期 YYYY-MM-DD；公元前记作 XXXXBC（如 0720BC）。唯一：一日一条',
  `jd`                DOUBLE          NOT NULL                COMMENT '儒略日，**TT 尺度**（JDE）。用于公元前/后范围查询与排序；UT 尺度另见 data_json.jd_ut',
  `data_json`         LONGTEXT        NOT NULL                COMMENT '当日太阳/月球/五大行星/二十八宿宿度的完整 JSON（约 2—4 KB/条）',
  `data_version`      VARCHAR(64)     NOT NULL DEFAULT 'v1'   COMMENT '算法/星历/ΔT 模型版本号（如 de421+dt_espenak_meeus_2006+tt_scale）；支持增量重算与旧版追溯',
  `method`            VARCHAR(32)     NOT NULL DEFAULT 'ephemeris_de421' COMMENT '计算方法：ephemeris_de421（星历精算）/ analytic_meeus（覆盖外解析降级）',
  `special_event_ids` VARCHAR(255)    NULL                    COMMENT '当日特殊天象的事件 ID（逗号分隔，指向 wp_astro_events.event_id）',
  `created_at`        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '首次写入时间',
  `updated_at`        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最近一次写入/重算时间',

  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_jd` (`jd`)              COMMENT '儒略日唯一，避免重复写入',
  UNIQUE KEY `uk_date_str` (`date_str`)  COMMENT '日期唯一：同一日期重导走更新而非新插（幂等）',
  KEY `idx_method` (`method`)            COMMENT '筛出走了解析降级的行'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='每日天象主表（太阳/月球/五星/宿度按日期预计算存储）';

-- -----------------------------------------------------------------------------
-- 表 2：wp_astro_events —— 未来/历史天象事件
--   事件展示为 WP 原生 astro_event 文章，由 post_id 关联；表为权威数据源。
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `wp_astro_events` (
  `event_id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `event_type`        VARCHAR(32)     NOT NULL                COMMENT '天象类型（与分类法 event_type 的 term slug 一致）：solar_eclipse / lunar_eclipse / planet / meteor / traditional / historical',
  `jd_core`           DOUBLE          NOT NULL                COMMENT '事件核心时刻儒略日，**TT 尺度**（排序/范围用）',
  `event_time_bj`     DATETIME        NULL                    COMMENT '北京时间（UTC+8）展示值；古代事件可为 NULL',
  `time_uncertainty`  VARCHAR(191)    NULL                    COMMENT '时间不确定度区间（历史事件必填，如 ±30min～±2h）；近未来为 NULL。★ v2.2.6 由 VARCHAR(64) 放宽：真值最长 60 字符/**159 字节**，而 wpdb 在单字节字符集或纯 ASCII 值时按**字节**截断 ⇒ 64 装不下（F27）',
  `dt_model`          VARCHAR(64)     NULL                    COMMENT '所用 ΔT 模型版本（历史事件必填）',
  `post_id`           BIGINT UNSIGNED NULL                    COMMENT '关联的 WordPress 文章 ID（astro_event CPT）；无则 NULL',
  `title`             VARCHAR(255)    NOT NULL                COMMENT '页面标题',
  `slug`              VARCHAR(191)    NOT NULL                COMMENT 'URL 别名（唯一索引）',
  `summary`           TEXT            NULL                    COMMENT '摘要（纯天文描述，不含星占谶纬）',
  `params_json`       LONGTEXT        NULL                    COMMENT '全套参数（食分/可见带/辐射点/ZHR/坐标等）',
  `obs_guide`         TEXT            NULL                    COMMENT '观测指南（仅未来天象）',
  `obs_site`          VARCHAR(191)    NULL                    COMMENT '观测地 / 坐标口径（如「揭阳 23.35N 116.36E」）',
  `literature`        TEXT            NULL                    COMMENT '文献原文与规范出处（仅历史天象，逐字核对）',
  `discussion`        TEXT            NULL                    COMMENT '史料辨析/多学派观点（仅历史天象，不下绝对定论）',
  `source_ref`        TEXT            NULL                    COMMENT '规范出处引用 + 可选 DOI',
  `method`            VARCHAR(32)     NULL                    COMMENT '计算方法：ephemeris_de421 / analytic_meeus（历史事件须标）',
  `ephemeris`         VARCHAR(191)    NULL                    COMMENT '星历档与覆盖区间（如 de421.bsp（1899-07-28 至 2053-10-08））。★ v2.2.6 由 VARCHAR(96) 放宽：降级态真值「未使用（de421.bsp（1899-07-28 至 2053-10-08） 覆盖之外，已降级为 Meeus 解析式）」= 59 字符/**99 字节** > 96，属 F27 同类潜伏项'
  `publish_status`    TINYINT         NOT NULL DEFAULT 0      COMMENT '0=草稿 1=已发布',
  `created_at`        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '首次写入时间',
  `updated_at`        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最近一次写入时间',

  PRIMARY KEY (`event_id`),
  UNIQUE KEY `uk_slug` (`slug`)                       COMMENT 'URL 别名唯一',
  KEY `idx_jd_core` (`jd_core`)                       COMMENT '按核心时刻排序/范围',
  KEY `idx_event_type` (`event_type`)                 COMMENT '按类型过滤（Tab 分流）',
  KEY `idx_type_status_jd` (`event_type`, `publish_status`, `jd_core`) COMMENT 'Tab 列表查询复合索引（覆盖 WHERE+ORDER BY）',
  KEY `idx_post_id` (`post_id`)                       COMMENT '按 WP 文章反查'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='天象事件表（未来/历史共用，分支渲染由模板层决定）';

-- -----------------------------------------------------------------------------
-- 表 3：wp_astro_relations —— 事件关联（1NF）
--   替代逗号拼接的 related_future_ids / related_hist_ids 字段。
--   唯一键 (from_event,to_event,rel_type) 是 REST 反复导入仍幂等的保证。
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `wp_astro_relations` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `from_event` BIGINT UNSIGNED NOT NULL                COMMENT '源事件 ID（wp_astro_events.event_id）',
  `to_event`   BIGINT UNSIGNED NOT NULL                COMMENT '目标事件 ID',
  `rel_type`   VARCHAR(32)     NOT NULL                COMMENT 'same_type=同类型古今对照 / related=相关',

  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_from_to_rel` (`from_event`, `to_event`, `rel_type`) COMMENT '同一关系只存一条（幂等）',
  KEY `idx_from_rel` (`from_event`, `rel_type`) COMMENT '按源事件+关系类型查古今对照',
  KEY `idx_to_event`  (`to_event`)              COMMENT '反向查被关联事件'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='天象关联表（古今对照/相关，1NF 规范）';

-- -----------------------------------------------------------------------------
-- 表 4：wp_astro_daily_site —— 每日天象的**观测地维度**（v2.0.0 新增）
--   为什么单独一张表：daily 一条记录 40 余项里只有 11 项与观测地有关
--   （日出/日落/昼长/民用·航海·天文三种晨昏成对/月出/月落），其余是地心量。
--   若把 city 加进 daily，5.5 万行 × N 城 × 每行 2—4 KB 的 data_json 会爆；
--   拆表后每行不到 200 字节，38 城 × 770 天（滚动窗）≈ 2.9 万行。
--   唯一键 (date_str, city) ⇒ 同一日同一城重导走更新（幂等）。
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `wp_astro_daily_site` (
  `id`                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `date_str`          VARCHAR(10)     NOT NULL                COMMENT '展示用日期 YYYY-MM-DD（与 daily.date_str 同口径，便于联查）',
  `city`              VARCHAR(32)     NOT NULL                COMMENT '观测地键（与 compute_sky.CONFIG.CITIES 的键一致，如 jieyang/beijing）',
  `city_cn`           VARCHAR(32)     NOT NULL                COMMENT '观测地中文名（如 揭阳）',
  `lat`               DOUBLE          NOT NULL                COMMENT '观测地纬度（度，北纬为正）',
  `lon`               DOUBLE          NOT NULL                COMMENT '观测地经度（度，东经为正）',
  `elev_m`            DOUBLE          NOT NULL                COMMENT '海拔（米），影响升落的数十秒量级',
  `tz`                VARCHAR(16)     NOT NULL DEFAULT 'UTC+8' COMMENT '展示用时区口径；升落时刻均为该时区的钟表时',
  `sunrise_bj`        VARCHAR(8)      NULL                    COMMENT '日出（HH:MM）；覆盖外为 NULL',
  `sunset_bj`         VARCHAR(8)      NULL                    COMMENT '日落（HH:MM）',
  `day_length_min`    SMALLINT        NULL                    COMMENT '昼长（分钟）',
  `tw_civil_begin`    VARCHAR(8)      NULL                    COMMENT '民用晨光始（太阳高度 -6°）',
  `tw_civil_end`      VARCHAR(8)      NULL                    COMMENT '民用昏影终（-6°）',
  `tw_nautical_begin` VARCHAR(8)      NULL                    COMMENT '航海晨光始（-12°）',
  `tw_nautical_end`   VARCHAR(8)      NULL                    COMMENT '航海昏影终（-12°）',
  `tw_astro_begin`    VARCHAR(8)      NULL                    COMMENT '天文晨光始（-18°）',
  `tw_astro_end`      VARCHAR(8)      NULL                    COMMENT '天文昏影终（-18°）',
  `moonrise_bj`       VARCHAR(8)      NULL                    COMMENT '月出（HH:MM）；当日不出或不出现在该日则为 NULL',
  `moonset_bj`        VARCHAR(8)      NULL                    COMMENT '月落（HH:MM）',
  `method`            VARCHAR(32)     NOT NULL DEFAULT 'ephemeris_de421' COMMENT '计算方法：ephemeris_de421 / out_of_range_no_rise_set',
  `data_version`      VARCHAR(64)     NOT NULL DEFAULT 'v1'   COMMENT '算法/星历/ΔT 模型版本号（与 daily 同源）',
  `created_at`        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '首次写入时间',
  `updated_at`        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最近一次写入/重算时间',

  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_date_city` (`date_str`, `city`) COMMENT '同一日同一城唯一（重导走更新而非新插）',
  KEY `idx_city_date` (`city`, `date_str`)       COMMENT '按城市取某日之前的记录（报告聚合用）'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='每日天象的观测地维度（升落与晨昏；地心量仍在 wp_astro_daily）';

-- -----------------------------------------------------------------------------
-- 激活/迁移说明：
--   · 插件端请用 dbDelta（"存在即增量升级"）；dbDelta 要求：每行独立、
--     KEY 前加空格、字段名前后无反引号（本文件的注释版反引号仅供手工执行）。
--   · 从 v1.1.0 升级：`uk_date_str` 与 `uk_from_to_rel` 是**新增唯一键**。
--     若表内已有重复行（v1.1.0 的重复导入所致），加唯一键会失败；
--     先按下列语句清理，再激活插件：
--       DELETE a FROM wp_astro_daily a JOIN wp_astro_daily b
--         ON a.date_str = b.date_str AND a.id > b.id;
--       DELETE a FROM wp_astro_relations a JOIN wp_astro_relations b
--         ON a.from_event=b.from_event AND a.to_event=b.to_event
--            AND a.rel_type=b.rel_type AND a.id > b.id;
--   · **jd 尺度变更提醒（F17）**：v1.1.0 的解析降级行把 UT 儒略日当 TT 用了，
--     古代行偏差可达数小时。v1.2.0 已修；若曾用 v1.1.0 导入过 1900 年以前
--     或 2053 年以后的数据，请**重导**这些日期（date_str 唯一键保证是更新而非新增）。
-- -----------------------------------------------------------------------------
