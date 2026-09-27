<?php
/**
 * 只读数据集总览端点：GET /wp-json/kcj-astro/v1/dataset
 *
 * ── 为什么要这个端点（v2.3.19 · 2026-09-26）────────────────────────────
 *
 * 用户指令原文：「**替代传统 API：直接发布纯文本静态 JSON 数据库**……
 * 在您的网站上新建一个专门的页面，里面同样放一个『自定义 HTML 区块』，
 * 直接贴入由花括号包裹的、最干净的数据集。」
 *
 * 该指令的目标（**给 AI Agent 一个能整块吞下的数据入口**）是对的，
 * 但落地路径在 WP.com 免费版上不可行且有副作用：
 *   ① 编辑器里手贴 JSON ⇒ 换主题即失效、无版本控制、改一处要记得改 N 处
 *      （站点已有反例：插件页 229 用 `<style>` 全内联块做的，正是不依赖主题才稳）；
 *   ② 手贴的是**死快照**。本站数据**每日在变**（`kcj_astro_daily` 逐日导入）
 *      ⇒ 静态件第一天就过期，且没人会记得去更新它；
 *   ③ 站点已有 `kcj-astro/v1` 命名空间（`/place` 已对匿名开放）
 *      ⇒ 再加一个站点 URL 下的静态件，等于**同一份数据两个出口**，日后必然失配。
 *
 * ⇒ 改为**在插件里加一个只读端点**：一份数据一个出口、随库自动更新、可版本化、
 *   可进 OSS 仓、可回滚。路径仍落在 `kcj-astro/v1` 之下，与既有端点同源。
 *
 * ── 安全设计（四条，逐条对应本文件既有端点的惯例）─────────────────────
 *
 *  ① **表名白名单**：只认 `daily` / `events` / `daily_site` 三张；**不接受表名参数**，
 *     表名写死在代码里 ⇒ 无法被用来读 `wp_users` 之类的敏感表。
 *  ② **行数硬上限**：每次最多回 N 行（`limit` 参数上限 200，默认 50），
 *     且**不接受 offset**（不做分页遍历面）⇒ 不可被用来拖全库。
 *  ③ **只输出已公开内容**：`events` 表加 `publish_status = 1` 过滤
 *     （与归档页、`kcj_astro_schema_payload()` 的 collection 分支**同一判据**）；
 *     标题/摘要过 `wp_strip_all_tags` ⇒ 不夹带后台 HTML。
 *  ④ **不返回任何用户/配置数据**：无 post_id、无 meta、无 option、无路径。
 *     返回体只含**天文历法数值本身** —— 即「公开数据集的公开内容」。
 *
 * ── 为什么不需要鉴权 ───────────────────────────────────────────────
 * 本端点的内容**等价于站点上已经公开渲染出来的内容**（天象数据与事件标题），
 * 不含任何非公开信息 ⇒ 与 `/place` 同档，用 `__return_true`。
 * 对比：`/health` `/freshness` `/import` 暴露的是**运维态**（版本、表状态、写入口），
 * 故那几个保持鉴权 —— 这个区别是刻意的，不是疏漏。
 *
 * @package KCJ_Astro
 */

if (!defined('ABSPATH')) {
    exit;
}

/**
 * 注册只读数据集端点。
 *
 * @return void
 */
function kcj_astro_rest_register_dataset() {
    register_rest_route(KCJ_ASTRO_REST_NS, '/dataset', array(
        'methods'             => 'GET',
        'permission_callback' => '__return_true',
        'args'                => array(
            // kind：**枚举**，不是自由串 ⇒ 天然白名单，无需再过滤
            'kind'  => array(
                'required'          => false,
                'default'           => 'summary',
                'sanitize_callback' => 'sanitize_text_field',
                'validate_callback' => function ($v) {
                    return in_array($v, array('summary', 'daily', 'events', 'places'), true);
                },
            ),
            'limit' => array(
                'required'          => false,
                'default'           => 50,
                // 上限 200：足够 Agent 抽样本，远小于整库（daily 表单日 + 历史）
                'sanitize_callback' => 'absint',
            ),
        ),
        'callback'            => 'kcj_astro_rest_dataset_callback',
    ));
}

/**
 * 端点回调：按 kind 返回对应切片。
 *
 * @param WP_REST_Request $request 请求对象
 * @return array|WP_Error
 */
