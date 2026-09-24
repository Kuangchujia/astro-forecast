<?php
/**
 * 后台「数据导入」页（v2.2.0 新增）
 *
 * ── 为什么要有这个文件（缘起，勿删） ───────────────────────────────
 *   本模块的数据原本只有一条通路：**外部进程 → REST 端点**（includes/rest-import.php）。
 *   它要求站点提供「应用程序密码」或 OAuth 令牌。2026-09-23 实测：
 *     · 站点**支持**该功能（`/wp-json/` 根索引的 authentication 字段明确宣告
 *       application-passwords 端点）；
 *     · 但外部拿不到有效凭据 —— 应用密码只在**站点仪表盘 → 用户 → 个人资料**里生成，
 *       且 WordPress 生成的口令是 **24 位纯字母数字**
 *       （core: `wp_generate_password(24,false,false)`，校验前 `preg_replace('/[^a-z\d]/i','',$pw)`）。
 *   结果：数据一条也进不来，而**站点的三栏目因此长期空着**。
 *
 *   ⇒ 结论：**把导入搬进 WordPress 内部**。后台里是已登录管理员，不需要任何令牌；
 *     数据文件随插件包一起上传（data/datasets/），点一次按钮即完成。
 *     这条路不依赖平台计划类型、不依赖应用密码、不依赖 OAuth，且全程可复验。
 *
 * ── 分批与超时（关键工程约束） ─────────────────────────────────────
 *   总量 34,845 行，一次请求做完必然超时。做法：
 *     · **游标**（每条非空行的序号）存 option，请求之间可续；
 *     · **双闸**：单次请求最多跑 KCJ_ASTRO_IMPORT_MAX_SEC 秒，或读满一轮；
 *     · 页面每次处理完一批，输出 `<meta http-equiv="refresh">` **自动续跑**，
 *       于是整条链由浏览器逐跳驱动，每跳都是短请求 —— 不碰任何超时上限。
 *   游标算的是**非空行序号**（不是文件字节偏移），故断点续跑与重跑都幂等。
 *
 * ── 幂等 ───────────────────────────────────────────────────────────
 *   写入复用 REST 端点的 upsert（判重键：daily→date_str、
 *   daily_site→(date_str,city)、events→slug），故重复导入是更新而非追加。
 *
 * ── 断点续跑的前提：sha1 指纹（v2.2.3，勿删）──────────────────────────
 *   游标记三样：行序号 offset、字节位 pos、数据件 sha1。**下一次请求必须能证明
 *   「旧字节位指的是同一个文件里的同一位置」**，否则那三样里没有一个可信。
 *   判据一律用 sha1，**不用字节数**：
 *     · 本版把行序改成了「离今天近优先」，而 **重排行序不改变文件字节数**
 *       （实测四个数据件重排前后一字节不差），只比字节数**判不出来**；
 *     · 判不出来的后果不是「白跑」而是「**静默丢数据**」：沿用的旧字节位落在
 *       行中间 ⇒ fgets 读回半行 ⇒ JSON 解析失败被记成坏行 ⇒ 后半段整段丢失，
 *       而游标照常推进、页面照常报「已完成」。
 *   故两道都要有：① sha1 与清单声明不符 ⇒ 拒跑（多半是上传不完整）；
 *   ② sha1 与状态记录不符、**或状态里根本没有 sha1**（v2.2.2 及更早的遗留游标）
 *   ⇒ 从第 1 行重导。upsert 幂等 ⇒ 重导只花时间，不会产生重复行。
 *   行序本身为什么是「功能」而不是「美观」：导入逐跳推进（
 *   每跳 400 行 / 18 秒 ＋ meta refresh 续跑），故**行序 = 数据到达页面的先后**。
 *   原先是时间升序，`daily_site` 的「今天」落在第 14,061 行 ⇒ 用户点了导入、
 *   等了 9 分钟、页面逐项一字未变，只能判成「坏了」。详见 make_datasets.py 头部。
 *
 * 硬性约束：本页只写天文数值、文献文本与溯源字段；不接收也不存储任何占星/吉凶字段。
 */

if (!defined('ABSPATH')) {
    exit;
}

define('KCJ_ASTRO_IMPORT_MAX_SEC', 18);   // 单次请求时间盒（秒）
// 每次 upsert 的行数。
// ★ v2.2.2：120 → 400（120 行/轮时 29,298 行的数据件要 245 轮 × 十几秒 ⇒ 上百跳才跑得完，
//   人会以为「卡死了」）。
// ★ v2.3.0：400 → 1,500。**这一次能放大，是因为瓶颈换地方了**：
//   改前 `kcj_astro_rest_upsert` 对每行发两次库往返（SELECT ＋ INSERT/UPDATE），
//   400 行/批 = 800 次往返 —— 批越大越慢，所以 400 已是当时的实际上限；
//   现在 `daily`/`daily_site`/`relations` 走**多行 ON DUPLICATE KEY UPDATE**，
//   一整批压成一条语句 ⇒ 往返与数据量脱钩，放大批才真正等于少跳。
//   ⚠ 事件表（`events`）仍走逐行（它要拿 insert_id 同步 CPT），故对这一集而言
//     放大只增加单批耗时、不减少往返 —— 它的规模（4,672 行）本来也不吃紧。
define('KCJ_ASTRO_IMPORT_CHUNK', 1500);
define('KCJ_ASTRO_IMPORT_OPT', 'kcj_astro_import_state');

/** 数据集目录 */
function kcj_astro_import_dir() {
    return KCJ_ASTRO_PATH . 'data/datasets/';
}

/**
 * 读数据集清单（data/datasets/_manifest.json，由 make_datasets.py 生成）。
 * 清单缺失 ⇒ 返回空数组 ⇒ 页面如实报「数据集未随包提供」，而不是显示一个空表。
 */
function kcj_astro_import_sets() {
    static $cache = null;
    if ($cache !== null) {
        return $cache;
    }
    $cache = array();
    $f     = kcj_astro_import_dir() . '_manifest.json';
    if (!is_readable($f)) {
        return $cache;
    }
    $j = json_decode((string) file_get_contents($f), true);
    if (!is_array($j) || empty($j['sets']) || !is_array($j['sets'])) {
        return $cache;
    }
    foreach ($j['sets'] as $s) {
        if (!empty($s['key']) && !empty($s['table']) && !empty($s['file'])) {
            $cache[(string) $s['key']] = $s;
        }
    }
    return $cache;
}

/** 导入游标（option，autoload=no） */
function kcj_astro_import_state() {
    $s = get_option(KCJ_ASTRO_IMPORT_OPT, array());
    return is_array($s) ? $s : array();
}

function kcj_astro_import_state_put($key, $arr) {
    $s = kcj_astro_import_state();
    $s[$key] = $arr;
    update_option(KCJ_ASTRO_IMPORT_OPT, $s, false);
}

function kcj_astro_import_state_reset($key) {
    $s = kcj_astro_import_state();
    unset($s[$key]);
    update_option(KCJ_ASTRO_IMPORT_OPT, $s, false);
}

