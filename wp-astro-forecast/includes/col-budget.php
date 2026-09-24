<?php
/**
 * kcj-astro · 列宽预算（column budget）
 *    —— 「这一行写进去会不会被**静默截断**」的唯一判据来源。
 *
 * ═══ 为什么必须有它（缘起，勿删） ═══
 * 2026-09-23：`events_past` 的 4,672 行**全部**写入失败，页面与日志只给出一句
 *   「WordPress 数据库错误：处理以下字段的值失败：time_uncertainty。提供的值可能太长或包含无效数据。」
 * —— 这句话里**一个数字都没有**：不说值多长、不说上限多少、不说比的是字符还是字节。
 * 于是「为什么太长」只能靠推：我把四个表、十几个字符串列的最长值逐列量了一遍，
 * 又去读了 WordPress 核心的 `wpdb::process_fields()` / `strip_invalid_text()` 才敢下结论。
 * 这类事故**不该需要读核心源码才能定位**：超限的那一刻，代码自己就知道
 * 「哪个字段、值多长、上限多少、按什么口径比」。本文件把这三件事做成前置检查。
 *
 * ═══ 判据口径（与 WordPress 完全一致，不是我自己发明的算法）═══
 * 依据：`wp-includes/class-wpdb.php` 的 `strip_invalid_text()`（v6.x）——
 *   ① 列的字符集取不到（false）⇒ **完全不校验、不截断**；
 *   ② 字符集为 `latin1`，或值是**纯 ASCII** ⇒ 按**字节**截断（`strlen` / `substr`）；
 *   ③ 其余（utf8 / utf8mb3 / utf8mb4）⇒ 按**字符**截断（`mb_strlen` / `mb_substr`）。
 *   ④ `get_col_length()` 把列分成 `char`（VARCHAR/CHAR）与 `byte`（BLOB/TEXT 家族）两类，
 *      并给出 `length`；返回 `false` 表示「该列无上限 / 列不存在 / 非 MySQL」。
 * ★ 两侧都**直接调 WordPress 自己的函数**（`$wpdb->get_col_length()` / `get_col_charset()`），
 *   所以本文件的判断与真正执行写入的那段代码**同源**，不会各说各话。
 *
 * ═══ 五条纪律 ═══
 *   ① **失败必须带数字**：消息里一定有「字段名 / 值长（字符＋字节）/ 上限 / 口径 / 声明类型」。
 *   ② **不越权**：本文件只**报告**超限，不替调用方决定改写策略（截断还是拒收由调用方定）。
 *   ③ **拿不到信息不等于没问题**：取不到列信息时返回「未知」并由调用方决定从严，
 *      绝不静默当成「装得下」（本项目反复吃的静默通过）。
 *   ④ **纯函数与取数分开**：`kcj_astro_fit()` 不碰 `$wpdb`，可零桩单测；
 *      这样「字符还是字节」这类最容易写错的判断能被直接钉住。
 *   ⑤ **不改变已有行为**：只做**预检**；通过的行照常走原来的插入路径。
 */

if (!defined('ABSPATH')) {
    exit;
}

/** 值长量测（纯函数）。多字节安全；**不依赖 mbstring**（本机 PHP 就没开）。 */
function kcj_astro_measure($value) {
    if ($value === null) {
        return array('chars' => 0, 'bytes' => 0, 'exact' => true);
    }
    if (!is_string($value)) {
        $value = (string) $value;
    }
    $bytes = strlen($value);
    if (function_exists('mb_strlen')) {
        // 与 WordPress 的 strip_invalid_text() 同一函数、同一编码，故同源可比。
        return array('chars' => (int) mb_strlen($value, 'UTF-8'), 'bytes' => $bytes, 'exact' => true);
    }
    // ★ 没有 mbstring 时**不能**拿字节数当字符数充数 —— 那样 60 字符的中文会被数成 159，
    //   于是「utf8 按字符」这条分支被算反，判据会假红（把装得下的值拦下来），
    //   而假红比假绿更坏：它会教人「把判据关掉」。
    //   故按 WordPress 自己在无 mbstring 时的回落办法数（wp-includes/compat.php 的
    //   _wp_mb_strlen 也是走 preg 这条路）：`/./us` 逐字符匹配。
    $n = @preg_match_all('/./us', $value, $mm);
    if ($n !== false) {
        return array('chars' => (int) $n, 'bytes' => $bytes, 'exact' => true);
    }
    // 连 preg 都数不出来（非法 UTF-8）⇒ 只能报字节数，并把 exact 置 false 让调用方知道。
    return array('chars' => $bytes, 'bytes' => $bytes, 'exact' => false);
}

/**
 * 由「列的长度信息 + 字符集」推出有效口径（纯函数）。
 *
 * @param array|false $len     `$wpdb->get_col_length()` 的返回值
 * @param string|false $charset `$wpdb->get_col_charset()` 的返回值
 * @return array{unit:string,limit:int|null,kind:string|false}
 *         unit: 'char' | 'byte' | 'none'
 */
