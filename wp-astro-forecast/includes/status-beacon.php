<?php
/**
 * kcj-astro · 公开状态信标（beacon）  —— 让「导入有没有跑」在站外可读，且**不需要任何凭据**
 *
 * ═══ 为什么要有它（缘起，勿删） ═══
 * 2026-09-23 那一轮，接连三次出现同一个僵局：用户在后台点了、我在站外**什么都看不见**。
 * 包换了（CSS 版本标记 + ?m= 都变了）、数据件对了（四件 sha1 与本地逐一相同）、
 * 行序也对了（首行都落在行序锚点那一天），而三个栏目**逐项一字未变**。
 * 我在站外能拿到的证据只有页面正文里的几句文案（「需导入 wp_astro_daily_site」
 * 「一条都没收录」），而真正需要的三件事 ——
 *   · 导入游标跑到第几行？
 *   · 有没有报错？报的什么错？
 *   · 四张表各有多少行？
 * —— 站外**一律不可见**。`/health` 与 `/import` 都要 `edit_posts`（外网实测 401），
 * 于是「免凭据观察后台」这条路原本根本不存在，只能靠猜，而本轮因此猜错了两回。
 *
 * ═══ 本文件补上这条路 ═══
 * 把运行状态写成**公开可读**的两个文件。刻意放在 **uploads/** 而**不是插件目录**：
 *   · wp-content/uploads/kcj-astro-status.json   最近一次的完整快照（覆盖写、缩进 JSON）
 *   · wp-content/uploads/kcj-astro-log.jsonl     每次调用追加一行（滚动保留最近若干行）
 * 内容只有**计数、游标、错误文本、行序与 sha1**，不含凭据、不含个人信息。
 *
 * ═══ 设计纪律（每一条都是本项目已经踩过的坑） ═══
 *   ① **写盘失败不得静默** —— 失败原因记进 option `kcj_astro_beacon_error`，并在导入页显示。
 *      否则「有信标」与「信标没写出来」在站外**完全同形**，我又得猜（正是本文件要根治的病）。
 *   ② **不写进插件目录** —— 那里会被 make_zip 打进包，「zip ↔ 磁盘逐字节一致」的判据会报红；
 *      而且 WP.com 上插件目录常常是只读的。
 *   ③ **逐次出声** —— 每次调用都写（覆盖 + 追加），不依赖定时任务（定时任务本身也需要人去触发）。
 *   ④ **日志滚动** —— 每跳一行，不裁剪会无限增长。
 *   ⑤ **信标自己不得成为故障源** —— 所有取值都用 `function_exists` / `class_exists` 守卫，
 *      任何一处拿不到就记 null，绝不抛错（否则「为观察而加的代码」自己会打断导入）。
 *
 * ═══ v2.2.6 增补：把「还差哪一层」也照出来 ═══
 *   本版上线后信标立刻给出了确定结论（四集游标全 100%，而 events_past 4,672 行全失败、
 *   失败原文是「处理以下字段的值失败：time_uncertainty」）—— 这一层**成了**。
 *   但接着又发现两处**它自己照不到**的地方，故本版补上：
 *     · `cols`   —— 服务器上每个字符串列的实况（声明类型 / 字符集 / **WordPress 自己算的
 *                   有效上限与计量口径**）。F27 卡在「列宽 64、值 159 字节」，
 *                   而当时站外看不到那一列到底多宽、按字符还是按字节计。
 *     · `places` —— 前台短代码「某日查到几行观测地数据」的审计记录。
 *                   它能一刀切开两种长得一模一样的故障：查到 0 行（数据不在库里）
 *                   vs 查到 38 行而页面仍说「未覆盖」（是**缓存**把旧结果端上来了）。
 *     · `progress[*].errors` —— 失败**原文**进信标。以前只有「失败 N 行」，
 *                   原因只在后台页面的 notice 里，站外看不到 ⇒ 本轮只能靠用户截图。
 *     · 修 `have` 取值：原先读 `schema_status()['version']`（该键不存在）⇒ have 恒为 null，
 *       「schema option 落没落账」这一项**长期读不出来**，而它正是判断
 *       「ALTER 有没有被确认成功」的唯一信号。真实键是 option / expected / ok / widths /
 *       shortfalls / error。⇒ 拆成独立的 `schema_state` 段，并把 `widths` 一并带出。
 */