/**
 * 按**非空行序号**读一批 NDJSON。返回：
 *   array('rows'=>[...], 'bad'=>n, 'consumed'=>k, 'eof'=>bool,
 *         'pos'=>字节偏移, 'size'=>文件字节数)   或 WP_Error
 *
 * 三条语义必须同时成立（改前务必读完 —— 前两条都是踩过的坑）：
 *   ① 游标推进按 **consumed（已消费的非空行数）**，与解析成功与否无关。
 *      旧写法按 `$offset += count($rows)` 推进（只数成功的行）—— 文件里只要有
 *      1 行非法 JSON，该行就永远不被消费、每次重读，表现为**无限循环**；
 *      而唯一的兜底 `if (!$rows) { $offset = $total; }` 更糟：它会**静默跳过
 *      后面所有行**却报「已完成」。故改为 consumed，并把兜底收窄到「一行都没消费到」。
 *   ② 空行既不占序号也不占游标 ⇒ 断点续跑不漏行、不重复。
 *   ③ `pos` 是「已消费内容之后的字节偏移」，供下一次请求 **fseek 直接定位**。
 *      旧写法每跳都从文件头 fgets 到 offset ⇒ 对 29,298 行的数据件是 O(n²)：
 *      offset 越大单跳越慢，表现为「导入越跑越慢、最后像卡死」。
 *      同时返回 size，调用方拿它与上次记录比对：文件被换过就从头重导
 *      （宁可重跑，也不许静默错位）。
 *
 * @param int $file_size 上次记录的字节数；与当前不一致则**不使用**快路径。
 * @param int $file_pos  上次记录的字节位；0 表示从头线性扫。
 */
function kcj_astro_import_read($file, $offset, $limit, $file_size = 0, $file_pos = 0) {
    $path = kcj_astro_import_dir() . basename((string) $file);
    if (!is_readable($path)) {
        return new WP_Error('kcj_astro_no_file', '数据文件不可读：' . basename((string) $file));
    }
    $size = (int) filesize($path);
    $fh   = @fopen($path, 'rb');
    if (!$fh) {
        return new WP_Error('kcj_astro_no_file', '数据文件打不开：' . basename((string) $file));
    }

    $i        = 0;
    $rows     = array();
    $bad      = 0;
    $consumed = 0;
    $eof      = true;
    $pos      = 0;

    // ── 快路径：字节位仍有效 ⇒ 直接定位（O(1)）─────────────────────
    //   有效性由调用方给定：file_size 与当前一致，且 file_pos 落在文内。
    //   fseek 失败则老实退回线性扫 —— 不静默降级成错误结果。
    if ($file_size > 0 && $file_size === $size && $file_pos > 0 && $file_pos <= $size) {
        if (fseek($fh, (int) $file_pos) === 0) {
            $i   = (int) $offset;   // 该位之前已消费 $offset 行（调用方保证，见 state.size 校验）
            $pos = (int) $file_pos;
        } else {
            rewind($fh);
        }
    }

    while (($line = fgets($fh)) !== false) {
        $t = trim($line);
        if ($t === '') {
            continue;               // 空行不占序号，也不占游标
        }
        $i++;
        if ($i <= $offset) {
            continue;               // 线性慢路径：跳过已消费行
        }
        if ($consumed >= $limit) {
            $eof = false;           // 已取满且后面还有内容
            break;
        }
        $consumed++;
        $pos = (int) ftell($fh);    // 消费到哪（= 下一行的起始字节位）

        $r = json_decode($t, true);
        if (!is_array($r)) {
            $bad++;                 // ★ 仍计入 consumed —— 否则这一行会被永远重读
            continue;
        }
        $rows[] = $r;
    }
    if ($eof) {
        $pos = $size;               // 已到文件尾
    }
    fclose($fh);

    return array(
        'rows'     => $rows,
        'bad'      => $bad,
        'consumed' => $consumed,
        'eof'      => $eof,
        'pos'      => $pos,
        'size'     => $size,
    );
}

/**
 * 跑一个数据集的一批（时间盒）。返回 true 或 WP_Error。
 * 中途的文件级错误**直接返回 WP_Error**、不吞（本项目反复吃的静默失败）。
 *
 * ★ v2.2.4：`$budget` 可选 —— 单次请求要推进**多个**数据集时，把总时间盒**分摊**下去。
 *   不分摊的话，第一个集的 `run()` 会独自吃掉整个 18 秒 ⇒ 后面的集在本轮根本没机会跑，
 *   于是「每跳各推进一跳」形同虚设，退化成 v2.2.3 的「一次只推一个集」。
 */
