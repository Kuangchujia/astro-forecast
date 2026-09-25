<?php
/**
 * REST 导入端点（v1.1.0 新增，v1.2.0 扩写）
 *
 * ── 为什么必须走 REST ────────────────────────────────────────────────
 *   WordPress.com 托管**不开放外部 MySQL 直连**，故 Python 侧的 `--db`（pymysql 直连）
 *   在 kuangchujia.com 上不可用。可行路径只有两条：
 *     ① 后台手工上传 SQL/CSV（不适合每日增量）
 *     ② 插件暴露鉴权 REST 端点，Python 用「应用程序密码」推数据 ← 本文件
 *
 * ── 端点 ────────────────────────────────────────────────────────────
 *   POST /wp-json/kcj-astro/v1/import       body: {"table":"daily"|"daily_site"|"events"|"relations","rows":[...]}
 *   POST /wp-json/kcj-astro/v1/flush-cache  清 transient（替代外部进程无法触发的 do_action）
 *   GET  /wp-json/kcj-astro/v1/health       连通性与三表行数自检（不写数据）
 *   GET  /wp-json/kcj-astro/v1/freshness    数据新鲜度（最新日记录 vs 今天）
 *
 * ── 幂等性（v1.2.0 修）─────────────────────────────────────────────
 *   v1.1.0 有三处会破坏幂等，现已修：
 *     ① daily 的唯一键只有 jd —— 同一日期若修订过 jd（例如 F17 的尺度修正后再导一次），
 *        会**插出第二行**而不是更新，同一 date_str 出现两条。现改为按 date_str 判重
 *        （表上同时加 UNIQUE uk_date_str）。
 *     ② relations 无唯一键、且 upsert 分支写的是「不判重直接插入」——每次重导都追加重复行。
 *        现按 (from_event,to_event,rel_type) 唯一键 + ON DUPLICATE KEY UPDATE。
 *     ③ 用 `$wpdb->last_error === ''` 判成功 —— last_error 不随成功查询复位，
 *        前一条出错会让后面全部被记成失败。现改为判各 API 的返回值。
 *
 * ── 安全性 ──────────────────────────────────────────────────────────
 *   鉴权：HTTP Basic + WordPress「应用程序密码」；权限要求 edit_posts。
 *   单次上限 500 行；**字段白名单**（非白名单键一律丢弃）；值经 $wpdb->prepare 或类型强制；
 *   不执行任何来自客户端的 SQL 片段。
 *
 * ── ★ v2.2.6 变更（F27：4,672 行全失败的病根）───────────────────────
 *   新增**写入前字段长度预检**（`includes/col-budget.php`）：调 WordPress 自己的
 *   `$wpdb->get_col_length()` / `get_col_charset()` 算出该列的有效上限与计量口径
 *   （char 按字符、byte 与 latin1 按字节 —— 与 `wpdb::strip_invalid_text()` 同源），
 *   超限即带数字报错并跳过写入。
 *   缘起：`events.time_uncertainty` 声明 VARCHAR(64)，真值 60 字符 / **159 字节**，
 *   wpdb 按字节截断 ⇒ 整行被拒；而错误消息无数字，站外只能反推。
 *
 * 硬性约束：本端点不接收也不存储任何占星/吉凶字段；仅天文数值、文献文本与溯源字段。
 */

if (!defined('ABSPATH')) {
    exit;
}

define('KCJ_ASTRO_REST_NS', 'kcj-astro/v1');
define('KCJ_ASTRO_REST_MAX_ROWS', 500);

/** 权限：必须具备 edit_posts（应用程序密码走同一套能力体系） */
function kcj_astro_rest_permission() {
    return current_user_can('edit_posts');
}

/**
 * 白名单：逻辑表名 → 允许写入的列（顺序即写入顺序）。
 * 未列出的键一律丢弃，避免客户端误加列或注入。
 */