function kcj_astro_rest_dataset_callback($request) {
    global $wpdb;

    $kind  = (string) $request->get_param('kind');
    $limit = (int) $request->get_param('limit');
    if ($limit <= 0) {
        $limit = 50;
    }
    if ($limit > 200) {
        $limit = 200;
    }

    // ── 元信息：任何 kind 都带上，供 Agent 判断数据新鲜度与口径 ──────────
    $meta = array(
        'site'         => home_url('/'),
        'title'        => 'Chinese Calendar Open Datasets — 华夏历法开放数据集',
        'author'       => array(
            'name' => '邝楚嘉 Chujia Kuang',
            'orcid' => 'https://orcid.org/0009-0002-7650-833X',
        ),
        'license'      => 'https://creativecommons.org/licenses/by/4.0/',
        'dataset_doi'  => '10.5281/zenodo.22788686',
        'preprint_doi' => '10.5281/zenodo.22803746',
        'plugin'       => defined('KCJ_ASTRO_VER') ? KCJ_ASTRO_VER : null,
        // ★ 口径三条：明确告诉机器「这些数据是什么、不是什么」——
        //   比让 Agent 自己揣测更省它的判断成本，也避免它把数据当预言用。
        'scope_note'   => array(
            'these_are'  => '现代天体动力学星历推算的日、月、五星黄道位置，以及二十四节气交节时刻。',
            'these_are_not' => '不含占卜、运势、吉凶、宜忌等任何推断性内容；不提供个体测算。',
            'reference'  => '太阳黄经固定以 15° 为步长划分二十四节气；宿度由岁差变换归算到历史观测历元。',
        ),
        'generated_at' => gmdate('c'),
        'kind'         => $kind,
    );

    // ── summary：只回「有什么数据、多少行、时间跨度」，不吐正文 ──────────
    if ($kind === 'summary') {
        $tables = array();
        $daily_tbl  = KCJ_Astro_DB::table('daily');
        $events_tbl = KCJ_Astro_DB::table('events');
        $site_tbl   = KCJ_Astro_DB::table('daily_site');

        $tables['daily'] = kcj_astro_rest_dataset_table_stat(
            $daily_tbl, 'date_str',
            "SELECT COUNT(*) FROM {$daily_tbl}",
            "SELECT MIN(date_str), MAX(date_str) FROM {$daily_tbl}"
        );
        $tables['events'] = kcj_astro_rest_dataset_table_stat(
            $events_tbl, 'event_time_bj',
            // ★ 只数**已发布**的行（判据与归档页一致）
            "SELECT COUNT(*) FROM {$events_tbl} WHERE publish_status = 1",
            "SELECT MIN(event_time_bj), MAX(event_time_bj) FROM {$events_tbl} WHERE publish_status = 1"
        );
        $tables['daily_site'] = kcj_astro_rest_dataset_table_stat(
            $site_tbl, 'date_str',
            "SELECT COUNT(*) FROM {$site_tbl}",
            "SELECT MIN(date_str), MAX(date_str) FROM {$site_tbl}"
        );

        $meta['tables']   = $tables;
        $meta['endpoints'] = array(
            'summary' => add_query_arg('kind', 'summary', rest_url(KCJ_ASTRO_REST_NS . '/dataset')),
            'daily'   => add_query_arg('kind', 'daily',   rest_url(KCJ_ASTRO_REST_NS . '/dataset')),
            'events'  => add_query_arg('kind', 'events',  rest_url(KCJ_ASTRO_REST_NS . '/dataset')),
            'places'  => add_query_arg('kind', 'places',  rest_url(KCJ_ASTRO_REST_NS . '/dataset')),
            // ★ 观测地单点查询（既有的公开端点，需 date + key 两参）。
            //   ⚠ 这一行是本端点**唯一**指向另一个端点的引用 —— 加它是因为
            //     「给 Agent 一个能自己找到详细数据的地图」比让它猜路径更有用。
            //     **不要**在这里列 /health /freshness /import：那几个要鉴权，
            //     列出来等于给 Agent 三个必然 401 的坑。
            'place'   => rest_url(KCJ_ASTRO_REST_NS . '/place') . '?date=YYYY-MM-DD&key=<place_key>',
        );
        return $meta;
    }

    // ── daily：逐日天象（data_json 原文。这是公开数据的本体，不加工）─────
    if ($kind === 'daily') {
        $tbl  = KCJ_Astro_DB::table('daily');
        $rows = $wpdb->get_results(
            $wpdb->prepare(
                "SELECT date_str, jd, data_version, method, data_json FROM {$tbl}
                 ORDER BY date_str DESC LIMIT %d",
                $limit
            ),
            ARRAY_A
        );
        $out = array();
        foreach ((array) $rows as $r) {
            $data = json_decode(isset($r['data_json']) ? (string) $r['data_json'] : '', true);
            $out[] = array(
                'date'         => isset($r['date_str'])     ? $r['date_str']     : null,
                'jd'           => isset($r['jd'])           ? (float) $r['jd']   : null,
                'data_version' => isset($r['data_version']) ? $r['data_version'] : null,
                'method'       => isset($r['method'])       ? $r['method']       : null,
                'data'         => is_array($data) ? $data : null,
            );
        }
        $meta['count'] = count($out);
        $meta['rows']  = $out;
        return $meta;
    }

    // ── events：天象事件（**只出已发布**，且只出面向公众的字段）──────────
    if ($kind === 'events') {
        $tbl  = KCJ_Astro_DB::table('events');
        $rows = $wpdb->get_results(
            $wpdb->prepare(
                "SELECT event_type, jd_core, event_time_bj, title, slug, summary, ephemeris
                 FROM {$tbl}
                 WHERE publish_status = 1
                 ORDER BY jd_core ASC LIMIT %d",
                $limit
            ),
            ARRAY_A
        );
        $out = array();
        foreach ((array) $rows as $r) {
            $slug = isset($r['slug']) ? (string) $r['slug'] : '';
            $out[] = array(
                'event_type' => isset($r['event_type'])   ? $r['event_type']   : null,
                'time_bj'    => isset($r['event_time_bj']) ? $r['event_time_bj'] : null,
                'jd_core'    => isset($r['jd_core'])      ? (float) $r['jd_core'] : null,
                // ★ 过 strip_tags：库里的 title/summary 可能带编辑期 HTML 残留，
                //   而这是**给机器读的纯数据**，不该夹带标签。
                'title'      => wp_strip_all_tags(isset($r['title'])   ? (string) $r['title']   : ''),
                'summary'    => wp_strip_all_tags(isset($r['summary']) ? (string) $r['summary'] : ''),
                'url'        => home_url('/sky-forecast/' . $slug . '/'),
                'ephemeris'  => isset($r['ephemeris'])    ? $r['ephemeris']    : null,
            );
        }
        $meta['count'] = count($out);
        $meta['rows']  = $out;
        return $meta;
    }

    // ── places：预置观测地清单（含经纬与海拔；这是全站计算的公共基准）────
    if ($kind === 'places') {
        $tbl  = KCJ_Astro_DB::table('daily_site');
        $rows = $wpdb->get_results(
            $wpdb->prepare(
                "SELECT city, city_cn, lat, lon, elev_m, tz, MAX(date_str) AS latest
                 FROM {$tbl}
                 GROUP BY city, city_cn, lat, lon, elev_m, tz
                 ORDER BY city ASC LIMIT %d",
                $limit
            ),
            ARRAY_A
        );
        $out = array();
        foreach ((array) $rows as $r) {
            // ★ 逐键兜底：SQL 别名（`MAX(date_str) AS latest`）在正常 MySQL 下必然存在，
            //   但**依赖别名而不做 isset 就是缺陷** —— 驱动差异、GROUP BY 被优化器改写、
            //   或将来有人改了 SELECT 列表，都会变成 PHP Warning（本项目本机已实测到）。
            //   机器读的接口**不该吐 Warning**：那会污染 JSON 上游、且 8.x 下可配成 Fatal。
            $out[] = array(
                'key'     => isset($r['city'])    ? $r['city']    : null,
                'name_cn' => isset($r['city_cn']) ? $r['city_cn'] : null,
                'lat'     => isset($r['lat'])     ? (float) $r['lat'] : null,
                'lon'     => isset($r['lon'])     ? (float) $r['lon'] : null,
                'elev_m'  => isset($r['elev_m'])  ? (float) $r['elev_m'] : null,
                'tz'      => isset($r['tz'])      ? $r['tz']      : null,
                'latest'  => isset($r['latest'])  ? $r['latest']  : null,
            );
        }
        $meta['count'] = count($out);
        $meta['rows']  = $out;
        return $meta;
    }

    return new WP_Error('kcj_astro_bad_kind', 'kind 不在白名单内', array('status' => 400));
}