function kcj_astro_import_run($key, $budget = null) {
    $sets = kcj_astro_import_sets();
    if (!isset($sets[$key])) {
        return new WP_Error('kcj_astro_bad_set', '未知数据集：' . $key);
    }
    $set = $sets[$key];

    // ★★ v2.2.2 前置检查：**目标表不存在就立刻报错，不要开跑**。
    //   为什么必须有这一道：kcj_astro_rest_upsert 对单行写入失败只累加 failed、
    //   不返回 WP_Error，而游标照常推进 ⇒ 表不存在时页面会显示
    //   「已完成 100%」＋「成功 0 / 失败 29298」，**看上去像成功**。
    //   本轮线上就是这样被误判为「已全部完成」的。宁可当场红字，也不许伪装成功。
    $th = KCJ_Astro_DB::health();
    $tb = isset($th[$set['table']]) ? $th[$set['table']] : null;
    if (!$tb || empty($tb['exists'])) {
        return new WP_Error('kcj_astro_no_table',
            '目标表 ' . ($tb ? $tb['table'] : $set['table']) . ' 不存在，'
            . '写入会全部失败。请先点本页上方的「补建 / 升级表结构」按钮。');
    }

    // ★★ v2.2.3 前置检查：**数据件 sha1 必须与清单声明一致**。
    //   为什么要有这一道：清单由 make_datasets.py 生成，sha1 是「这一版数据件」的
    //   身份。若上传不完整（FTP/后台断流）或数据件被手工替换，字节数与行数都可能
    //   照样对得上，而内容已不是清单所声明的 —— 那种错没有任何别的探针能发现。
    $data_dir = kcj_astro_import_dir();
    $file_sha = @sha1_file($data_dir . basename((string) $set['file']));
    if ($file_sha === false || $file_sha === '') {
        return new WP_Error('kcj_astro_no_file',
            '数据文件读不到（无法计算校验和）：' . basename((string) $set['file']));
    }
    $want_sha = isset($set['sha1']) ? (string) $set['sha1'] : '';
    if ($want_sha !== '' && $file_sha !== $want_sha) {
        return new WP_Error('kcj_astro_sha_mismatch',
            '数据件与清单不符：' . basename((string) $set['file'])
            . ' 实际 sha1 ' . substr($file_sha, 0, 12) . '… ≠ 清单 '
            . substr($want_sha, 0, 12) . '…。多半是上传不完整，或清单与数据件不是同一次生成。'
            . '请在本地重跑 make_datasets.py 后重新打包上传。');
    }

    $st     = kcj_astro_import_state();
    $cur    = isset($st[$key]) && is_array($st[$key]) ? $st[$key] : array();
    $offset = isset($cur['offset']) ? (int) $cur['offset'] : 0;
    $total  = (int) $set['rows'];
    $written = isset($cur['written']) ? (int) $cur['written'] : 0;
    $failed  = isset($cur['failed']) ? (int) $cur['failed'] : 0;
    $errors  = (isset($cur['errors']) && is_array($cur['errors'])) ? $cur['errors'] : array();
    $rounds  = isset($cur['rounds']) ? (int) $cur['rounds'] : 0;
    // 字节位（v2.2.2）：直读定位用。
    $file_pos  = isset($cur['pos']) ? (int) $cur['pos'] : 0;
    $file_size = isset($cur['size']) ? (int) $cur['size'] : 0;
    $prev_sha  = isset($cur['sha1']) ? (string) $cur['sha1'] : '';

    // ★★ v2.2.3：**只要不能证明旧字节位对得上当前数据件，就从第 1 行重导**。
    //   两种「不能证明」都算：
    //     (a) 状态里的 sha1 与当前文件不符 —— 数据件内容变了；
    //     (b) 状态里**根本没有** sha1 —— 那是 v2.2.2 及更早留下的游标。
    //   ⚠ (b) 是本版最容易漏的一处，且后果最重：本版把行序改成了「离今天近优先」，
    //     而**重排行序不改变文件字节数**（实测四项一字节不差）。若只判 (a)，
    //     升级上来的旧游标（无 sha1）会一路沿用**旧字节位**——
    //     那个字节位在新文件里落在**行中间**，fgets 读回半行 ⇒ JSON 解析失败
    //     被记成坏行 ⇒ **后半段静默丢失**，而游标照常推进、页面照常报「已完成」。
    //   代价只是时间（upsert 幂等，不会产生重复行），故一律从严。
    $reset_why = '';
    if ($prev_sha !== '' && $prev_sha !== $file_sha) {
        $reset_why = '数据件内容已变更（sha1 ' . substr($prev_sha, 0, 8)
            . '… → ' . substr($file_sha, 0, 8) . '…）';
    } elseif ($prev_sha === '') {
        $reset_why = '旧游标里没有 sha1（上游版本遗留），无法证明其字节位对得上当前数据件'
            . '（sha1 ' . substr($file_sha, 0, 8) . '…）';
    }
    if ($reset_why !== '' && $offset > 0) {
        $errors[]  = $reset_why . '，已从第 1 行重导。';
        $offset    = 0;
        $file_pos  = 0;
        $file_size = 0;
        $written   = 0;
        $failed    = 0;
        $rounds    = 0;
    }

    // 事件数据集是否同步详情页：由清单决定（历史「不建页」、未来「建页」，见 make_datasets.py 的裁定）
    $sync = !empty($set['sync_posts']);
    $cb   = function () use ($sync) {
        return $sync;
    };
    add_filter('kcj_astro_sync_event_posts', $cb, 10, 2);

    $sec      = ($budget === null) ? KCJ_ASTRO_IMPORT_MAX_SEC : max(1, (int) $budget);
    $deadline = time() + $sec;
    while ($offset < $total && time() < $deadline) {
        $b = kcj_astro_import_read($set['file'], $offset, KCJ_ASTRO_IMPORT_CHUNK, $file_size, $file_pos);
        if (is_wp_error($b)) {
            remove_filter('kcj_astro_sync_event_posts', $cb, 10);
            return $b;
        }

        // ★ v2.2.3：此处不再判「字节数变了」—— 判据已上移到循环之前、改用 sha1
        //   （重排行序不改字节数，只比字节数抓不到）。此处只维护直读定位用的两个量。
        $file_size = $b['size'];
        $file_pos  = $b['pos'];

        // ★ 一行都没消费到 ⇒ 确实到文件尾（或 offset 已越界）。
        //   注意这里只处理「consumed == 0」：旧写法判的是 `!$rows`（成功行数为 0），
        //   一批全是非法 JSON 时会走这里并把 offset 记满 ⇒ **静默跳过后面所有行**。
        if ($b['consumed'] === 0) {
            $offset = $total;
            break;
        }
        $rows = $b['rows'];
        if (isset($set['publish_status']) && $set['publish_status'] !== null) {
            $pv = (int) $set['publish_status'];
            foreach ($rows as $k => $r) {
                $rows[$k]['publish_status'] = $pv;
            }
        }
        $res = kcj_astro_rest_upsert($set['table'], $rows);
        if (is_wp_error($res)) {
            remove_filter('kcj_astro_sync_event_posts', $cb, 10);
            return $res;
        }
        $written += (int) $res['written'];
        $failed  += (int) $res['failed'];
        foreach ((array) $res['errors'] as $e) {
            if (count($errors) < 10) {
                $errors[] = (string) $e;
            }
        }
        if ($b['bad'] > 0 && count($errors) < 10) {
            $errors[] = '跳过 ' . (int) $b['bad'] . ' 行（不是合法 JSON）';
        }
        // ★ 按**消费行数**推进（含被跳过的非法行），不是按成功行数 —— 见函数头 ①。
        //   旧的 `$offset += count($rows)` 会让非法行永远重读（死循环）或整段静默丢失。
        $offset += $b['consumed'];
        $rounds++;
        if ($b['eof']) {
            $offset = $total;
            break;
        }
    }
    remove_filter('kcj_astro_sync_event_posts', $cb, 10);

    kcj_astro_forecast_flush_cache();
    $done = ($offset >= $total);
    if ($done && function_exists('kcj_astro_run_audit')) {
        kcj_astro_run_audit('admin_import');
    }
    kcj_astro_import_state_put($key, array(
        'offset'  => $offset,
        'total'   => $total,
        // v2.2.2：字节位与数据件字节数 —— 供下一跳直读定位，并识别「数据件被换过」。
        'pos'     => $file_pos,
        'size'    => $file_size,
        // v2.2.3：数据件 sha1 —— 「内容有没有变」的唯一可靠判据（字节数对重排是瞎的）。
        'sha1'    => $file_sha,
        'written' => $written,
        'failed'  => $failed,
        'errors'  => array_slice($errors, 0, 10),
        'rounds'  => $rounds,
        'done'    => $done,
        // ★★ v2.2.6：记下**这次失败是在哪个表结构版本上发生的**。
        //   为什么：原先「done 且 failed>0」的集会被永久跳过（就地重跑会在每跳重新选中它
        //   ⇒ 无限重跑），只能靠人点「重跑」。于是「我把列宽修好」与「数据真正进库」之间
        //   还差一次**人工动作** —— 而上一轮的教训正是「用户答已执行、两侧对不上」。
        //   现在：表结构版本变了（= ALTER 真的跑过）⇒ 这个集自动重导一次；
        //   重导后 fail_schema 被更新为当前版本 ⇒ 若仍失败则回到跳过态（**收敛，不会空转**）。
        'fail_schema' => ($failed > 0 || !$done) ? (string) get_option('kcj_astro_schema_version') : '',
        'updated' => current_time('mysql'),
    ));
    return true;
}

