<?php
/**
 * 数据层：自定义表的定义与建表（指令 02）
 *
 * 本文件是**表结构的唯一正本**：
 *   · 插件激活时由 activation.php 调用 KCJ_Astro_DB::create() 经 dbDelta() 建表；
 *   · sql/install_tables.sql 是同一结构的「可手工导入」版本，二者必须逐列一致
 *     （verify_package.py 有一项专门做 SQL ↔ dbDelta 的列集对拍）。
 *
 * 表（4 张）：
 *   1. {prefix}astro_daily      每日天象（日粒度预计算）
 *   2. {prefix}astro_events     天象事件（未来/历史共用，分支渲染由模板层决定）
 *   3. {prefix}astro_relations  事件关联（古今对照/相关，1NF）
 *   4. {prefix}astro_daily_site 每日天象的**观测地维度**（v2.0.0 新增）
 *
 * ★ v2.0.0（2026-09-23）新增第 4 张表 `astro_daily_site` —— 「观测地可选」的数据面。
 *   为什么不把 city 加进 daily 表：daily 一条记录 40 余项里，**只有 11 项与观测地有关**
 *   （日出/日落/昼长/三种晨昏成对/月出/月落），其余全是地心量（黄经、赤纬、视星等、
 *   入宿、月相、地月距离）。把 daily 乘上城市数会把 5.5 万行变成数百万行、
 *   每行 2—4 KB 的 data_json 跟着翻倍；拆表后每行不到 200 字节。
 *   代价：模板渲染「今日天象」时要多查一次（date_str + city 命中唯一键，单行读）。
 *
 * ★ v1.2.0 相对 v1.1.0 的变更：
 *   - daily 增 special_event_ids（与指令 02 的字段清单对齐）与 created_at；
 *   - relations 增 UNIQUE KEY uk_from_to_rel —— v1.1.0 缺唯一键，
 *     导致 REST 反复导入同一关系会不断插入重复行（幂等性缺陷）；
 *   - 全部表结构的注释统一说明 jd 为 **TT 尺度**（见 compute_sky F17）。
 *
 * ★ v1.2.1（2026-09-23，线上首推暴露的缺陷 F22）：
 *   - `daily.data_version` 与 `events.dt_model` 由 VARCHAR(32) 放宽到 **VARCHAR(64)**。
 *     病根：F17 把 DATA_VERSION 从 `de421+dt_espenak_meeus_2006`（27）改成
 *     `de421+dt_espenak_meeus_2006+tt_scale`（**36**），解析降级行再加 `+analytic`（**45**），
 *     而列宽仍是 32 ⇒ 线上 INSERT 被 MySQL 拒（「提供的值可能太长或包含无效数据」），
 *     表现为 REST 回执 `written:0, failed:1`。列注释里写的就是 36 字符的值，**列宽没跟着改**。
 *   - 新增 **KCJ_ASTRO_SCHEMA**（表结构版本，与插件版本解耦）与文件末尾的
 *     `init` 守卫：option `kcj_astro_schema_version` 与常量不符即跑 dbDelta 增量升级
 *     ⇒ 已建库的站点无需重新激活，**打开任意页面即自动 ALTER**。
 *     （dbDelta 会改列宽：它拿 DESCRIBE 的 Type 做全串比较，varchar(32) !== varchar(64)
 *       且 varchar 不命中 text/blob 向短退让与整数显示宽度两个例外 ⇒ 必定发出 CHANGE COLUMN。
 *       依据：wp-admin/includes/upgrade.php 的 dbDelta()。）
 *
 *   ★ 同批修掉的三个同族缺陷（都属「静默失败」，与 F22 一个家族）：
 *     · F24  activation.php 把 KCJ_ASTRO_VER 写进 `kcj_astro_schema_version`
 *            —— 同一个 option 两处语义不同，取值撞车即永久跳过升级。
 *     · F25  create() **无条件**落账 ⇒ ALTER 一旦失败也被记成「已升级」，
 *            守卫从此不再重试，列宽永远补不上而系统「以为」成功。
 *            现改为：dbDelta 之后**逐列实测**列宽，达标才落账；不达标记
 *            `kcj_astro_schema_error` 且**不写版本**，留给下一次请求重试。
 *     · F26  /health 不暴露表结构状态 ⇒ 只能靠「推一行数据看报不报错」试错判断
 *            升级成没成。现由 schema_status() 直接给出 option 值、期望值、
 *            实测列宽与缺口清单。
 *
 * ★ v2.2.6（2026-09-23，线上第二次「推数据才发现的静默失败」F27）：
 *   `events.time_uncertainty` 由 VARCHAR(64) 放宽到 **VARCHAR(191)**。
 *   病根与 F22（列宽）**同一个家族、但不是同一个错**：
 *     · F22 是「声明的列宽 < 真值字符数」（32 < 36），改宽即可；
 *     · F27 是「声明的列宽 < 真值的**字节数**」（64 < **159**）——
 *       真值「±数小时（极大时刻为 λ☉ 锚点下的**理论值**；主要不确定度是实际峰值相对理论的
 *       偏离，逐年不同，非 ΔT 不确定度）」只有 **60 字符**，字符数是够的；159 字节才超。
 *       而 WordPress 的 `wpdb::strip_invalid_text()` 在**字符集为单字节**（latin1）或
 *       **值恰为纯 ASCII** 时**按字节**截断（`strlen`/`substr`）⇒ 159 > 64 被截 ⇒
 *       `$data !== $converted_data` ⇒ 整行被拒，报「处理以下字段的值失败」。
 *     表现：4,672 行**全部** written=0 / failed=4672，而页面只显示一句没有数字的通用错误。
 *   ⇒ 本次同时补三样东西，缺一即复发：
 *     ① 列宽放宽到 **191**（≥159 字节、≥60 字符，**两种口径都通过**）——
 *        选 191 而不是 255/TEXT，是沿用本项目 `slug`/`obs_site` 的既有口径，
 *        且 utf8mb4 下 191 是索引安全上限，不会引入新的行外存储；
 *     ② `min_widths()` 纳入该列 —— 事故列原先**不在监视面内**，
 *        所以「表结构就绪、列宽达标」那句话是真的、却没有覆盖到事故列；
 *     ③ 新增 `includes/col-budget.php`：写入前按 **WordPress 自己的口径**
 *        （`$wpdb->get_col_length()` ＋ `get_col_charset()`）逐字段预检，
 *        超限时直接报出「字段 / 值长（字符＋字节）/ 上限 / 按什么计 / 实际列类型」，
 *        不再让调用方去读核心源码反推。
 *
 * 命名：类名带下划线而非 WP 风格的 class-xxx.php 内 PascalCase，是照指令 02 的文件名，
 *       但类名沿用项目既有的 KCJ_ 前缀，避免与其它插件撞名。
 */