function kcj_astro_rest_columns($table) {
    $map = array(
        'daily' => array('date_str', 'jd', 'data_json', 'data_version', 'method', 'special_event_ids'),
        'events' => array('event_id', 'event_type', 'jd_core', 'event_time_bj',
                          'time_uncertainty', 'dt_model', 'post_id', 'title', 'slug',
                          'summary', 'params_json', 'obs_guide', 'obs_site', 'literature',
                          'discussion', 'source_ref', 'method', 'ephemeris', 'publish_status'),
        'relations' => array('from_event', 'to_event', 'rel_type'),
        // v2.0.0：观测地维度（升落与晨昏）。列全部显式，不用 data_json 大字段。
        'daily_site' => array('date_str', 'city', 'city_cn', 'lat', 'lon', 'elev_m', 'tz',
                              'sunrise_bj', 'sunset_bj', 'day_length_min',
                              'tw_civil_begin', 'tw_civil_end',
                              'tw_nautical_begin', 'tw_nautical_end',
                              'tw_astro_begin', 'tw_astro_end',
                              'moonrise_bj', 'moonset_bj',
                              'method', 'data_version'),
    );
    return isset($map[$table]) ? $map[$table] : null;
}

/**
 * 各表的判重键（与建表唯一键一致）。
 * ★ 复合键用**数组**表示（v2.0.0）：daily_site 的唯一键是 (date_str, city)，
 *   而 v1.x 的实现只支持「单列判重」——直接加表会变成「同一天不同城互相覆盖」，
 *   表现为「只有第一座城的记录留得下、其余全被 update 掉」，且**不会报任何错**。
 */
function kcj_astro_rest_unique_key($table) {
    $map = array(
        'daily'      => 'date_str',
        'events'     => 'slug',
        'relations'  => '',
        'daily_site' => array('date_str', 'city'),
    );
    return isset($map[$table]) ? $map[$table] : '';
}

/** 数值型列（写入前强制转型，避免把字符串塞进 DOUBLE） */
function kcj_astro_rest_numeric_columns() {
    return array('jd', 'jd_core', 'event_id', 'post_id', 'publish_status',
                 'from_event', 'to_event',
                 'lat', 'lon', 'elev_m', 'day_length_min');
}

/** 规整为「列 => 值」，丢弃非白名单键；数组/对象自动 JSON 化 */
function kcj_astro_rest_normalize_row($row, $cols) {
    $numeric = kcj_astro_rest_numeric_columns();
    $out = array();
    foreach ($cols as $c) {
        if (!array_key_exists($c, $row)) {
            continue;
        }
        $v = $row[$c];
        if (is_array($v) || is_object($v)) {
            $v = wp_json_encode($v, JSON_UNESCAPED_UNICODE);
        }
        if (in_array($c, $numeric, true)) {
            $v = is_numeric($v) ? $v + 0 : null;
            if ($v === null) {
                continue;   // 数值列给不出数就不写，宁可少一列也不要写错值
            }
        }
        $out[$c] = $v;
    }
    return $out;
}

/**
 * 某表的判重键在**库里**是否兑现为 UNIQUE 索引（v2.3.0 快路径的**前置条件**）。
 *
 * ★ 为什么必须在库上实测、不能只看建表语句：多行 `INSERT ... ON DUPLICATE KEY UPDATE`
 *   的唯一「不产生重复」的保证就是**那个唯一索引**。索引若不在，这条语句会**照单全插**
 *   —— 不是报错，是**静默产生重复行**，而 `written` 计数照样全额通过。
 *   对一个「重导幂等」的数据集来说，这是最坏的一类失败：看起来全成功、数据越导越脏。
 *   故此处 `SHOW INDEX` 实查，取不到就**退回逐行慢路径**（慢路径用 SELECT-then-UPDATE，
 *   不依赖索引也不会插重复），而不是赌索引一定在。
 *
 * @return bool true ＝ 可以用快路径
 */
function kcj_astro_rest_unique_index_ok($table) {
    static $cache = array();
    if (isset($cache[$table])) {
        return $cache[$table];
    }
    $cache[$table] = false;

    $ukey = kcj_astro_rest_unique_key($table);
    if ($ukey === '' || $ukey === null) {
        return false;   // 无唯一键的表（如 relations 的历史形态）不走快路径
    }
    $want = is_array($ukey) ? $ukey : array($ukey);
    sort($want);

    global $wpdb;
    $tbl  = KCJ_Astro_DB::table($table);
    if (!$tbl) {
        return false;
    }
    $idx = $wpdb->get_results("SHOW INDEX FROM {$tbl}", ARRAY_A);   // phpcs:ignore WordPress.DB
    if (!is_array($idx) || !$idx) {
        return false;
    }
    $bykey = array();
    foreach ($idx as $r) {
        if ((int) $r['Non_unique'] !== 0) {
            continue;
        }
        $kn = (string) $r['Key_name'];
        if ($kn === 'PRIMARY') {
            continue;   // 主键是 id，不承担业务判重
        }
        if (!isset($bykey[$kn])) {
            $bykey[$kn] = array();
        }
        $bykey[$kn][(int) $r['Seq_in_index']] = (string) $r['Column_name'];
    }
    foreach ($bykey as $kn => $parts) {
        ksort($parts);
        $got = array_values($parts);
        sort($got);
        if ($got === $want) {
            $cache[$table] = true;
            return true;
        }
    }
    return false;
}