/** 某数据集的进度（供页面渲染与管理页共用） */
function kcj_astro_import_progress($key) {
    $st  = kcj_astro_import_state();
    $cur = isset($st[$key]) && is_array($st[$key]) ? $st[$key] : array();
    return array(
        'offset'  => isset($cur['offset']) ? (int) $cur['offset'] : 0,
        'total'   => isset($cur['total']) ? (int) $cur['total'] : 0,
        'pos'     => isset($cur['pos']) ? (int) $cur['pos'] : 0,
        'size'    => isset($cur['size']) ? (int) $cur['size'] : 0,
        'written' => isset($cur['written']) ? (int) $cur['written'] : 0,
        'failed'  => isset($cur['failed']) ? (int) $cur['failed'] : 0,
        'errors'  => (isset($cur['errors']) && is_array($cur['errors'])) ? $cur['errors'] : array(),
        'done'    => !empty($cur['done']),
        // v2.2.6：失败发生在哪个表结构版本上（供「表结构变更后自动重导」判据使用）
        'fail_schema' => isset($cur['fail_schema']) ? (string) $cur['fail_schema'] : '',
        'updated' => isset($cur['updated']) ? (string) $cur['updated'] : '',
    );
}

/**
 * 表结构是否**自这个集的失败以来**变过（v2.2.6）。
 * 返回 true ⇒ 值得自动重导一次（ALTER 多半已把列宽补上）。
 * ★ 判据必须**严**：`fail_schema` 为空（老状态、没有记录）时返回 false ——
 *   宁可让人点一次「重跑」，也不要在每跳都重新选中它、把页面卡在无限重导里。
 *   同时「当前版本为空」（option 未落账）也返回 false：那种情况下 ALTER 并未被确认成功。
 */
function kcj_astro_import_schema_changed($key) {
    $p      = kcj_astro_import_progress($key);
    $was    = (string) $p['fail_schema'];
    $now    = (string) get_option('kcj_astro_schema_version');
    return ($was !== '' && $now !== '' && $was !== $now);
}

/**
 * 清单的**顶层元信息**（行序锚点等）。
 * 与 kcj_astro_import_sets() 分开：那个只返回 sets 字典，元信息会被丢掉。
 */
function kcj_astro_import_manifest_meta() {
    static $m = null;
    if ($m !== null) {
        return $m;
    }
    $m = array();
    $f = kcj_astro_import_dir() . '_manifest.json';
    if (is_readable($f)) {
        $j = json_decode((string) file_get_contents($f), true);
        if (is_array($j)) {
            $m = $j;
        }
    }
    return $m;
}

/** 一批数据件的自检读数：实际 sha1、第 1 行的身份、与清单是否一致。
 *  放在页面上是因为「行序错了」和「包没换」原先**在外面完全看不出来**：
 *  用户等了 9 分钟页面一字未变，只能猜。这道自检把「看不见」变成「一行字」。 */
function kcj_astro_import_data_report() {
    $sets = kcj_astro_import_sets();
    $out  = array();
    foreach ($sets as $k => $s) {
        $path = kcj_astro_import_dir() . basename((string) $s['file']);
        $have = is_readable($path) ? @sha1_file($path) : false;
        $want = isset($s['sha1']) ? (string) $s['sha1'] : '';
        $first = '—';
        if (is_readable($path)) {
            $fh = @fopen($path, 'rb');
            if ($fh) {
                while (($line = fgets($fh)) !== false) {
                    $line = trim($line);
                    if ($line === '') {
                        continue;
                    }
                    $r = json_decode($line, true);
                    if (is_array($r)) {
                        if (isset($r['date_str'])) {
                            $first = (string) $r['date_str'];
                            if (isset($r['city']) && $r['city'] !== '') {
                                $first .= ' / ' . $r['city'];
                            }
                        } elseif (isset($r['event_time_bj'])) {
                            $first = (string) $r['event_time_bj'];
                        }
                    }
                    break;
                }
                fclose($fh);
            }
        }
        $out[$k] = array(
            'file'   => basename((string) $s['file']),
            'order'  => isset($s['order']) ? (string) $s['order'] : '—',
            'first'  => $first,
            'sha1'   => ($have === false) ? '读不到' : substr($have, 0, 12),
            'match'  => ($have !== false && $want !== '' && $have === $want),
            'has_sha' => ($want !== ''),
        );
    }
    return $out;
}

/** 页面 URL（带参数构造，避免各处手拼） */
function kcj_astro_import_url($args = array()) {
    $base = admin_url('edit.php?post_type=' . KCJ_ASTRO_CPT . '&page=kcj-astro-import');
    return empty($args) ? $base : add_query_arg($args, $base);
}

/* ------------------------------ 后台页面 ------------------------------ */

add_action('admin_menu', function () {
    add_submenu_page(
        'edit.php?post_type=' . KCJ_ASTRO_CPT,
        '天象数据导入',
        '数据导入',
        'manage_options',
        'kcj-astro-import',
        'kcj_astro_import_page'
    );
});