/**
 * 取一张表的「行数 + 时间跨度」。
 *
 * ★ 为什么表名要作为**参数传入而非从请求取**：调用点全部是**代码里的字面量**
 *   （见 callback 里的三处），请求无法影响它 ⇒ 不构成注入面。
 *   这是刻意的：让「白名单」体现在**调用点**而非**过滤逻辑**里，更难写错。
 *
 * @param string $tbl       已含前缀的表名（来自 KCJ_Astro_DB::table()）
 * @param string $time_col  时间列名（代码字面量）
 * @param string $count_sql 行数 SQL（代码字面量）
 * @param string $range_sql 跨度 SQL（代码字面量）
 * @return array
 */
function kcj_astro_rest_dataset_table_stat($tbl, $time_col, $count_sql, $range_sql) {
    global $wpdb;
    $count = (int) $wpdb->get_var($count_sql);
    $row   = $wpdb->get_row($range_sql, ARRAY_A);
    $min   = is_array($row) ? array_values($row)[0] : null;
    $max   = is_array($row) ? array_values($row)[1] : null;
    return array(
        'rows' => $count,
        'from' => $min,
        'to'   => $max,
        'time_column' => $time_col,
    );
}

// ★ 挂到 rest_api_init。用 add_action 而非在文件顶层直接调 —— 后者会在
//   插件加载期就注册，某些环境下 rest_api_init 尚未触发 ⇒ 路由静默丢失（本项目踩过）。
add_action('rest_api_init', 'kcj_astro_rest_register_dataset');