/**
 * 多行 `INSERT ... ON DUPLICATE KEY UPDATE` 快路径（v2.3.0）。
 *
 * ★ 为什么要有它：慢路径对**每一行**发两次库往返（`SELECT id … LIMIT 1` ＋ `INSERT/UPDATE`）。
 *   `daily_site` 由 38 城扩到 340 锚点后是 43,520 行 ⇒ 慢路径约 **87,000 次往返**，
 *   在托管库上按 10 ms 计就是 15 分钟以上，而导入器每跳只有 18 秒时间盒。
 *   快路径把一整批压成**一条**语句 ⇒ 往返数与数据量脱钩。
 *
 * ★ 与慢路径的**语义一致**（否则就是两个行为，将来必出「两边对不上」）：
 *   · 字段白名单、数值列强转、写入前长度预检，三条**逐行照做**；
 *   · 判重靠唯一索引，与慢路径的 `SELECT … WHERE 唯一键` 等价；
 *   · 事件表的 CPT 同步**不在本路径**（`events` 被显式排除，它要拿 `insert_id`）。
 *
 * ★ `deferred` 的用途：列集合**逐行不一致**的批次，或任何一行取不到可用列时，
 *   把这些行**交回慢路径**处理 —— 不猜、不丢、不整批降级。
 *   批量语句要求所有行共享同一列集合，而本数据集理论上都是齐的；
 *   但「理论上齐」不是判据，所以留一条可走的路。
 *
 * @return array|null null ＝ 不适用（唯一索引不在），调用方须整批走慢路径
 */