if (!defined('ABSPATH')) {
    exit;
}

class KCJ_Astro_DB {

    /** 逻辑表名 → 物理表名（不含前缀） */
    const TABLES = array('daily', 'events', 'relations', 'daily_site');

    /** 物理表名（含前缀） */
    public static function table($name) {
        global $wpdb;
        if (!in_array($name, self::TABLES, true)) {
            return null;
        }
        return $wpdb->prefix . 'astro_' . $name;
    }

    /** 三张表的建表语句（dbDelta 要求的格式：每行独立、KEY 前加空格、末尾无逗号） */
    public static function schema() {
        global $wpdb;
        $charset = $wpdb->get_charset_collate();
        $p       = $wpdb->prefix;

        $sql_daily = "CREATE TABLE {$p}astro_daily (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            date_str VARCHAR(10) NOT NULL,
            jd DOUBLE NOT NULL,
            data_json LONGTEXT NOT NULL,
            data_version VARCHAR(64) NOT NULL DEFAULT 'v1',
            method VARCHAR(32) NOT NULL DEFAULT 'ephemeris_de421',
            special_event_ids VARCHAR(255) NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY  (id),
            UNIQUE KEY uk_jd (jd),
            UNIQUE KEY uk_date_str (date_str),
            KEY idx_method (method)
        ) $charset;";