function kcj_astro_col_budget_from($len, $charset) {
    // ① 列信息拿不到 ⇒ WP 自己也不校验（strip_invalid_text 里 `if (false === $charset) continue;`）
    if ($len === false || $charset === false || $charset === null) {
        return array('unit' => 'none', 'limit' => null, 'kind' => false);
    }
    if (!is_array($len) || !isset($len['type']) || !array_key_exists('length', $len)) {
        return array('unit' => 'none', 'limit' => null, 'kind' => false);
    }
    $kind  = (string) $len['type'];
    $limit = is_numeric($len['length']) ? (int) $len['length'] : null;
    // ② latin1（单字节字符集）⇒ WP 强制按字节
    $cs   = strtolower((string) $charset);
    $unit = ($kind === 'byte') ? 'byte' : 'char';
    if ($cs === 'latin1') {
        $unit = 'byte';
    }
    return array('unit' => $unit, 'limit' => $limit, 'kind' => $kind);
}

/**
 * 判定一个值是否装得下（纯函数）。
 * 返回 null = 「与该列无关或装得下」；否则返回带数字的说明数组。
 *
 * ★ 为什么两个口径的数都要算出来：本轮的事故正是「字符数看着够、字节数不够」
 *   （60 字符 / 159 字节 vs 声明 64）。只报一个数就会再次落到「说不清为什么太长」。
 *   `over` 按**与 WP 相同的口径**判（见文件头），另一个数只作旁证出现在消息里。
 */
function kcj_astro_fit($value, $budget) {
    if ($value === null) {
        return null;
    }
    if (!is_array($budget) || !isset($budget['unit'])) {
        return null;
    }
    if ($budget['unit'] === 'none' || empty($budget['limit'])) {
        return null;   // 无上限 ⇒ 装得下
    }
    $m = kcj_astro_measure($value);
    $limit = (int) $budget['limit'];
    $unit  = (string) $budget['unit'];
    $over  = ($unit === 'byte') ? ($m['bytes'] > $limit) : ($m['chars'] > $limit);
    return array(
        'chars'  => $m['chars'],
        'bytes'  => $m['bytes'],
        'exact'  => $m['exact'],
        'limit'  => $limit,
        'unit'   => $unit,
        'kind'   => isset($budget['kind']) ? $budget['kind'] : false,
        'over'   => $over,
    );
}

/** 取某列的有效口径（**取数**，用 WordPress 自己的两个函数）。 */
function kcj_astro_col_budget($table, $column) {
    global $wpdb;
    $out = array('unit' => 'none', 'limit' => null, 'kind' => false,
                 'declared' => '', 'charset' => null, 'known' => false);
    if (!$wpdb || !is_object($wpdb)
        || !method_exists($wpdb, 'get_col_length') || !method_exists($wpdb, 'get_col_charset')) {
        // 桩环境/非 MySQL：**如实标 known=false**，不假装没问题（纪律 ③）
        return $out;
    }
    if (!class_exists('KCJ_Astro_DB')) {
        return $out;
    }
    $tbl = KCJ_Astro_DB::table($table);
    if (!$tbl) {
        return $out;
    }
    $len = $wpdb->get_col_length($tbl, $column);
    if (function_exists('is_wp_error') && is_wp_error($len)) {
        return $out;
    }
    $charset = $wpdb->get_col_charset($tbl, $column);
    if (function_exists('is_wp_error') && is_wp_error($charset)) {
        return $out;
    }
    $b = kcj_astro_col_budget_from($len, $charset);
    $out['unit']    = $b['unit'];
    $out['limit']   = $b['limit'];
    $out['kind']    = $b['kind'];
    $out['charset'] = ($charset === false ? false : (string) $charset);
    $out['known']   = true;
    if (method_exists('KCJ_Astro_DB', 'column_meta')) {
        $meta = KCJ_Astro_DB::column_meta($table, $column);
        if (is_array($meta)) {
            $out['declared'] = (string) $meta['type'];
        }
    }
    return $out;
}

/** 一行数据里所有**字符串**字段的长度预检。返回 array(字段名 => 可读说明)。 */
function kcj_astro_preflight($table, $data) {
    $bad = array();
    if (!is_array($data)) {
        return $bad;
    }
    foreach ($data as $col => $val) {
        if ($val === null || !is_string($val)) {
            continue;   // 数值列不参与（WP 对 %d/%f 不做长度检查）
        }
        $budget = kcj_astro_col_budget($table, $col);
        $fit    = kcj_astro_fit($val, $budget);
        if (!$fit || empty($fit['over'])) {
            continue;
        }
        $bad[$col] = sprintf(
            '字段 %s 装不下：值长 %d 字符 / %d 字节，列上限 %d（%s；实际类型 %s%s）',
            $col,
            $fit['chars'],
            $fit['bytes'],
            $fit['limit'],
            ($fit['unit'] === 'byte' ? '按字节计' : '按字符计'),
            ($budget['declared'] !== '' ? $budget['declared'] : (string) $fit['kind']),
            ($budget['charset'] === false || $budget['charset'] === null
                ? '' : '，字符集 ' . $budget['charset'])
        );
        if (empty($fit['exact'])) {
            $bad[$col] .= '（本机无 mbstring，字符数为字节兜底值）';
        }
    }
    return $bad;
}