if (!defined('ABSPATH')) {
    exit;
}

define('KCJ_ASTRO_BEACON_FILE', 'kcj-astro-status.json');
define('KCJ_ASTRO_LOG_FILE', 'kcj-astro-log.jsonl');
define('KCJ_ASTRO_LOG_MAX', 400);     // 行数超过这个值就裁剪
define('KCJ_ASTRO_LOG_KEEP', 200);    // 裁剪后保留最近这么多行

/** uploads 目录（含错误处理：拿不到就返回空串，由调用方记进 beacon_error）。 */
function kcj_astro_beacon_dir() {
    $u = wp_upload_dir();
    if (!is_array($u) || !empty($u['error']) || empty($u['basedir']) || empty($u['baseurl'])) {
        return array('dir' => '', 'url' => '', 'error' => is_array($u) && !empty($u['error'])
            ? (string) $u['error'] : 'wp_upload_dir() 未返回可用目录');
    }
    return array('dir' => trailingslashit($u['basedir']), 'url' => trailingslashit($u['baseurl']), 'error' => '');
}

function kcj_astro_beacon_status_path() { $d = kcj_astro_beacon_dir(); return $d['dir'] . KCJ_ASTRO_BEACON_FILE; }
function kcj_astro_beacon_status_url()  { $d = kcj_astro_beacon_dir(); return $d['url'] . KCJ_ASTRO_BEACON_FILE; }
function kcj_astro_beacon_log_path()    { $d = kcj_astro_beacon_dir(); return $d['dir'] . KCJ_ASTRO_LOG_FILE; }
function kcj_astro_beacon_log_url()     { $d = kcj_astro_beacon_dir(); return $d['url'] . KCJ_ASTRO_LOG_FILE; }

/**
 * 组装快照。**只读、无副作用**，可以单独调用（后台页面也用它）。
 * 拿不到的项一律记 null 并注明，绝不抛错。
 */