function kcj_astro_import_page() {
    if (!current_user_can('manage_options')) {
        wp_die(esc_html('权限不足：仅站点管理员可导入数据。'));
    }
    $sets  = kcj_astro_import_sets();
    $run   = isset($_GET['kcj_run']) ? sanitize_key(wp_unslash($_GET['kcj_run'])) : '';
    $notice = '';
    $notice_cls = 'notice-info';
    $auto = '';   // 非空则输出自动续跑
    // v2.2.2：额外告警（「一键全部」时发现「已完成但全是失败行」的集）＋ 其暂存清单。
    // 单独一条 notice 输出，免得被「本次导入已完成…」那句覆盖掉。
    $extra_notice = '';
    // v2.2.4：自动开始时的说明句。**单独一个变量**——它若写进 $notice，
    // 会被下面的 elseif/else 分支覆盖掉（那正是「写了但不显示」的老坑）。
    $auto_note = '';
    $stale = array();

    // ★★ v2.2.4：**打开本页即自动开始 / 续跑**，免去「该点哪个按钮」这一层。
    //   缘起：v2.2.3 上线后外部取证已确认「包对、数据件对、行序对」（甲/丙/戊 12 项全过，
    //   线上数据件首行确已是 2026-09-23），而三栏**仍一字未变** ⇒ 导入这一步没发生。
    //   而这一步原先要求「先点补建、再点一键全部」，任一环节错位就什么都看不到，
    //   页面上也没有线索可自查（用户两次答「已执行」，两侧对不上）。
    //   本页的唯一用途就是导入，故改为：**一打开就开始/续跑**（页面本身已过
    //   current_user_can('manage_options') 权限门）。
    //   ⚠ 显式带 kcj_run 时照旧走显式路径并校验 nonce；只有自动路径不校验 nonce。
    //   ⚠ 数据件 sha1 与清单不符时**不自动开始**（那种情况下开跑会写进来历不明的数据）。
    $auto_start = false;
    if ($run === '' && $sets) {
        $todo = 0;
        $redo = 0;   // v2.2.6：标着「已完成」但写入有失败、且表结构已变更 ⇒ 值得重导的集数
        foreach ($sets as $k => $s) {
            $p = kcj_astro_import_progress($k);
            if ($p['offset'] < (int) $s['rows']) {
                $todo++;
            } elseif ($p['done'] && $p['failed'] > 0 && kcj_astro_import_schema_changed($k)) {
                // ★★ v2.2.6：这一条**必须与下面的候选判定同步**，否则会出现最尴尬的一种情况 ——
                //   判据认为「有活可干」，而自动开始的闸门认为「没活可干」⇒ 打开页面什么都不发生，
                //   我在这头等结果、用户在那头以为已经好了（上一轮正是这么错过的）。
                //   故两处判据改成同源：都用 kcj_astro_import_schema_changed()。
                $redo++;
            }
        }
        $drep_bad = false;
        foreach (kcj_astro_import_data_report() as $d) {
            if (!$d['has_sha'] || !$d['match']) {
                $drep_bad = true;
                break;
            }
        }
        if (($todo + $redo) > 0 && !$drep_bad) {
            $run        = 'all';
            $auto_start = true;
            $todo       = $todo + $redo;
        }
    }

    if ($run !== '') {
        if ($auto_start) {
            $auto_note = '本页打开即自动开始 / 续跑导入（尚有 ' . $todo . ' 个数据集待处理'
                . '，含表结构变更后需重导的）。'
                . '本页会自己往下走，不必再点任何按钮。';
        } else {
            check_admin_referer('kcj_astro_import_' . $run);
        }

        if ($run === 'repair') {
            // ★ v2.2.2：不依赖 init 守卫，当场 dbDelta 一次并**实测复验**。
            //   守卫只在 option 与常量不符时才跑；一旦 dbDelta 失败而 option 已被
            //   误写，守卫从此不再重试 —— 表就永远缺着，而页面上看不出原因。
            KCJ_Astro_DB::create();
            $hh2 = KCJ_Astro_DB::health();
            $ss2 = KCJ_Astro_DB::schema_status();
            $miss = array();
            foreach ($hh2 as $t => $info) {
                if (empty($info['exists'])) {
                    $miss[] = $info['table'];
                }
            }
            if ($miss) {
                $notice = '补建后仍有 ' . count($miss) . ' 张表缺失：' . implode('、', $miss) . '。'
                    . '请到「插件」页停用再启用本插件重试；若仍缺失，多半是数据库账号没有建表权限。';
                // ★ v2.2.4：把**数据库返回的原始错误**贴出来。
                //   没有这一句时，「表建不出来」在页面上只是一句「仍缺失」，
                //   用户在站外转述不出原因，我只能靠猜（本轮就猜了两轮）。
                if (!empty($ss2['error']['bad'])) {
                    $notice .= ' 数据库返回：' . wp_json_encode($ss2['error']['bad'], JSON_UNESCAPED_UNICODE);
                }
                $notice_cls = 'notice-error';
            } elseif (!empty($ss2['shortfalls'])) {
                $notice = '表已建齐，但列宽未达标（写入会被 MySQL 拒收）：'
                    . implode('；', $ss2['shortfalls']);
                $notice_cls = 'notice-error';
            } else {
                $notice = '表结构就绪：' . count($hh2) . ' 张表齐备、列宽达标（schema option '
                    . ($ss2['option'] === null ? '未落账' : $ss2['option'])
                    . '，期望 ' . $ss2['expected'] . '）。';
                $notice_cls = 'notice-success';
            }
        } elseif (!$sets) {
            $notice = '数据集未随插件包提供：找不到 data/datasets/_manifest.json。'
                . '请用 make_datasets.py 生成数据集后重新打包上传。';
            $notice_cls = 'notice-error';
        } else {
            // kcj_reset=1 ⇒ 先把该数据集游标清零再跑（「重跑」按钮）。
            // ★ 不能拿「已处理行数」当唯一依据：数据件换新版（行数变了）时也要能从头来一遍。
            $reset_one = (isset($_GET['kcj_reset']) && '1' === (string) wp_unslash($_GET['kcj_reset']));

            if ($run !== 'all') {
                // ── 单集：行为与 v2.2.3 一致（「重跑」「继续」按钮走这里）────────
                $target = $run;
                if (!isset($sets[$target])) {
                    $notice = '未知数据集：' . $target;
                    $notice_cls = 'notice-error';
                } else {
                    if ($reset_one) {
                        kcj_astro_import_state_reset($target);
                    }
                    $t0 = time();
                    $r  = kcj_astro_import_run($target);
                    $dt = time() - $t0;
                    if (is_wp_error($r)) {
                        $notice = '「' . $sets[$target]['label'] . '」导入中断：' . $r->get_error_message();
                        $notice_cls = 'notice-error';
                    } else {
                        $p = kcj_astro_import_progress($target);
                        $notice = sprintf('「%s」已处理 %d / %d 行（本次用时 %d 秒）。',
                            $sets[$target]['label'], $p['offset'], (int) $sets[$target]['rows'], $dt);
                        if ($p['failed'] > 0) {
                            $notice .= sprintf(' ⚠ 其中写入失败 %d 行 —— 这些行没有进库。', $p['failed']);
                            if (!empty($p['errors'])) {
                                $notice .= ' 原因：' . implode('；', array_slice($p['errors'], 0, 3));
                            }
                            $notice_cls = 'notice-error';
                        } else {
                            $notice_cls = $p['done'] ? 'notice-success' : 'notice-info';
                        }
                        if (!$p['done']) {
                            $auto = kcj_astro_import_url(array(
                                'kcj_run'  => $target,
                                '_wpnonce' => wp_create_nonce('kcj_astro_import_' . $target),
                                'kcj_auto' => '1',
                            ));
                        }
                    }
                }
            } else {
                // ── ★★ v2.2.4：「一键全部」＝ 本轮把**每个未完成的集各推进一跳** ──────
                //   两个缺陷一起修（都是本轮线上「点了却什么都没发生」的成因）：
                //
                //   ① **队头阻塞**：原实现只选「第一个未完成的集」当 target，它一报错就
                //      `return WP_Error` ⇒ **整条链中断** ⇒ 排在它后面的集**永远轮不到**。
                //      而 `daily_site` 在清单里排第 2 位，恰是最可能报错的那个（表缺）——
                //      于是 `events_*` 从不被导入，「历史栏一直空」与「今日栏一直降级」
                //      同时出现，而页面上只是一句红字，看不出「后面的全被挡住了」。
                //      ⇒ 现改为：**报错的集跳过、继续下一个**，并逐集列出错误。
                //   ② **先到的不一定是先要的**：原实现每跳只推进一个集 ⇒
                //      「先跑完 `daily_site` 的 74 跳，历史栏才轮到」。
                //      ⇒ 现改为**每跳各推进一跳**（时间盒按剩余集数**分摊**，
                //         见 kcj_astro_import_run 的 $budget）⇒ 两个栏目都在最初几跳内点亮。
                $cands = array();
                $rerun = array();   // v2.2.6：因「表结构已变更」而被自动重导的集
                foreach ($sets as $k => $s) {
                    $p = kcj_astro_import_progress($k);
                    // done 但写入有失败 ⇒ 一般不重跑（就地重跑会在每跳重新选中它 ⇒ 无限重跑）。
                    // ★★ v2.2.6 例外：**表结构自那次失败以来变过** ⇒ 自动清零重导一次。
                    //   为什么必须加这一条：F27 的修法是「把列宽从 64 放到 191」，
                    //   而 ALTER 只解决「装得下」，不解决「已经失败的那 4,672 行还没进库」——
                    //   那个集标着 done=true、offset=total，下一跳会**立刻跳过**，
                    //   于是「我修好了」与「数据真的进去了」之间差一次人工点「重跑」。
                    //   上一轮的教训正是「用户答已执行、两侧对不上」，故把这一步也自动化。
                    //   收敛性：重导后 kcj_astro_import_run() 会把 fail_schema 记成**当前**版本，
                    //   若仍失败，下一跳 `$was === $now` ⇒ 回到跳过态，不会空转。
                    if ($p['done'] && $p['failed'] > 0) {
                        if (kcj_astro_import_schema_changed($k)) {
                            kcj_astro_import_state_reset($k);
                            $cands[] = $k;
                            $rerun[] = $k;
                            continue;
                        }
                        $stale[] = $k;
                        continue;
                    }
                    if ($p['offset'] < (int) $s['rows']) {
                        $cands[] = $k;
                    }
                }
                if ($rerun) {
                    $nm = array();
                    foreach ($rerun as $k) {
                        $nm[] = $sets[$k]['label'];
                    }
                    $extra_notice = '表结构已变更 ⇒ 自动重导上一次写入失败的数据集：'
                        . implode('；', $nm) . '。这是为了把「列宽修好了」真正变成「行进库了」。';
                }
                if ($stale) {
                    $nm = array();
                    foreach ($stale as $k) {
                        $pp = kcj_astro_import_progress($k);
                        $nm[] = $sets[$k]['label'] . '（失败 ' . $pp['failed'] . ' 行）';
                    }
                    $extra_notice = ($extra_notice !== '' ? $extra_notice . ' ' : '')
                        . '以下数据集标着「已完成」，但存在写入失败行 —— '
                        . implode('；', $nm) . '。这些行并没有进库。'
                        . '请先点上方「补建 / 升级表结构」，再单独点它的「重跑」。';
                }

                if (!$cands) {
                    if (!$stale) {
                        $notice = '四个数据集均已导入完毕，且无写入失败行。';
                        $notice_cls = 'notice-success';
                    }
                } else {
                    $lines   = array();
                    $errs    = array();
                    $left    = KCJ_ASTRO_IMPORT_MAX_SEC;   // 本请求剩余时间盒
                    $n_cand  = count($cands);
                    foreach ($cands as $i => $k) {
                        if ($left <= 0) {
                            break;   // 时间盒用尽 ⇒ 余下的交给下一跳
                        }
                        // 分摊：剩下的集平分剩余时间，至少 3 秒（太短则一行也跑不完）
                        $share = max(3, (int) floor($left / max(1, $n_cand - $i)));
                        $t0 = time();
                        $r  = kcj_astro_import_run($k, $share);
                        $dt = time() - $t0;
                        $left -= max(1, $dt);
                        if (is_wp_error($r)) {
                            // ★ 跳过它、继续下一个集（旧版在这里整条链中断）
                            $errs[$k] = $r->get_error_message();
                            $lines[]  = '⚠ ' . $sets[$k]['label'] . ' 未能开始';
                            continue;
                        }
                        $p = kcj_astro_import_progress($k);
                        $one = sprintf('%s %d/%d 行（%.0f%%）', $sets[$k]['label'],
                            $p['offset'], (int) $sets[$k]['rows'],
                            $p['offset'] * 100.0 / max(1, (int) $sets[$k]['rows']));
                        if ($p['failed'] > 0) {
                            $one .= '，⚠ 写入失败 ' . $p['failed'] . ' 行';
                        }
                        $lines[] = $one;
                    }
                    $notice = '本轮推进：' . implode('；', $lines) . '。';
                    $notice_cls = 'notice-info';

                    // ★ 判「还有没有未完成的集」必须用**最新**状态，不能用 $cands
                    //   （那是本轮开始前的快照 —— 拿快照判会多续跑一跳，或漏掉刚好完成的收尾）。
                    $still = 0;
                    foreach ($sets as $k => $s) {
                        if (kcj_astro_import_progress($k)['offset'] < (int) $s['rows']) {
                            $still++;
                        }
                    }
                    if ($still > 0) {
                        $auto = kcj_astro_import_url(array(
                            'kcj_run'  => 'all',
                            '_wpnonce' => wp_create_nonce('kcj_astro_import_all'),
                            'kcj_auto' => '1',
                        ));
                        $notice .= sprintf(' 尚有 %d 个数据集未跑完，本页会自动继续。', $still);
                    } elseif (!$errs && !$stale) {
                        $notice = '四个数据集均已导入完毕，且无写入失败行。';
                        $notice_cls = 'notice-success';
                    }
                    // 有集报错 ⇒ 逐集列出（红字单独一条）。
                    // ⚠ 仍会继续自动续跑：跳过报错的集之后，其余集还在推进 ⇒ 停掉就没进展了。
                    //   代价是每跳都会再撞一次那个错、于是每跳都重复显示这条红字 —— 有意为之：
                    //   宁可重复报，也不许把「某个集一直没进去」这件事藏起来。
                    if ($errs) {
                        $parts = array();
                        foreach ($errs as $kk => $msg) {
                            $parts[] = $sets[$kk]['label'] . '：' . $msg;
                        }
                        $err_head = '以下数据集未能开始（已跳过它们、继续处理其余）：';
                        $extra_notice = ($extra_notice !== '' ? $extra_notice . ' ' : '')
                            . $err_head . implode('；', $parts);
                    }
                }
            }
        }
    }

    // ★★ v2.2.5：把「运行状态」写进**公开可读**的信标文件（免凭据即可观察）。
    //   位置刻意放在**所有分支之后**：无论本次是「自动开始」「一键全部」「单集」「补建」，
    //   还是**什么都没做、只是把页面打开了**，都写一次。
    //   最后那一种恰恰最重要 —— 若连文件都没出现，就说明「页面根本没被打开」
    //   或者「uploads 不可写」；这两种情形在站外过去**完全同形**（本轮为此猜了两回）。
    $beacon = array();
    if (function_exists('kcj_astro_beacon_write')) {
        $beacon = kcj_astro_beacon_write(array(
            'run'    => $run,
            'auto'   => $auto_start ? 1 : 0,
            'notice' => $notice,
            'extra'  => $extra_notice,
        ));
    }

    $tables = KCJ_Astro_DB::health();
    $schema = KCJ_Astro_DB::schema_status();
    $meta      = kcj_astro_import_manifest_meta();
    $data_rep  = kcj_astro_import_data_report();
    $bad_data  = array();
    foreach ($data_rep as $k => $d) {
        if (!$d['has_sha'] || !$d['match']) {
            $bad_data[] = $d['file'];
        }
    }
    $miss_tbl = array();
    foreach ($tables as $t => $info) {
        if (empty($info['exists'])) {
            $miss_tbl[] = $info['table'];
        }
    }
    ?>
    <div class="wrap">
      <h1>天象数据导入</h1>

      <?php if ($notice !== '') : ?>
        <div class="notice <?php echo esc_attr($notice_cls); ?>"><p><?php echo esc_html($notice); ?></p></div>
      <?php endif; ?>

      <?php if ($auto_note !== '') : ?>
        <div class="notice notice-info"><p><?php echo esc_html($auto_note); ?></p></div>
      <?php endif; ?>

      <?php if ($extra_notice !== '') : ?>
        <div class="notice notice-error"><p><?php echo esc_html($extra_notice); ?></p></div>
      <?php endif; ?>

      <?php
      // ★★ v2.2.5：公开状态信标区。这一段是**给站外诊断用的窗口** ——
      //   以前「导入到底跑没跑、跑到第几行、报了什么错」只有登录后看得见，
      //   于是站外只能靠猜。现在每次打开本页都会写出下面两个公开文件。
      $b_url   = function_exists('kcj_astro_beacon_status_url') ? kcj_astro_beacon_status_url() : '';
      $b_lurl  = function_exists('kcj_astro_beacon_log_url') ? kcj_astro_beacon_log_url() : '';
      $b_state = get_option('kcj_astro_beacon_state', array());
      $b_err   = get_option('kcj_astro_beacon_error', array());
      ?>
      <h2>公开状态信标（站外可读 · 免凭据）</h2>
      <p style="max-width:960px">
        本页每次打开、每次导入，都会把运行状态写到下面两个文件里。
        <strong>不需要登录</strong>即可读取，所以「导入有没有真的跑」可以在站外直接取证，
        不必再靠页面文案反推。
      </p>
      <ul>
        <li>最新快照：<a href="<?php echo esc_url($b_url); ?>" target="_blank" rel="noopener">
          <code><?php echo esc_html($b_url); ?></code></a>
          —— 四张表的行数、四个数据集的游标与失败行数、表结构版本、最近一次错误。</li>
        <li>逐跳日志：<a href="<?php echo esc_url($b_lurl); ?>" target="_blank" rel="noopener">
          <code><?php echo esc_html($b_lurl); ?></code></a>
          —— 每次调用追加一行，滚动保留最近 200 行。</li>
      </ul>
      <?php if (!$beacon || empty($beacon['ok'])) : ?>
        <div class="notice notice-error"><p>
          <strong>信标没有写出来（或只写出一半）。</strong>
          <?php echo esc_html($beacon && !empty($beacon['why'])
                ? $beacon['why']
                : '本次未调用。'); ?>
          —— 多半是 uploads 目录不可写。没有这两个文件，站外就分不清
          「导入没跑」与「跑了但坏在某处」，只能靠猜。
        </p></div>
      <?php else : ?>
        <p>
          最近一次写入：<code><?php echo esc_html(isset($b_state['at']) ? $b_state['at'] : '（无记录）'); ?></code>
          ｜ 写入成功项：<code><?php echo esc_html(implode('、', (array) (isset($b_state['ok']) ? $b_state['ok'] : array()))); ?></code>
          <?php if (!empty($b_state['ctx']['run'])) : ?>
            ｜ 触发：<code><?php echo esc_html((string) $b_state['ctx']['run']); ?></code>
          <?php endif; ?>
        </p>
      <?php endif; ?>
      <?php if (!empty($b_err['why'])) : ?>
        <div class="notice notice-warning"><p>
          上一次信标写入报错（<code><?php echo esc_html((string) $b_err['at']); ?></code>）：
          <?php echo esc_html((string) $b_err['why']); ?>
        </p></div>
      <?php endif; ?>

      <?php if ($miss_tbl || !empty($schema['shortfalls'])) : ?>
        <div class="notice notice-error"><p>
          <strong>表结构未就绪，先处理这里再导入：</strong>
          <?php if ($miss_tbl) : ?>缺表 <?php echo esc_html(implode('、', $miss_tbl)); ?>。<?php endif; ?>
          <?php if (!empty($schema['shortfalls'])) : ?>
            列宽缺口 <?php echo esc_html(implode('；', $schema['shortfalls'])); ?>。
          <?php endif; ?>
          <?php if (!empty($schema['error'])) : ?>
            上次建表报错：<code><?php echo esc_html(wp_json_encode($schema['error'])); ?></code>
          <?php endif; ?>
          —— 目标表不存在时，导入会「全部失败」（而这些失败以前不会显示出来）。
        </p></div>
      <?php endif; ?>

      <h2>表结构自检</h2>
      <table class="widefat striped" style="max-width:960px">
        <thead>
          <tr><th>表</th><th>存在</th><th>现存行数</th><th>列宽</th></tr>
        </thead>
        <tbody>
        <?php foreach ($tables as $t => $info) :
            $short = array();
            foreach ((array) $schema['shortfalls'] as $c => $v) {
                if (strpos((string) $c, $t . '.') === 0) {
                    $short[] = $v;
                }
            }
            ?>
          <tr>
            <td><code><?php echo esc_html($info['table']); ?></code></td>
            <td><?php echo $info['exists']
                    ? '<strong style="color:#1a7f37">是</strong>'
                    : '<strong style="color:#b32d2e">否 —— 写入会全部失败</strong>'; ?></td>
            <td><?php echo esc_html($info['exists'] ? (string) $info['rows'] : '—'); ?></td>
            <td><?php echo $short ? esc_html(implode('；', $short)) : '达标'; ?></td>
          </tr>
        <?php endforeach; ?>
        </tbody>
      </table>
      <p>
        <?php $n_rep = wp_create_nonce('kcj_astro_import_repair'); ?>
        <a class="button"
           href="<?php echo esc_url(kcj_astro_import_url(array('kcj_run' => 'repair', '_wpnonce' => $n_rep))); ?>">
          补建 / 升级表结构
        </a>
        <span class="description">
          schema option <?php echo esc_html($schema['option'] === null ? '未落账' : (string) $schema['option']); ?>
          ／期望 <?php echo esc_html((string) $schema['expected']); ?>
          ｜当前 <?php echo $schema['ok'] ? '正常' : '需处理'; ?>
          ｜点一次即跑一次 dbDelta（幂等，只 ALTER 有差异的列）。
        </span>
      </p>

      <?php if ($bad_data) : ?>
        <div class="notice notice-error"><p>
          <strong>数据件与清单不一致：</strong><?php echo esc_html(implode('、', $bad_data)); ?>。
          点导入会被当场拒绝（这是有意的：内容对不上时开跑，会写进一批来历不明的数据）。
          请在本地重跑 <code>python make_datasets.py</code>，再重新打包上传。
        </p></div>
      <?php endif; ?>

      <h2>数据件自检</h2>
      <p class="description">
        行序锚点（清单生成时的「今天」）：<code><?php
          echo esc_html(isset($meta['anchor_date']) ? (string) $meta['anchor_date'] : '未记录'); ?></code>。
        导入是<b>逐跳</b>推进的，所以<b>行序就是数据到达页面的先后</b> ——
        「第 1 行」这一列即第一批读到的内容。它必须是<b>今天</b>，
        否则「今日天象」栏要等文件爬到那一行才会正常（29,298 行的数据件里，
        今天原先在第 14,061 行，那正是「点了导入、等很久页面没反应」的原因）。
      </p>
      <table class="widefat striped" style="max-width:960px">
        <thead>
          <tr><th>文件</th><th>行序</th><th>第 1 行（第一批读到的）</th><th>sha1</th><th>与清单一致</th></tr>
        </thead>
        <tbody>
        <?php foreach ($data_rep as $k => $d) : ?>
          <tr>
            <td><code><?php echo esc_html($d['file']); ?></code></td>
            <td><code><?php echo esc_html($d['order']); ?></code></td>
            <td><?php echo esc_html($d['first']); ?></td>
            <td><code><?php echo esc_html($d['sha1']); ?></code></td>
            <td><?php
              if (!$d['has_sha']) {
                  echo '<strong style="color:#b32d2e">清单缺 sha1 —— 请重跑 make_datasets.py</strong>';
              } elseif ($d['match']) {
                  echo '<strong style="color:#1a7f37">是</strong>';
              } else {
                  echo '<strong style="color:#b32d2e">否</strong>';
              }
            ?></td>
          </tr>
        <?php endforeach; ?>
        </tbody>
      </table>
      <p class="description">
        sha1 是「重排行序」的唯一探针：<b>重排不改变文件字节数</b>，
        所以按字节数判「数据件有没有被换过」是瞎的 —— 换掉行序后会沿用旧字节位、
        落在行中间、把后半段静默读丢。故 v2.2.3 起一律以 sha1 为准。
      </p>

      <?php if ($auto !== '') : ?>
        <div class="notice notice-warning"><p>
          正在导入，本页会自动继续；也可手工点下面的「继续」。
          <a class="button button-primary" href="<?php echo esc_url($auto); ?>">继续</a>
        </p></div>
        <meta http-equiv="refresh" content="1;url=<?php echo esc_url($auto); ?>" />
      <?php endif; ?>

      <p class="description">
        数据随插件包提供（<code>data/datasets/</code>），点一次即导入；写入按判重键更新，可重复点。
        单次请求最多跑 <?php echo (int) KCJ_ASTRO_IMPORT_MAX_SEC; ?> 秒，未跑完会自动续。
      </p>

      <?php if (!$sets) : ?>
        <div class="notice notice-error"><p>
          找不到 <code>data/datasets/_manifest.json</code> —— 数据集未随包提供。
          请先在项目根目录跑 <code>python make_datasets.py</code> 生成数据，再重新打包上传。
        </p></div>
      <?php else : ?>
        <table class="widefat striped">
          <thead>
            <tr>
              <th>数据集</th><th>写入表</th><th>行数</th><th>已处理</th>
              <th>进度</th><th>结果</th><th>操作</th>
            </tr>
          </thead>
          <tbody>
          <?php foreach ($sets as $k => $s) :
              $p     = kcj_astro_import_progress($k);
              $total = (int) $s['rows'];
              $pct   = $total > 0 ? min(100, (int) floor($p['offset'] * 100 / $total)) : 0;
              $db    = isset($tables[$s['table']]['rows']) ? $tables[$s['table']]['rows'] : null;
              ?>
            <tr>
              <td>
                <strong><?php echo esc_html($s['label']); ?></strong><br />
                <code><?php echo esc_html($s['file']); ?></code>
              </td>
              <td><code><?php echo esc_html($tables[$s['table']]['table'] ?? $s['table']); ?></code><br />
                  <span class="description">现 <?php echo esc_html($db === null ? '—' : $db); ?> 行</span></td>
              <td><?php echo esc_html($total); ?></td>
              <td><?php echo esc_html($p['offset']); ?></td>
              <td>
                <?php echo esc_html($pct); ?>%
                <?php if ($p['done']) : ?><br /><strong>已完成</strong><?php endif; ?>
              </td>
              <td>
                成功 <strong><?php echo esc_html($p['written']); ?></strong>
                <?php if ($p['failed'] > 0) : ?>
                  ／<span style="color:#b32d2e">失败 <?php echo esc_html($p['failed']); ?></span>
                <?php endif; ?>
                <?php if ($p['updated'] !== '') : ?>
                  <br /><span class="description"><?php echo esc_html($p['updated']); ?></span>
                <?php endif; ?>
                <?php if (!empty($p['errors'])) : ?>
                  <br /><span class="description"><?php echo esc_html(implode('；', array_slice($p['errors'], 0, 2))); ?></span>
                <?php endif; ?>
              </td>
              <td>
                <?php
                $nonce = wp_create_nonce('kcj_astro_import_' . $k);
                if ($p['done']) {
                    $url = kcj_astro_import_url(array('kcj_run' => $k, '_wpnonce' => $nonce, 'kcj_reset' => '1'));
                    ?>
                    <a class="button" href="<?php echo esc_url($url); ?>"
                       onclick="return confirm('重跑会把该数据集再写一遍（按判重键更新，不会重复）。确定？');">重跑</a>
                    <?php
                } else {
                    // ★ 这里只传 kcj_reset=0（**继续**，不清游标）。
                    //   曾写成 `($p['offset'] > 0 ? '1' : '0')` —— 那是**反的**：
                    //   已跑过一半时点「继续」会把游标清零、从头再跑一遍。虽因 upsert 幂等
                    //   不会写坏数据，但白跑一轮，且按钮语义与行为相反。
                    $url = kcj_astro_import_url(array(
                        'kcj_run' => $k, '_wpnonce' => $nonce, 'kcj_reset' => '0',
                    ));
                    ?>
                    <a class="button button-primary" href="<?php echo esc_url($url); ?>">
                      <?php echo ($p['offset'] > 0 ? '继续' : '开始导入'); ?>
                    </a>
                    <?php
                }
                ?>
              </td>
            </tr>
          <?php endforeach; ?>
          </tbody>
        </table>

        <p>
          <?php $n_all = wp_create_nonce('kcj_astro_import_all'); ?>
          <a class="button button-primary"
             href="<?php echo esc_url(kcj_astro_import_url(array('kcj_run' => 'all', '_wpnonce' => $n_all))); ?>">
            一键按顺序导入全部
          </a>
        </p>

        <h2>说明</h2>
        <ul style="list-style:disc;margin-left:1.5em">
          <?php foreach ($sets as $s) : ?>
            <li><strong><?php echo esc_html($s['label']); ?></strong>：<?php echo esc_html($s['note']); ?></li>
          <?php endforeach; ?>
        </ul>
        <p class="description">
          历史事件以「未发布」状态入库：它供「历史上今日天象」栏页面内联展示，
          不生成详情页，也不进归档页、结构化数据与站点地图。未来事件则生成详情页（同 slug 复用，不重复建页）。
        </p>
      <?php endif; ?>
    </div>
    <?php
}