function kcj_astro_rest_bulk_upsert($table, $rows, $cols) {
    global $wpdb;
    if (!kcj_astro_rest_unique_index_ok($table)) {
        return null;
    }
    $ukey  = kcj_astro_rest_unique_key($table);
    $ukeys = is_array($ukey) ? $ukey : array($ukey);
    $tbl   = KCJ_Astro_DB::table($table);

    // 单条语句最多几行：占位符个数 = 列数 × 行数，是唯一的长度护栏。
    // `daily_site` 20 列 × 500 行 = 10,000 个占位符，SQL 约 250 KB ⇒ 远在 packet 上限内。
    $max_rows = 500;

    $written  = 0;
    $failed   = 0;
    $errors   = array();
    $deferred = array();
    $batch    = array();

    $flush = function () use (&$batch, &$written, &$failed, &$errors, $tbl, $ukeys, $max_rows) {
    // ★★ v2.3.1 修（线上致命错误 F61）：闭包**不继承**外层作用域 —— 外层那句
    //   `global $wpdb;` 对闭包**无效**，闭包内的 `$wpdb` 是未定义变量（null），
    //   于是首次 `$wpdb->prepare()` 直接致命错误：「Call to a member function
    //   prepare() on null」，整个导入端点 500。**必须在闭包内再声明一次 global。**
    //   ⚠ 不用 `use ($wpdb)`：capture-by-value 抓的是**定义那一刻**的值，
    //     一旦将来初始化顺序变动就会静默捕获 null —— 同一故障的第二次。
        global $wpdb;   // ★ 闭包内必须自带（外层的 global 到不了这里）
        while ($batch) {
            $part      = array_splice($batch, 0, $max_rows);
            $cols_used = array_keys($part[0][1]);
            $names     = array();
            foreach ($cols_used as $c) {
                $names[] = '`' . $c . '`';
            }
            $ph   = array();
            $vals = array();
            foreach ($part as $item) {
                $cells = array();
                foreach ($cols_used as $c) {
                    $v = $item[1][$c];
                    if ($v === null) {
                        // ★ NULL 必须写成字面 NULL，不能走 %s —— wpdb 会把 null 转成空串，
                        //   而空串对 SMALLINT/VARCHAR 语义不同（「没有数据」≠「零」「空」）。
                        $cells[] = 'NULL';
                    } else {
                        $cells[] = '%s';
                        $vals[]  = $v;
                    }
                }
                $ph[] = '(' . implode(',', $cells) . ')';
            }
            $upd = array();
            foreach ($cols_used as $c) {
                if (in_array($c, $ukeys, true)) {
                    continue;   // 唯一键列不必自赋值
                }
                $upd[] = '`' . $c . '` = VALUES(`' . $c . '`)';
            }
            $sql = 'INSERT INTO ' . $tbl . ' (' . implode(',', $names) . ') VALUES '
                 . implode(',', $ph);
            if ($upd) {
                $sql .= ' ON DUPLICATE KEY UPDATE ' . implode(',', $upd);
            }
            $q = ($vals ? $wpdb->prepare($sql, $vals) : $sql);   // phpcs:ignore WordPress.DB
            $r = $wpdb->query($q);   // phpcs:ignore WordPress.DB
            if ($r === false) {
                $failed += count($part);
                $errors[] = '批量写入失败（' . count($part) . ' 行）：' . $wpdb->last_error;
            } else {
                $written += count($part);
            }
        }
        $batch = array();
    };

    foreach ($rows as $i => $row) {
        if (!is_array($row)) {
            $deferred[$i] = $row;   // 交给慢路径去报那一条「第 N 行不是对象」
            continue;
        }
        $data = kcj_astro_rest_normalize_row($row, $cols);
        if (!$data) {
            $deferred[$i] = $row;
            continue;
        }
        if (function_exists('kcj_astro_preflight')) {
            $over = kcj_astro_preflight($table, $data);
            if ($over) {
                $failed++;
                foreach ($over as $msg) {
                    $errors[] = $msg;
                }
                continue;
            }
        }
        if ($batch) {
            $a = array_keys($batch[0][1]);
            $b = array_keys($data);
            sort($a);
            sort($b);
            if ($a !== $b) {
                $flush();            // 列集合变了：先把上一批写掉，本行另起一批
            }
        }
        $batch[] = array($i, $data);
        if (count($batch) >= $max_rows) {
            $flush();
        }
    }
    $flush();

    return array(
        'written'  => $written,
        'failed'   => $failed,
        'errors'   => $errors,
        'deferred' => $deferred,
    );
}

/**
 * 分批 upsert。返回 array('written'=>n,'failed'=>m,'errors'=>[...])。
 * relations 走 INSERT ... ON DUPLICATE KEY UPDATE（其余走「查存在→更新，否则插入」）。
 *
 * ★ v2.3.0：先试**多行快路径**（`kcj_astro_rest_bulk_upsert`），只有它「不适用」或
 *   「有行处理不了」时才落到下面的逐行慢路径。`events` **显式排除**在快路径之外
 *   —— 它写完要拿 `insert_id` 去同步 CPT 详情页，而多行语句给不出每行的 id。
 */