function kcj_astro_beacon_snapshot() {
    $out = array(
        'ver'      => defined('KCJ_ASTRO_VER') ? (string) KCJ_ASTRO_VER : null,
        'schema'   => defined('KCJ_ASTRO_SCHEMA') ? (string) KCJ_ASTRO_SCHEMA : null,
        'at'       => current_time('mysql'),
        'site'     => home_url('/'),
        'epoch'    => function_exists('kcj_astro_data_epoch') ? kcj_astro_data_epoch() : null,
        'schema_state' => array('want' => defined('KCJ_ASTRO_SCHEMA') ? (string) KCJ_ASTRO_SCHEMA : null,
                                'have' => null, 'error' => null, 'short' => array(), 'widths' => array()),
        'anchor'   => null,
        'tables'   => array(),
        'progress' => array(),
        'data'     => array(),
        // ★★ v2.2.6 新增两段 —— 都是本轮 F27 卡住时**站外最想要、却拿不到**的东西。
        'cols'     => array(),   // 服务器上各字符串列的**实况**（声明类型/字符集/WP 口径上限）
        'places'   => null,      // 前台短代码「查某日观测地数据查到几行」的审计记录
    );

    if (class_exists('KCJ_Astro_DB')) {
        $ss = KCJ_Astro_DB::schema_status();
        // ★★ v2.2.6 修：这里原先读的是 `$ss['version']`（和 `$out['schema']` 撞名、且键不存在）
        //   ⇒ 站外看到的永远是 `have = null`，「表结构到底落没落账」这一项**长期读不出来**，
        //   而它恰好是判断「ALTER 有没有被确认成功」的唯一信号。
        //   schema_status() 的真实键是 option / expected / ok / widths / shortfalls / error。
        $out['schema_state']['have']   = isset($ss['option']) ? $ss['option'] : null;
        $out['schema_state']['want']   = isset($ss['expected']) ? (string) $ss['expected'] : $out['schema_state']['want'];
        $out['schema_state']['ok']     = !empty($ss['ok']);
        $out['schema_state']['error']  = isset($ss['error']) ? $ss['error'] : null;
        $out['schema_state']['short']  = isset($ss['shortfalls']) ? array_values((array) $ss['shortfalls']) : array();
        $out['schema_state']['widths'] = isset($ss['widths']) ? (array) $ss['widths'] : array();
        foreach ((array) KCJ_Astro_DB::health() as $t => $info) {
            $out['tables'][$t] = array(
                'table'  => isset($info['table']) ? $info['table'] : $t,
                'exists' => !empty($info['exists']),
                'rows'   => !empty($info['exists']) ? (int) $info['rows'] : null,
            );
        }

        // ── 列实况（v2.2.6）─────────────────────────────────────────────
        // 只收**字符串列**：数值/时间列不参与「值是否太长」，收进来只会把文件撑大。
        // 每列记三样：声明类型（SHOW FULL COLUMNS 的 Type）、字符集、以及
        // **WordPress 自己算出来的有效上限与计量口径**（get_col_length / get_col_charset）。
        // ★ 这里只报事实、不作判断 —— 判断在 col-budget.php，免得两处口径漂移。
        $char_kinds = array('char', 'varchar', 'text', 'tinytext', 'mediumtext', 'longtext',
                            'blob', 'tinyblob', 'mediumblob', 'longblob');
        foreach (KCJ_Astro_DB::TABLES as $t) {
            $meta = KCJ_Astro_DB::all_columns($t);
            $keep = array();
            foreach ($meta as $col => $m) {
                $kind = strtolower(preg_replace('/\(.*/', '', (string) $m['type']));
                if (!in_array($kind, $char_kinds, true)) {
                    continue;
                }
                $b = function_exists('kcj_astro_col_budget')
                    ? kcj_astro_col_budget($t, $col)
                    : array('unit' => 'none', 'limit' => null, 'known' => false);
                $keep[$col] = array(
                    'type'   => (string) $m['type'],
                    'coll'   => (string) $m['collation'],
                    // 「WordPress 会按什么口径、放到多长」：unit=char 按字符、byte 按字节、none 不校验
                    'unit'   => isset($b['unit']) ? (string) $b['unit'] : 'none',
                    'limit'  => isset($b['limit']) && $b['limit'] !== null ? (int) $b['limit'] : null,
                    'known'  => !empty($b['known']),
                );
            }
            if ($keep) {
                $out['cols'][$t] = $keep;
            }
        }
    }

    if (function_exists('kcj_astro_import_sets') && function_exists('kcj_astro_import_progress')) {
        foreach ((array) kcj_astro_import_sets() as $k => $s) {
            $p = kcj_astro_import_progress($k);
            $total = (int) $s['rows'];
            $off   = (int) $p['offset'];
            $out['progress'][$k] = array(
                'label'  => isset($s['label']) ? $s['label'] : $k,
                'rows'   => $total,
                'offset' => $off,
                'failed' => (int) $p['failed'],
                'done'   => !empty($p['done']),
                'pct'    => round($off * 100.0 / max(1, $total), 2),
                // ★ v2.2.6：把**失败原文**也带出来。以前信标只报「失败 N 行」，
                //   而「为什么失败」只在后台页面的 notice 里 —— 站外看不到，
                //   于是本轮那 4,672 行只能靠**用户截图**才让我看到原因。
                'errors' => isset($p['errors']) ? array_values((array) $p['errors']) : array(),
                // 失败发生在哪个表结构版本上（判据「表结构变更后自动重导」的输入）
                'fail_schema' => isset($p['fail_schema']) ? (string) $p['fail_schema'] : '',
            );
        }
    }
    if (function_exists('kcj_astro_import_data_report')) {
        foreach ((array) kcj_astro_import_data_report() as $k => $d) {
            $out['data'][$k] = $d;
        }
    }
    if (function_exists('kcj_astro_import_manifest_meta')) {
        $out['anchor'] = kcj_astro_import_manifest_meta();
    }

    // ── 前台查询审计（v2.2.6）───────────────────────────────────────────
    // `kcj_astro_places_seen` 由 kcj_astro_audit_places() 在**每次真正查询**时写入，
    // 记的是「某日查到了几行观测地数据」。这一项能一刀切开两种长得一模一样的故障：
    //   · 查到 0 行  ⇒ 数据确实不在库里（或日期对不上）；
    //   · 查到 38 行而页面仍说「未覆盖」 ⇒ 是**缓存**把旧结果端上来了。
    // 没有它，这两种情况在站外无法区分（本轮正是卡在这里）。
    // ★ v2.3.0：读的是「按时间追加的观测日志」（旧格式 {date=>{rows,at}} 由写入侧迁移）。
    //   为什么给三样而不是只给最近一次：只看最近一次，**瞬时降级**（一次 0 夹在两次正常之间）
    //   与**持续为零**（连续多次 0）长得一模一样，而这两种要采取的动作完全相反
    //   （前者是缓存/竞态，后者是数据没进库）。有了近 8 次序列，站外一眼可判。
    //   同理给 `expect`：能答「340/340 齐」还是「38/340 缺」，不必先知道应该有多少个。
    $seen = get_option('kcj_astro_places_seen', null);
    if (is_array($seen) && $seen) {
        $log = array_values($seen);
        $n   = count($log);
        $out['places']      = array_slice($log, -8);   // 最近 8 次（时间升序）
        $out['places_seen'] = $n;                       // 共保留几条
        $out['places_last'] = $log[$n - 1];             // 最近一次（含 date/rows/expect/at）
    }
    return $out;
}