        $sql_events = "CREATE TABLE {$p}astro_events (
            event_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            event_type VARCHAR(32) NOT NULL,
            jd_core DOUBLE NOT NULL,
            event_time_bj DATETIME NULL,
            time_uncertainty VARCHAR(191) NULL,
            dt_model VARCHAR(64) NULL,
            post_id BIGINT UNSIGNED NULL,
            title VARCHAR(255) NOT NULL,
            slug VARCHAR(191) NOT NULL,
            summary TEXT NULL,
            params_json LONGTEXT NULL,
            obs_guide TEXT NULL,
            obs_site VARCHAR(191) NULL,
            literature TEXT NULL,
            discussion TEXT NULL,
            source_ref TEXT NULL,
            method VARCHAR(32) NULL,
            ephemeris VARCHAR(191) NULL,
            publish_status TINYINT NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY  (event_id),
            UNIQUE KEY uk_slug (slug),
            KEY idx_jd_core (jd_core),
            KEY idx_event_type (event_type),
            KEY idx_type_status_jd (event_type, publish_status, jd_core),
            KEY idx_post_id (post_id)
        ) $charset;";

        $sql_relations = "CREATE TABLE {$p}astro_relations (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            from_event BIGINT UNSIGNED NOT NULL,
            to_event BIGINT UNSIGNED NOT NULL,
            rel_type VARCHAR(32) NOT NULL,
            PRIMARY KEY  (id),
            UNIQUE KEY uk_from_to_rel (from_event, to_event, rel_type),
            KEY idx_from_rel (from_event, rel_type),
            KEY idx_to_event (to_event)
        ) $charset;";

        // ★ v2.0.0：观测地维度表。键 (date_str, city) 唯一 ⇒ 同一日同一城重导走更新。
        //   列全部显式列出（不用 data_json 大字段）：校验器可直接做 SQL ↔ dbDelta 逐列对拍，
        //   模板也能直接取值，不必再多一层 JSON 解析。
        $sql_daily_site = "CREATE TABLE {$p}astro_daily_site (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            date_str VARCHAR(10) NOT NULL,
            city VARCHAR(32) NOT NULL,
            city_cn VARCHAR(32) NOT NULL,
            lat DOUBLE NOT NULL,
            lon DOUBLE NOT NULL,
            elev_m DOUBLE NOT NULL,
            tz VARCHAR(16) NOT NULL DEFAULT 'UTC+8',
            sunrise_bj VARCHAR(8) NULL,
            sunset_bj VARCHAR(8) NULL,
            day_length_min SMALLINT NULL,
            tw_civil_begin VARCHAR(8) NULL,
            tw_civil_end VARCHAR(8) NULL,
            tw_nautical_begin VARCHAR(8) NULL,
            tw_nautical_end VARCHAR(8) NULL,
            tw_astro_begin VARCHAR(8) NULL,
            tw_astro_end VARCHAR(8) NULL,
            moonrise_bj VARCHAR(8) NULL,
            moonset_bj VARCHAR(8) NULL,
            method VARCHAR(32) NOT NULL DEFAULT 'ephemeris_de421',
            data_version VARCHAR(64) NOT NULL DEFAULT 'v1',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY  (id),
            UNIQUE KEY uk_date_city (date_str, city),
            KEY idx_city_date (city, date_str)
        ) $charset;";

        return array(
            'daily'     => $sql_daily,
            'events'    => $sql_events,
            'relations' => $sql_relations,
            'daily_site' => $sql_daily_site,
        );
    }

    /**
     * 字符型列的**最小宽度要求**（升级后逐列实测的依据）。
     * 只登记「曾因装不下真值而出过事故」的列，不做全表普查——
     * 全表普查留给 verify_package.py 的静态对拍（那才是它该管的）。
     */
    public static function min_widths() {
        return array(
            'daily'      => array('data_version' => 64),
            // ★ v2.2.6：加入 `time_uncertainty`（191）。它是本轮 F27 的事故列：
            //   v1.x 声明 VARCHAR(64)，而真值是「±数小时（极大时刻为 λ☉ 锚点下的**理论值**；
            //   主要不确定度是实际峰值相对理论的偏离，逐年不同，非 ΔT 不确定度）」
            //   —— **60 字符 / 159 字节**。4,672 行因此**全部**被 wpdb 拒收（详见本文件 v2.2.6 说明）。
            //   ⚠ 这一列原先**不在监视面内**，所以「表结构就绪、列宽达标」是真的、但覆盖面不足。
            'events'     => array('dt_model' => 64, 'time_uncertainty' => 191, 'ephemeris' => 191),
            // v2.0.0：新表沿用同一个版本号常量，宽度要求一致（36 字符 / 降级行 45 字符）
            'daily_site' => array('data_version' => 64),
        );
    }

    /** 实测某列的字符宽度（varchar(N) 的 N）；列不存在或非字符型返回 null。 */
    public static function column_width($table, $column) {
        $m = self::column_meta($table, $column);
        if ($m === null) {
            return null;
        }
        if (preg_match('/^(?:var)?char\((\d+)\)/i', $m['type'], $mm)) {
            return (int) $mm[1];
        }
        return null;   // text / longtext 等不设上限，视为不设限
    }

    /**
     * 某列的**实况元信息**（v2.2.6 新增）。
     * 为什么要有它：本轮 F27 卡在「列宽 64、值 159 字节」上，而当时站外**看不到**
     * 服务器上那一列的真实类型与字符集 —— 只能靠推。SHOW FULL COLUMNS 是这类问题的
     * 唯一实况来源（`Type` 给 varchar(191)，`Collation` 给字符集），故单独成一个方法，
     * 供列宽守卫、字段长度预检与公开信标三方共用（一处定义、三处读数一致）。
     */
    public static function column_meta($table, $column) {
        global $wpdb;
        $tbl = self::table($table);
        if (!$tbl) {
            return null;
        }
        $row = $wpdb->get_row($wpdb->prepare("SHOW FULL COLUMNS FROM {$tbl} LIKE %s", $column));
        if (!$row || !isset($row->Type)) {
            return null;
        }
        return array(
            'type'      => (string) $row->Type,
            'collation' => isset($row->Collation) ? (string) $row->Collation : '',
            'nullable'  => isset($row->Null) ? (string) $row->Null : '',
            'key'       => isset($row->Key) ? (string) $row->Key : '',
            'extra'     => isset($row->Extra) ? (string) $row->Extra : '',
        );
    }

    /**
     * 整表的列实况（v2.2.6）—— 公开信标用它把「服务器上这一列到底什么样」一次摊开。
     * ★ 只报事实、不作判断：判断留给列宽守卫与字段长度预检，免得两处口径漂移。
     */
    public static function all_columns($table) {
        global $wpdb;
        $tbl = self::table($table);
        if (!$tbl) {
            return array();
        }
        $rows = $wpdb->get_results("SHOW FULL COLUMNS FROM {$tbl}", ARRAY_A);
        if (!is_array($rows)) {
            return array();
        }
        $out = array();
        foreach ($rows as $r) {
            $name = isset($r['Field']) ? (string) $r['Field'] : '';
            if ($name === '') {
                continue;
            }
            $out[$name] = array(
                'type'      => isset($r['Type']) ? (string) $r['Type'] : '',
                'collation' => isset($r['Collation']) ? (string) $r['Collation'] : '',
                'nullable'  => isset($r['Null']) ? (string) $r['Null'] : '',
                'key'       => isset($r['Key']) ? (string) $r['Key'] : '',
            );
        }
        return $out;
    }

    /** 逐列实测：返回未达标清单 array('daily.data_version' => 'varchar(32) < 需要 64')。 */
    public static function width_shortfalls() {
        $bad = array();
        foreach (self::min_widths() as $t => $cols) {
            foreach ($cols as $c => $min) {
                $w = self::column_width($t, $c);
                if ($w === null) {
                    // 列缺失或非字符型：读不到就当未达标，宁可重试也不要静默放过
                    $bad[$t . '.' . $c] = "读不到列宽（列缺失或非字符型），需要 {$min}";
                } elseif ($w < $min) {
                    $bad[$t . '.' . $c] = "varchar({$w}) < 需要 {$min}";
                }
                // 达标（$w >= $min）不加入 —— 这一点必须写成独立分支，
                // 不能用「先无条件赋值再过滤」的写法：那样达标项也会留在清单里，
                // 列宽永远判为不合格，守卫便每次请求都跑一遍 dbDelta。
                // （等价逻辑在 verify_package.py: width_shortfalls_py()，配两向负控制。）
            }
        }
        return $bad;
    }

    /**
     * 表结构状态（供 REST /health 与后台自检直接读数，F26）。
     * ok 为真 = option 已落账 **且** 关键列宽实测达标。
     */
    public static function schema_status() {
        $cur = get_option('kcj_astro_schema_version');
        $bad = self::width_shortfalls();
        return array(
            'option'     => ($cur === false ? null : (string) $cur),
            'expected'   => (string) KCJ_ASTRO_SCHEMA,
            'ok'         => ($cur === KCJ_ASTRO_SCHEMA && !$bad),
            'widths'     => array(
                'daily.data_version'      => self::column_width('daily', 'data_version'),
                'events.dt_model'         => self::column_width('events', 'dt_model'),
                // ★ v2.2.6（F27）：这一列原先**不在监视面内**，于是 repair 报「列宽达标」
                //   是一句真话、却对本次事故毫无覆盖面 —— 事故列恰恰是唯一没被看的那个。
                'events.time_uncertainty' => self::column_width('events', 'time_uncertainty'),
                'daily_site.data_version' => self::column_width('daily_site', 'data_version'),
            ),
            'shortfalls' => $bad,
            'error'      => get_option('kcj_astro_schema_error', null),
        );
    }

    /** 建表 / 增量升级（dbDelta 幂等）。返回已建的表名数组。 */
    public static function create() {
        require_once ABSPATH . 'wp-admin/includes/upgrade.php';
        global $wpdb;
        $done = array();
        $cerr = array();

        foreach (self::schema() as $name => $sql) {
            $tbl = self::table($name);
            dbDelta($sql);

            // ★★ v2.2.4：**dbDelta 认不出的 DDL 会被它静默跳过** —— 缺表即改直连建表。
            //   为什么必须补这一手（本轮线上的头号嫌疑）：dbDelta 不是「照 SQL 执行」，
            //   而是**先解析** DDL 再与现状比对。解析器认不出的部分它**不报错、只是不做**。
            //   于是会出现「4 张表里 3 张建好、第 4 张永远缺着」，而调用方看不到任何异常：
            //     · init 守卫那边：width_shortfalls() 会因为「列读不到」而判不合格 ⇒
            //       不写 schema option ⇒ **每次请求都重跑一遍 dbDelta**（白跑，且永远不成功）；
            //     · 后台导入页那边：「一键全部」的顺序是**按清单**走的，
            //       `daily_site` 排在第 2 位 ⇒ 前置检查一报错就**中断整条链** ⇒
            //       排在它后面的数据集**永远轮不到**（历史栏因此一直空着）。
            //   故此处：**只对「确实不存在」的表**改用直连 `CREATE TABLE IF NOT EXISTS`，
            //   并把 $wpdb->last_error 记进 schema_error，让页面能把它显示出来。
            //   已存在的表不动 —— 列宽升级仍由 dbDelta 负责（那是它的强项）。
            if ($wpdb->get_var($wpdb->prepare('SHOW TABLES LIKE %s', $tbl)) !== $tbl) {
                $if_sql = preg_replace('/^CREATE\s+TABLE\s+/i', 'CREATE TABLE IF NOT EXISTS ', $sql);
                $wpdb->query($if_sql);
                if ($wpdb->get_var($wpdb->prepare('SHOW TABLES LIKE %s', $tbl)) !== $tbl) {
                    $cerr[$tbl] = '直连建表也失败：'
                        . ($wpdb->last_error !== '' ? $wpdb->last_error : '（数据库未返回错误信息）');
                }
            }
            $done[] = $tbl;
        }

        // ★ F25（v1.2.1 修）：dbDelta 跑完 ≠ 改成了。必须**实测**再记账。
        //   无条件记账的后果：ALTER 一旦失败，option 已被写上 ⇒ init 守卫从此
        //   永不再试 ⇒ 列宽永远补不上，而 /health 却显示「已升级」（静默失败）。
        $bad = self::width_shortfalls();
        // 直连建表的错误与列宽缺口合并记账：两者都属「表结构没就绪」，分开报会漏。
        $all = array_merge($cerr, $bad);
        if ($all) {
            update_option('kcj_astro_schema_error', array(
                'at'   => current_time('mysql'),
                'want' => (string) KCJ_ASTRO_SCHEMA,
                'bad'  => $all,
            ), false);
            return $done;   // 不写版本 ⇒ 下一次请求的 init 守卫会再试
        }
        delete_option('kcj_astro_schema_error');
        update_option('kcj_astro_schema_version', KCJ_ASTRO_SCHEMA);
        return $done;
    }

    /** 三张表是否都已存在（REST /health 与后台自检用） */
    public static function health() {
        global $wpdb;
        $out = array();
        foreach (self::TABLES as $t) {
            $tbl    = self::table($t);
            $exists = $wpdb->get_var($wpdb->prepare('SHOW TABLES LIKE %s', $tbl));
            $out[$t] = array(
                'table'  => $tbl,
                'exists' => ($exists === $tbl),
                'rows'   => ($exists === $tbl) ? (int) $wpdb->get_var("SELECT COUNT(*) FROM {$tbl}") : null,
            );
        }
        return $out;
    }

    /** 最新一条日记录的 date_str（数据新鲜度检查用；无数据返回 null） */
    public static function latest_daily_date() {
        global $wpdb;
        $tbl = self::table('daily');
        return $wpdb->get_var("SELECT date_str FROM {$tbl} ORDER BY jd DESC LIMIT 1");
    }

    /**
     * 重建 relations：把某个源事件的关系整表替换为给定集合（幂等）。
     * $pairs 形如 array( array('to'=>123,'type'=>'same_type'), ... )
     */
    public static function replace_relations($from_event, $pairs) {
        global $wpdb;
        $tbl = self::table('relations');
        $from_event = (int) $from_event;
        if ($from_event <= 0) {
            return 0;
        }
        $wpdb->delete($tbl, array('from_event' => $from_event));
        $n = 0;
        foreach ((array) $pairs as $pr) {
            $to   = isset($pr['to']) ? (int) $pr['to'] : 0;
            $type = isset($pr['type']) ? sanitize_key($pr['type']) : '';
            if ($to <= 0 || $type === '' || $to === $from_event) {
                continue;
            }
            $wpdb->insert($tbl, array(
                'from_event' => $from_event,
                'to_event'   => $to,
                'rel_type'   => $type,
            ));
            $n++;
        }
        return $n;
    }
}