function kcj_astro_rest_upsert($table, $rows) {
    global $wpdb;
    $cols = kcj_astro_rest_columns($table);
    if (!$cols) {
        return new WP_Error('kcj_astro_bad_table', '未知数据表：' . $table, array('status' => 400));
    }
    $tbl    = KCJ_Astro_DB::table($table);
    $ukey   = kcj_astro_rest_unique_key($table);
    $written = 0;
    $failed  = 0;
    $errors  = array();

    // ── 快路径（v2.3.0）────────────────────────────────────────────────
    if ($table !== 'events') {
        $fast = kcj_astro_rest_bulk_upsert($table, $rows, $cols);
        if (is_array($fast)) {
            $written += (int) $fast['written'];
            $failed  += (int) $fast['failed'];
            foreach ((array) $fast['errors'] as $e) {
                $errors[] = (string) $e;
            }
            $rest = $fast['deferred'];
            if (!$rest) {
                return array('written' => $written, 'failed' => $failed,
                             'errors' => array_slice(array_unique($errors), 0, 5));
            }
            $rows = $rest;   // 剩下这几行走慢路径；键保留原行号，报错里的「第 N 行」仍对得上
            if ($written > 0 || $failed > 0) {
                $errors[] = '余下 ' . count($rest) . ' 行（列集合与其他行不一致）改走逐行写入。';
            }
        }
    }

    foreach ($rows as $i => $row) {
        if (!is_array($row)) {
            $failed++;
            $errors[] = '第 ' . ($i + 1) . ' 行不是对象，已跳过';   // failed 必带原因
            continue;
        }
        $data = kcj_astro_rest_normalize_row($row, $cols);
        if (!$data) {
            $failed++;
            $errors[] = '第 ' . ($i + 1) . ' 行没有可写入的字段（全在白名单之外或值为 null）';
            continue;
        }

        // ★★ v2.2.6：**写入前先量长度**（F27 之后新增）。
        //   为什么：wpdb 会把「值超列宽」判成该行失败，但给的那句错话里**一个数字都没有**
        //   （「处理以下字段的值失败：X。提供的值可能太长或包含无效数据。」）——
        //   线上那轮 `events_past` 4,672 行全部失败，而「太长」到底是字符太长还是字节太长、
        //   差多少，只能靠读 WordPress 核心源码 + 逐列量真值反推。此处先自己量一遍：
        //     超限 ⇒ 直接报「字段 / 值长（字符＋字节）/ 上限 / 按什么计 / 实际列类型」，
        //            并且**不做这次写入**（省掉一次注定失败的库往返）。
        //   ⚠ 只在**能取到列信息**时判（kcj_astro_preflight 拿不到列就返回空数组）；
        //     取不到信息时照旧交给 wpdb，绝不因为「量不出来」而拒收（纪律 ③）。
        //   ⚠ 消息里**不带行号**：带了就没法 array_unique 去重，400 行会刷出 400 条同义消息，
        //     而「失败多少行」由 $failed 计数给出（见函数末尾的 array_slice(array_unique(...))）。
        if (function_exists('kcj_astro_preflight')) {
            $over = kcj_astro_preflight($table, $data);
            if ($over) {
                $failed++;
                foreach ($over as $msg) {
                    $errors[] = $msg;
                }
                continue;
            }
        }

        if ($table === 'relations') {
            // 唯一键 (from_event,to_event,rel_type)：重复即更新，天然幂等
            $r = $wpdb->query($wpdb->prepare(
                "INSERT INTO {$tbl} (from_event, to_event, rel_type) VALUES (%d, %d, %s)
                 ON DUPLICATE KEY UPDATE rel_type = VALUES(rel_type)",
                (int) $data['from_event'],
                (int) $data['to_event'],
                isset($data['rel_type']) ? (string) $data['rel_type'] : ''
            ));
            if ($r === false) {
                $failed++;
                $errors[] = $wpdb->last_error;
            } else {
                $written++;
            }
            continue;
        }

        $pk = ($table === 'events') ? 'event_id' : 'id';

        // ── 判重并写：支持单列键与**复合键** ───────────────────────────────
        // ★ v2.0.0：原来只支持单列键，若直接把 daily_site 挂进来，会按 date_str 找已有行，
        //   于是「同一天的第二座城」命中第一座城那一行并被 update 掉 —— 38 城最后只剩 1 行，
        //   而且 written 会显示成功。故此处按 $ukey 是否为数组分两路。
        if (is_array($ukey) && $ukey) {
            $where = array();
            $ok_key = true;
            foreach ($ukey as $k) {
                if (!isset($data[$k]) || $data[$k] === '') {
                    $ok_key = false;
                    break;
                }
                $where[$k] = $data[$k];
            }
            if (!$ok_key) {
                $failed++;
                $errors[] = '第 ' . ($i + 1) . ' 行缺少复合唯一键字段（' . implode(',', $ukey) . '）';
                continue;
            }
            $existing_id = $wpdb->get_var($wpdb->prepare(
                "SELECT {$pk} FROM {$tbl} WHERE " . implode(' AND ', array_map(
                    function ($k) { return $k . ' = %s'; }, array_keys($where)
                )) . ' LIMIT 1',
                array_values($where)
            ));
            if ($existing_id) {
                $r  = $wpdb->update($tbl, $data, array($pk => (int) $existing_id));
                $ok = ($r !== false);
            } else {
                $r  = $wpdb->insert($tbl, $data);
                $ok = ($r !== false);
            }
            if ($ok) {
                $written++;
            } else {
                $failed++;
                $errors[] = $wpdb->last_error;
            }
            continue;
        }

        $existing_id = null;
        if ($ukey !== '' && isset($data[$ukey]) && $data[$ukey] !== '') {
            $is_num = is_numeric($data[$ukey]);
            $sql    = $is_num
                ? "SELECT {$pk} FROM {$tbl} WHERE {$ukey} = %f LIMIT 1"
                : "SELECT {$pk} FROM {$tbl} WHERE {$ukey} = %s LIMIT 1";
            $existing_id = $wpdb->get_var($wpdb->prepare($sql, $data[$ukey]));
        }

        // ★ 判返回值而非 $wpdb->last_error（后者不随成功复位）
        if ($existing_id) {
            $r  = $wpdb->update($tbl, $data, array($pk => (int) $existing_id));
            $ok = ($r !== false);
        } else {
            $r  = $wpdb->insert($tbl, $data);
            $ok = ($r !== false);
        }
        if ($ok) {
            $written++;
            // 事件写入后同步为 CPT 文章（指令 03：事件自动成为自定义文章类型）
            // ★ v2.2.0：加一道**显式开关**。历史数据集（4,672 条）是「数据」不是「已发布文章」，
            //   若照旧为每条建页，会凭空长出 4,672 篇自动生成的页面 —— 那属批量薄内容，
            //   且与「历史上今日天象」栏的用途（页面内联展示）不匹配。
            //   后台导入页据此把开关拨到 false（见 includes/admin-import.php）。
            //   默认仍为 true ⇒ 不影响 REST 导入端的原有行为。
            if ($table === 'events') {
                $eid = $existing_id ? (int) $existing_id : (int) $wpdb->insert_id;
                if ($eid > 0 && function_exists('kcj_astro_sync_event_to_post')
                    && apply_filters('kcj_astro_sync_event_posts', true, $eid)) {
                    kcj_astro_sync_event_to_post($eid);
                }
            }
        } else {
            $failed++;
            $errors[] = $wpdb->last_error;
        }
    }

    return array('written' => $written, 'failed' => $failed, 'errors' => array_slice(array_unique($errors), 0, 5));
}