/**
 * 写快照 + 追加日志行。`$ctx` 说明「这次是什么触发的」，例如
 *   array('run' => 'all', 'auto' => true, 'notice' => '本轮推进：…', 'errors' => array(...))
 * 返回 array('ok'=>[], 'why'=>'', 'url'=>'', 'log_url'=>'')。
 */
function kcj_astro_beacon_write($ctx = array()) {
    $snap  = kcj_astro_beacon_snapshot();
    $snap['ctx'] = is_array($ctx) ? $ctx : array();
    $d     = kcj_astro_beacon_dir();
    $ok    = array();
    $why   = array();

    if ($d['dir'] === '') {
        $why[] = '拿不到 uploads 目录：' . $d['error'];
    } else {
        // ① 覆盖写快照（缩进 JSON，便于人眼与机器读）
        $json = wp_json_encode($snap, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);
        $sp   = kcj_astro_beacon_status_path();
        if (@file_put_contents($sp, $json, LOCK_EX) === false) {
            $why[] = '写快照失败（目录可能不可写）：' . $sp;
        } else {
            $ok[] = 'status';
        }

        // ② 追加一行日志（**单行** JSON；只留最关键的计数，便于 Range 取尾部）
        $line = wp_json_encode(array(
            'at'     => $snap['at'],
            'ver'    => $snap['ver'],
            'ctx'    => $snap['ctx'],
            'off'    => wp_list_pluck($snap['progress'], 'offset'),
            'failed' => wp_list_pluck($snap['progress'], 'failed'),
            'tables' => wp_list_pluck($snap['tables'], 'rows'),
            // ★ v2.2.6：写 schema_state 的真实键（原先写的是不存在的 `version`，故 have 恒为 null）
            'schema' => array('want' => $snap['schema_state']['want'],
                              'have' => $snap['schema_state']['have'],
                              'error' => $snap['schema_state']['error'] ? 1 : 0),
            'epoch'  => $snap['epoch'],
        ), JSON_UNESCAPED_UNICODE);

        $lp = kcj_astro_beacon_log_path();
        // 滚动裁剪：超上限就只留最近 KEEP 行
        if (is_readable($lp)) {
            $old = @file($lp, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
            if (is_array($old) && count($old) > KCJ_ASTRO_LOG_MAX) {
                $keep = array_slice($old, -KCJ_ASTRO_LOG_KEEP);
                @file_put_contents($lp, implode("\n", $keep) . "\n", LOCK_EX);
            }
        }
        if (@file_put_contents($lp, $line . "\n", FILE_APPEND | LOCK_EX) === false) {
            $why[] = '追加日志失败：' . $lp;
        } else {
            $ok[] = 'log';
        }
    }

    // ③ 失败**不得静默**：记进 option，后台页面显示出来
    if ($why) {
        update_option('kcj_astro_beacon_error',
            array('at' => current_time('mysql'), 'why' => implode('；', $why)), false);
    } else {
        delete_option('kcj_astro_beacon_error');
    }
    update_option('kcj_astro_beacon_state', array(
        'at'  => $snap['at'],
        'ver' => $snap['ver'],
        'ok'  => $ok,
        'ctx' => $snap['ctx'],
        'url' => kcj_astro_beacon_status_url(),
    ), false);

    return array('ok' => $ok, 'why' => implode('；', $why),
                 'url' => kcj_astro_beacon_status_url(), 'log_url' => kcj_astro_beacon_log_url());
}