/**
 * ── 表结构增量升级守卫（v1.2.1 新增）─────────────────────────────
 * 背景：v1.2.0 交付后线上首推失败——`data_version` 列宽仍是 32，
 *       而版本号值是 36 字符，MySQL 直接拒收（written:0 / failed:1）。
 *       当时**没有任何机制**会把已建库的旧列宽带上来：dbDelta 只在激活钩子里跑。
 *
 * 做法：表结构版本单列常量 KCJ_ASTRO_SCHEMA，与插件版本解耦。
 *       每个请求比对一次 option（autoload，命中即内存数组，代价可忽略）；
 *       不一致才跑 dbDelta（dbDelta 本身幂等，只会 ALTER 有差异的列）。
 *
 * 失败语义（F25）：create() 只在**实测列宽达标**后才更新 option
 *       ⇒ ALTER 没生效就保持旧值，下一次请求继续尝试（自我修复，不会卡死）；
 *       同时把缺口写进 option `kcj_astro_schema_error`，由 /health 的
 *       schema.error / schema.shortfalls 直接可读，不必靠推数据试错（F26）。
 *       成功一次即落账，此后每个请求只多一次 get_option —— 成本可忽略。
 *
 * 注意：不要在 admin 之外刻意开真实 cron 任务；本守卫靠正常页面请求触发即可。
 */
add_action('init', function () {
    if (get_option('kcj_astro_schema_version') !== KCJ_ASTRO_SCHEMA) {
        KCJ_Astro_DB::create();
    }
}, 1);