/* --------------------------- 路由 --------------------------- */

add_action('rest_api_init', function () {

    register_rest_route(KCJ_ASTRO_REST_NS, '/health', array(
        'methods'             => 'GET',
        'permission_callback' => 'kcj_astro_rest_permission',
        'callback'            => function () {
            $out = array(
                'ok'        => true,
                'plugin'    => KCJ_ASTRO_VER,
                'rest_ns'   => KCJ_ASTRO_REST_NS,
                'url_infix' => KCJ_ASTRO_SLUG,
                'schema'    => KCJ_Astro_DB::schema_status(),   // F26：表结构版本 + 实测列宽 + 缺口
                'tables'    => KCJ_Astro_DB::health(),
                'freshness' => kcj_astro_freshness(),
                'note'      => '数据由 Python compute_sky.py / build_dataset.py 预计算后经本端点导入',
            );
            return $out;
        },
    ));

    register_rest_route(KCJ_ASTRO_REST_NS, '/freshness', array(
        'methods'             => 'GET',
        'permission_callback' => 'kcj_astro_rest_permission',
        'callback'            => function () {
            return kcj_astro_freshness();
        },
    ));

    register_rest_route(KCJ_ASTRO_REST_NS, '/flush-cache', array(
        'methods'             => 'POST',
        'permission_callback' => 'kcj_astro_rest_permission',
        'callback'            => function () {
            kcj_astro_forecast_flush_cache();
            return array('ok' => true, 'flushed' => true);
        },
    ));

    /**
     * 公开只读：取某日**单个锚点**的观测地行（v2.3.10 新增）。
     *
     * 为什么需要它：首页瘦身后只内联 1 座城（v2.3.9），而读者的**存档城**在浏览器
     *   localStorage 里 —— 服务端无从得知。于是「读者在观测地总览页选过城，回首页
     *   应按该城显示」这条既有功能断了（首页 island 里没有那一城的数据行）。
     *   本端点给前端一个**按需只取那一城**的通道，从而在不增加首屏体积的前提下恢复原功能。
     *
     * 为什么不是 cookie／?place=：① 页面 transient 缓存键不含用户维度，读 cookie 会串号；
     *   ② v2.3.3 明令「换城不换 URL」（防居住地被留在地址栏被收藏转发）。
     *   REST 查询不落在 URL 语义里，存档仍只在 localStorage。
     *
     * ★ 安全面（这是全插件唯一 `__return_true` 的端点，务必守住）：
     *   - **只读**，且**只读 daily_site 一张白名单表**；不接受表名参数；
     *   - `key` 必须**存在于锚点表**（kcj_astro_place_prov_map() 的键集）⇒ 不接受任意 city 串；
     *   - `date` 必须严格 `YYYY-MM-DD`，且经 `wp_date` 走一遍日历合法性（拒绝 2026-02-30）；
     *   - 返回体**只含与 island 行同结构的数组**，不含其它任何库表内容；
     *   - 单次只返回 1 行，无批量面 ⇒ 不可被用来拖全库。
     */
    register_rest_route(KCJ_ASTRO_REST_NS, '/place', array(
        'methods'             => 'GET',
        'permission_callback' => '__return_true',
        'args'                => array(
            'date' => array(
                'required'          => true,
                'sanitize_callback' => 'sanitize_text_field',
            ),
            'key'  => array(
                'required'          => true,
                'sanitize_callback' => 'sanitize_text_field',
            ),
        ),
        'callback'            => function ($request) {
            $date = (string) $request->get_param('date');
            $key  = (string) $request->get_param('key');

            // ① 日期白名单：严格格式 + 真实日历日
            if (!preg_match('/^\d{4}-\d{2}-\d{2}$/', $date)) {
                return new WP_Error('kcj_astro_bad_date', 'date 须为 YYYY-MM-DD', array('status' => 400));
            }
            $ts = strtotime($date . ' 00:00:00 UTC');
            if ($ts === false || gmdate('Y-m-d', $ts) !== $date) {
                return new WP_Error('kcj_astro_bad_date', 'date 不是合法日历日', array('status' => 400));
            }

            // ② 锚点白名单：key 必须在目录的锚点表里（不从库表直接取任意 city）
            $pmap = function_exists('kcj_astro_place_prov_map') ? kcj_astro_place_prov_map() : array();
            if (!is_array($pmap) || $key === '' || !array_key_exists($key, $pmap)) {
                return new WP_Error('kcj_astro_bad_key', 'key 不在预置观测地清单内', array('status' => 404));
            }

            // ③ 取数（单城精确查询，不扫全表）
            $row = kcj_astro_load_place_one($date, $key);
            if ($row === null) {
                return new WP_Error('kcj_astro_no_row',
                    '该日该观测地无数据（可能尚未导入）', array('status' => 404));
            }

            // ④ 产出与 island 单行同结构的载荷（复用唯一构造点，防两处失配）
            return array(
                'ok'   => true,
                'date' => $date,
                'row'  => kcj_astro_place_to_row($key, $row),
            );
        },
    ));

    /**
     * 导航菜单位置：读取与修复（v2.3.16 新增 · 一次性运维端点）。
     *
     * 背景：2026-09-25 全站导航栏消失。定谳＝Seedlet 主题以 `has_nav_menu('primary')`
     *   为唯一开关决定是否渲染 `<nav>`；该开关为 false ⇒ 导航整块不输出。
     *   站上菜单 `Primary`（id 1359）**11 项完好**，丢的是「挂到哪个位置」这条分配记录。
     *   WP.com 的 `/wp/v2/.../menus` 端点在本站**不接受任何位置名**（一律 400
     *   `rest_invalid_menu_location`），`/menu-locations` 在 Jetpack 站点**未实现**（404）
     *   ⇒ 无法经通用 REST 修复，故由本插件（我方自建、可控）提供端点。
     *
     * 为什么先 dry_run：Polylang 激活后会把裸位置 `primary` 换成语言化位置
     *   （形如 `primary_zh`／`primary_en`），**具体名字只能由服务器上的
     *   `get_registered_nav_menus()` 读出**——客户端探名会盲扫且污染日志。
     *   故先 `dry_run=1` 报告真实位置与当前分配，确认后再执行。
     *
     * 安全面：`manage_options`（比 import 端点的 `edit_posts` 更严）；
     *   **只做「把既有菜单挂到既有位置」**，不新建/删除菜单、不改菜单项内容。
     */
    register_rest_route(KCJ_ASTRO_REST_NS, '/nav-menu-locations', array(
        'methods'             => 'GET',
        'permission_callback' => function () { return current_user_can('manage_options'); },
        'callback'            => function () {
            $locs = get_registered_nav_menus();          // 位置 slug => 人类可读名
            $cur  = get_nav_menu_locations();            // 位置 slug => menu term_id
            $menus = array();
            foreach (wp_get_nav_menus() as $m) {
                $menus[] = array(
                    'term_id' => (int) $m->term_id,
                    'name'    => $m->name,
                    'slug'    => $m->slug,
                    'count'   => (int) $m->count,
                );
            }
            $pll = array(
                'polylang_active' => function_exists('pll_languages_list'),
                'languages'       => function_exists('pll_languages_list') ? pll_languages_list() : array(),
                'default'         => function_exists('pll_default_language') ? pll_default_language() : null,
                'current'         => function_exists('pll_current_language') ? pll_current_language() : null,
            );
            return array(
                'ok'                => true,
                'theme'             => wp_get_theme()->get('Name') . ' ' . wp_get_theme()->get('Version'),
                'registered'        => $locs,
                'current_locations' => $cur,
                'menus'             => $menus,
                'polylang'          => $pll,
                'has_primary'       => has_nav_menu('primary'),
                'has_primary_pll'   => function_exists('pll_current_language')
                                        ? has_nav_menu('primary_' . pll_current_language()) : null,
            );
        },
    ));

    register_rest_route(KCJ_ASTRO_REST_NS, '/nav-menu-locations', array(
        'methods'             => 'POST',
        'permission_callback' => function () { return current_user_can('manage_options'); },
        'callback'            => function ($request) {
            $menu_id = (int) $request->get_param('menu_id');
            $targets = $request->get_param('locations');   // 数组：位置 slug 列表
            if ($menu_id <= 0 || !is_array($targets) || !$targets) {
                return new WP_Error('kcj_astro_bad_request',
                    '需要 JSON: {"menu_id":1359,"locations":["primary", ...]}',
                    array('status' => 400));
            }
            $valid = array_keys(get_registered_nav_menus());
            $cur   = get_nav_menu_locations();
            $applied = array();
            $skipped = array();
            foreach ($targets as $loc) {
                $loc = sanitize_key((string) $loc);
                if (!in_array($loc, $valid, true)) {
                    $skipped[] = $loc . '（不在已注册位置内）';
                    continue;
                }
                $cur[$loc] = $menu_id;
                $applied[] = $loc;
            }
            if (!$applied) {
                return new WP_Error('kcj_astro_no_valid_location',
                    '给定位置全部无效。已注册位置：' . implode(', ', $valid),
                    array('status' => 400));
            }
            set_theme_mod('nav_menu_locations', $cur);
            // 复核：只信回读
            $after = get_nav_menu_locations();
            $check = array();
            foreach ($applied as $loc) {
                $check[$loc] = isset($after[$loc]) ? (int) $after[$loc] : null;
            }
            return array(
                'ok'        => true,
                'applied'   => $applied,
                'skipped'   => $skipped,
                'verify'    => $check,
                'has_primary' => has_nav_menu('primary'),
                'note'      => '已写 theme_mod nav_menu_locations；清一次对象缓存后前台即生效',
            );
        },
    ));

    register_rest_route(KCJ_ASTRO_REST_NS, '/import', array(
        'methods'             => 'POST',
        'permission_callback' => 'kcj_astro_rest_permission',
        'callback'            => function ($request) {
            $table = sanitize_key((string) $request->get_param('table'));
            $rows  = $request->get_param('rows');
            if (!$table || !is_array($rows)) {
                return new WP_Error('kcj_astro_bad_request',
                    '需要 JSON: {"table":"daily|daily_site|events|relations","rows":[...]}',
                    array('status' => 400));
            }
            if (count($rows) > KCJ_ASTRO_REST_MAX_ROWS) {
                return new WP_Error('kcj_astro_too_many',
                    '单次最多 ' . KCJ_ASTRO_REST_MAX_ROWS . ' 行，请分批',
                    array('status' => 413));
            }
            $res = kcj_astro_rest_upsert($table, $rows);
            if (is_wp_error($res)) {
                return $res;
            }
            // 导入成功即清缓存（F9：外部进程调不了 do_action，改由服务端自理）
            kcj_astro_forecast_flush_cache();
            kcj_astro_run_audit('rest_import');
            return array(
                'ok'            => true,
                'table'         => $table,
                'received'      => count($rows),
                'written'       => $res['written'],
                'failed'        => $res['failed'],
                'errors'        => $res['errors'],
                'cache_flushed' => true,
            );
        },
    ));
});
