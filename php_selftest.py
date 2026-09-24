#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
天象预报模块 · PHP 层自检（v1.3.0 新增）

为什么要有这个文件：
  本机原本没有 PHP，于是插件的 PHP 代码**从未被执行过一次** ——
  只能靠「读源码 + 猜」。2026-09-23 踩到的正是这个坑：
  Rank Math 面板里把 CPT 默认 Schema Type 选成 `Event`，前台 79 页**整页零 JSON-LD**，
  根因写在 Rank Math 自己的源码里（白名单只认 Article 家族），而当时无从验证。
  ⇒ 把两件事钉死：
    ① 语法闸：插件内全部 `*.php` 过一遍 `php -l`（有任何一处语法错 = 整站白屏）；
    ② 钩子级桩测试：用最小 WordPress 桩把 `includes/rankmath.php` 真正跑起来，
       断言「哪个上下文该出哪个 @type、哪个上下文必须让位」。

用法：
  python php_selftest.py                 # 全跑（语法 + 桩测试），打印 PASS/FAIL
  python php_selftest.py --lint-only     # 只做语法闸
  python php_selftest.py --json          # 机器可读输出（供上层脚本调用）
  python php_selftest.py --php <路径>     # 指定 php 可执行文件

PHP 可执行文件查找顺序：
  --php 参数 → 环境变量 PHP_BIN → ~/.workbuddy/binaries/php/*/php.exe（本机托管目录）
  → PATH 里的 php
（本机便携版来源：windows.php.net/downloads/releases/ 的 nts-Win32-vs17-x64.zip，
  解压即用，无需安装；已放入 ~/.workbuddy/binaries/php/8.4.26-nts/。）
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.join(HERE, "wp-astro-forecast")
SKIP_DIRS = {".git", "__pycache__", "node_modules"}

# ── PHP 桩：目的是让 rankmath.php 的顶层代码真的执行起来 ───────────────────────
# 只实现 rankmath.php 实际调用到的那些 WordPress API，不做通用模拟。
HARNESS = r"""<?php
/**
 * 自动生成的最小 WordPress 桩（由 php_selftest.py 写入临时目录，勿手改）。
 * 用法：php harness.php <case>
 *   case ∈ event | event_with_rankmath_meta | historical | collection | daily | daily_no_shortcode
 */
define('ABSPATH', __DIR__);
define('ARRAY_A', 'ARRAY_A');
define('ARRAY_N', 'ARRAY_N');
define('OBJECT', 'OBJECT');
define('KCJ_ASTRO_CPT', 'astro_event');
define('KCJ_ASTRO_TAX', 'event_type');
define('KCJ_ASTRO_SLUG', 'sky-forecast');
/* ★ v2.2.7（F52）：渲染模板需要它（kcj_astro_render_template 用 KCJ_ASTRO_PATH 拼模板路径）。
   ⚠ 插件主文件不在桩里加载，故此处必须自己定义 —— 否则一旦有用例去渲染模板，
     报的是「未定义常量」这种与缺陷无关的错（会把「测不了」误当成「测过了」）。 */
define('KCJ_ASTRO_PATH', getenv('KCJ_PLUGIN_DIR') . '/');

/* ★ 时区必须先钉死：站点口径是北京时间。桩若不设，PHP 会用 UTC（或告警），
   于是 current_time('Y-m-d') 在 08:00 前后会跨日错位，「期间口径跨语言对拍」直接假红。 */
date_default_timezone_set('Asia/Shanghai');

$GLOBALS['kcj_hooks']  = [];
$GLOBALS['kcj_case']   = isset($argv[1]) ? $argv[1] : 'event';
$GLOBALS['kcj_pid']    = 264;
$GLOBALS['kcj_meta']   = [];
$GLOBALS['kcj_content'] = '';
$GLOBALS['kcj_shortcodes'] = [];
/* ★ v2.3.1：导入器真跑用例要记录「发出去的那几条 SQL」，用于断言语句形状。 */
$GLOBALS['kcj_sql'] = [];

/* 站点现状：Rank Math 已启用（插件按 defined('RANK_MATH_VERSION') 判定）。
   设环境变量 KCJ_NO_RANKMATH=1 可模拟「未启用」回退路径。 */
$GLOBALS['kcj_no_rm'] = getenv('KCJ_NO_RANKMATH') === '1';
if (!$GLOBALS['kcj_no_rm']) {
    define('RANK_MATH_VERSION', '1.0.240-stub');
}

/** 站点身份：按 case 摆好查询上下文与数据 */
switch ($GLOBALS['kcj_case']) {
    case 'event':
        break;
    case 'event_with_rankmath_meta':
        // Rank Math 已为该篇写过文章级 schema（编辑器保存过的情形）
        $GLOBALS['kcj_meta'] = ['rank_math_schema_Event' => ['@type' => 'Event']];
        break;
    case 'historical':
        break;
    case 'collection':
        break;
    case 'daily':
        $GLOBALS['kcj_pid']     = 229;   // 老黄历页
        $GLOBALS['kcj_content'] = '<p>[astro_today date="2026-10-04"]</p>';
        break;
    case 'daily_no_shortcode':
        $GLOBALS['kcj_pid']     = 229;
        $GLOBALS['kcj_content'] = '<p>不含短代码的普通页面</p>';
        break;

    case 'hub_page':
        // ★ v2.3.2（F62）：页面用的是 [astro_hub]（「天象预告」页正是它）。
        //   该短代码的「今日天象」栏**默认开启**（today="1"），且三栏都渲染进 HTML
        //   （模板是 radio + CSS 切换，不是 JS 按需取数）⇒ 页面上确实有今日天象内容。
        $GLOBALS['kcj_pid']     = 51;
        $GLOBALS['kcj_content'] = '<p>[astro_hub]</p>';
        break;
    case 'hub_page_today_off':
        // 负控制：把「今日天象」栏显式关掉 ⇒ 页面上没有今日天象 ⇒ 不得声明 Dataset。
        $GLOBALS['kcj_pid']     = 51;
        $GLOBALS['kcj_content'] = '<p>[astro_hub today="0" future="1" past="1"]</p>';
        break;
    case 'report_range':
        // 只测期间口径（纯函数），不涉查询上下文
        break;
    case 'history_helpers':
        // 只测历史栏目的两条纯函数（分组键 / 日期跳转），不涉查询上下文
        break;
    case 'hub_tabs':
        // 只测栏目激活态（URL → 该开哪一栏）；渲染走 kcj_astro_render_template，
        // 用页面内固定的 sections，不查库、不依赖查询上下文。
        break;
    case 'bulk_upsert':
        // 只测导入器多行快路径（真跑 kcj_astro_rest_bulk_upsert），不依赖查询上下文。
        break;
    default:
        fwrite(STDERR, "unknown case: {$GLOBALS['kcj_case']}\n");
        exit(2);
}

/* ---- 钩子收集 ---- */
function add_filter($tag, $cb, $prio = 10, $args = 1) { $GLOBALS['kcj_hooks'][$tag][] = ['prio' => $prio, 'args' => $args, 'cb' => $cb]; return true; }
function add_action($tag, $cb, $prio = 10, $args = 1) { return add_filter($tag, $cb, $prio, $args); }
function add_shortcode($tag, $cb) { $GLOBALS['kcj_shortcodes'][$tag] = $cb; return true; }

/* ---- 查询上下文 ---- */
/* ★ 这里必须是**白名单式的字面清单**：新增 case 一律要登记，否则会被误判成
   「CPT 单篇」而走错分支（本轮 hub_page 就踩了：报出一堆与缺陷无关的错）。 */
function is_singular($t = '') { $c = $GLOBALS['kcj_case']; if (in_array($c, ['collection', 'daily', 'daily_no_shortcode', 'hub_page', 'hub_page_today_off'], true)) { return false; } return $t === '' ? true : $t === KCJ_ASTRO_CPT; }
function is_post_type_archive($t = '') { return $GLOBALS['kcj_case'] === 'collection' && $t === KCJ_ASTRO_CPT; }
function is_tax($t = '') { return false; }

/* ---- 文章 API ---- */
function get_the_ID() { return (int) $GLOBALS['kcj_pid']; }
function get_queried_object_id() { return (int) $GLOBALS['kcj_pid']; }
function get_post_meta($id = 0, $key = '', $single = false) { return $GLOBALS['kcj_meta']; }
function metadata_exists($t, $id, $key) { return array_key_exists($key, $GLOBALS['kcj_meta']); }
function get_post_field($f, $id = 0) { return $f === 'post_content' ? $GLOBALS['kcj_content'] : ''; }
function has_shortcode($content, $tag) { return strpos((string) $content, '[' . $tag) !== false; }
function get_permalink($id = 0) { return 'https://example.test/sky-forecast/planet-saturn-opposition-20261004/'; }
function home_url($path = '') { return 'https://example.test' . $path; }
/* add_query_arg：kcj_astro_history_nav() 用它拼「前后几天」的链接。
   ★ 桩要保留「已有查询串时用 & 而非 ?」这一分支 —— 否则只在有查询串的页面上出错，
     而本测试恰好总是在无查询串的桩 URL 上跑，于是永远测不到（自指陷阱：观察面选错）。 */
function add_query_arg($key, $val = null, $url = null) {
    $base = $url ? $url : 'https://example.test/sky-forecast/history-today/';
    if (is_array($key)) { $qs = http_build_query($key); }
    else { $qs = rawurlencode((string) $key) . '=' . rawurlencode((string) $val); }
    return $base . (strpos($base, '?') === false ? '?' : '&') . $qs;
}
/* 基准时刻可被 KCJ_NOW 覆盖（形如 '2027-03-01'）。
   为什么需要：期间口径要对多组基准日做跨语言对拍，固定时间戳只能测一天，
   而 next12 的两种错法（＋365 天 / strtotime 加月）**只在闰日附近分岔**，
   不换基准日就永远测不出来。时刻取 12:00，避开日界。 */
function current_time($f) {
    $now = getenv('KCJ_NOW');
    $ts  = (is_string($now) && $now !== '') ? strtotime($now . ' 12:00:00') : 1780000000;
    return date($f, $ts);
}

/* shortcode_parse_atts：WP 核心函数（rankmath.php 的 daily 判据用它读 [astro_hub]
   的 today 开关）。只实现 kcj 用得到的三种写法：key="v" / key='v' / key=v。
   ⚠ 不实现「裸 token 与无名子串落进 $atts[0]」那条分支 —— 本处用不到。桩可以不完整，
     但**不许假装完整**：写了不验证的分支就是假证据。
   ⚠ 但保留了 WP 的关键语义：`today` 裸写成 flag 时进不了 ['today'] 键 ⇒
     shortcodes.php 里 `$atts['today'] === '1'` 不成立 ⇒ 该栏关闭。这条不能省。 */
function shortcode_parse_atts($text) {
    $atts = [];
    $re = '/([\w-]+)\s*=\s*"([^"]*)"(?:\s|$)|([\w-]+)\s*=\s*\'([^\']*)\'(?:\s|$)|([\w-]+)\s*=\s*([^\s\'"]+)(?:\s|$)/';
    if (preg_match_all($re, (string) $text, $m, PREG_SET_ORDER)) {
        foreach ($m as $g) {
            if (!empty($g[1]))     { $atts[strtolower($g[1])] = stripcslashes($g[2]); }
            elseif (!empty($g[3])) { $atts[strtolower($g[3])] = stripcslashes($g[4]); }
            elseif (!empty($g[5])) { $atts[strtolower($g[5])] = stripcslashes($g[6]); }
        }
    }
    return $atts;
}

/* ---- 文本 / 编码 ---- */
function wp_strip_all_tags($s) { return trim(strip_tags((string) $s)); }
function wp_json_encode($d, $flags = 0) { return json_encode($d, $flags); }
function esc_attr($s) { return htmlspecialchars((string) $s, ENT_QUOTES); }
function esc_html($s) { return htmlspecialchars((string) $s, ENT_QUOTES); }
function esc_html__($s, $d = '') { return $s; }
/* ★ v2.2.7（F52）：栏目激活态的解析器要读 URL 参数，需要这两个。
   sanitize_text_field 只实现本处用得到的部分：剥标签 + 折空白 + trim。
   不实现 HTML 实体与字符集过滤 —— 桩不必完整，但**不许假装完整**：
   这里用得到的只是「把 '  past  ' 折成 'past'」，多写反而是假证据。 */
function sanitize_text_field($s) {
    $s = strip_tags((string) $s);
    $s = preg_replace('/[\r\n\t ]+/', ' ', $s);
    return trim($s);
}
function wp_unslash($v) { return is_string($v) ? stripslashes($v) : $v; }

/** 取出「哪个 radio 带 checked」（返回 id 列表，逗号拼接）。用于 F52 的桩断言。
    ⚠ 不能用 substr_count 数一个拼接好的串：模板里 id= 与 data-i= 之间是换行+缩进，
      拼接串根本不存在 ⇒ 判据会永远报「找不到」而看起来像是模板错了（假红）。 */
function kcj_hub_checked_ids($h) {
    if (preg_match_all('/id="([^"]+-t\d+)"\s+data-i="\d+"\s+checked="checked"/', $h, $m)) {
        return implode(',', $m[1]);
    }
    return '';
}

/* ---- 数据层桩（真实实现在 includes/class-astro-db.php，此处不引入） ---- */
class KCJ_Astro_DB {
    public static function table($name) { return 'wp_astro_' . $name; }
}

class KCJ_Stub_WPDB {
    public $rows = [];
    public $last_error = '';
    public $insert_id  = 0;
    /** ★ v2.3.1：`kcj_astro_rest_bulk_upsert()` 真跑的必经之路（记录语句供断言形状）。
        —— 本桩原先没有 `query()`：那条快路径从未被本测试调用过，于是「闭包内 $wpdb
           为 null」这种必崩缺陷在 41/41 全绿里安然无恙（F61，线上致命错误）。 */
    public function query($q) { $GLOBALS['kcj_sql'][] = $q; return 1; }
    public function prepare($q, $a = null) { return $q; }
    public function get_row($q, $mode = null) {
        $c = $GLOBALS['kcj_case'];
        // ★ v2.3.2：daily 那一行改按 **SQL 形状** 认，不按 case 名认。
        //   原先写成 `if ($c === 'daily')` ⇒ 任何新增的「含今日天象的页面」用例
        //   （本轮 hub_page）都取不到行，payload 恒空 —— 纯函数明明修好了、总判定
        //   却照旧报红（假红）；而当时若把断言写松一点就会变成假绿。
        //   按形状认：谁查 data_json 就给谁，与「跑的是哪个 case」解耦。
        if (strpos((string) $q, 'data_json') !== false) {
            return ['data_json' => json_encode([
                'observer' => ['city' => '揭阳', 'lat' => 23.35, 'lon' => 116.36],
                'sun' => ['x' => 1], 'moon' => ['x' => 1], 'planets' => [1, 2],
            ])];
        }
        if ($c === 'event' || $c === 'event_with_rankmath_meta') {
            return [
                'title'           => '土星冲日',
                'summary'         => '土星与太阳黄经相差 180°，日落时东升、午夜中天、日出时西落，整夜可见。',
                'event_time_bj'   => '2026-10-04 20:29:16',
                'event_type'      => 'planet',
                'obs_site'        => '',
                'source_ref'      => '',
                'literature'      => '',
                'time_uncertainty' => '',
                'method'          => 'jpl',
            ];
        }
        if ($c === 'historical') {
            return [
                'title'           => '1054年天关客星',
                'summary'         => '至和元年五月己丑，客星出天关之东南。',
                'event_time_bj'   => '1054-07-04 00:00:00',
                'event_type'      => 'historical',
                'obs_site'        => '',
                'source_ref'      => '《宋史·天文志》',
                'literature'      => '《宋会要辑稿》',
                'time_uncertainty' => '±3日',
                'method'          => 'analytic_meeus',
            ];
        }
        // （daily 行已上移为「按 SQL 形状认」，见本函数开头 —— 不再按 case 名认。）
        return null;
    }
    public function get_results($q, $mode = null) {
        // ★ v2.3.1：导入器用例要的是 `SHOW INDEX` 的结构（含 daily_site 的复合唯一键），
        //   不是事件列表。按 case 分流 —— 否则那条路径永远走不到。
        if ($GLOBALS['kcj_case'] === 'bulk_upsert') {
            return [
                ['Non_unique' => 0, 'Key_name' => 'PRIMARY',      'Seq_in_index' => 1, 'Column_name' => 'id'],
                ['Non_unique' => 0, 'Key_name' => 'uk_date_city', 'Seq_in_index' => 1, 'Column_name' => 'date_str'],
                ['Non_unique' => 0, 'Key_name' => 'uk_date_city', 'Seq_in_index' => 2, 'Column_name' => 'city'],
            ];
        }
        return [
            ['title' => '土星冲日', 'event_time_bj' => '2026-10-04 20:29:16'],
            ['title' => '英仙座流星雨极大', 'event_time_bj' => '2026-08-12 22:00:00'],
        ];
    }
}
$wpdb = new KCJ_Stub_WPDB();

/* ---- 载入被测文件 ---- */
// shortcodes.php 顶层只做 add_action / add_shortcode 注册，不执行任何渲染 ⇒ 可安全载入。
// 它同时给出期间口径函数 kcj_astro_report_range()，供下面的跨语言对拍使用。
require getenv('KCJ_PLUGIN_DIR') . '/includes/shortcodes.php';
require getenv('KCJ_PLUGIN_DIR') . '/includes/rankmath.php';
/* ★ v2.3.1：导入器也纳入桩测试。顶层只 define 常量 + add_action 注册，可安全载入。
   —— 在这之前，`includes/rest-import.php` **从未被执行过一次**（F61 的土壤）。 */
require getenv('KCJ_PLUGIN_DIR') . '/includes/rest-import.php';

/* ---- 分支：期间口径（纯函数，与 Rank Math 无关），供跨语言对拍 ----
 * 为什么必须真跑 PHP：期间口径在 PHP 与 Python 各有一份实现，
 * 分岔只在闰日附近显现（＋365 天 vs 日历月加法，差一天），静态读码看不出。
 * 顺带把「短代码是否注册齐」也带出来 —— 这是「加了个函数但没接线」的现成哨兵。 */
if ($GLOBALS['kcj_case'] === 'report_range') {
    $ranges = [];
    foreach (['month', 'quarter', 'year', 'next12'] as $p) {
        $r = kcj_astro_report_range($p);
        $ranges[$p] = [
            'start' => $r['start'],
            'end'   => $r['end'],
            'label' => kcj_astro_period_label($p, $r),
        ];
    }
    echo json_encode(
        ['case' => 'report_range', 'today' => current_time('Y-m-d'),
         'registered' => array_keys($GLOBALS['kcj_shortcodes']), 'ranges' => $ranges],
        JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES), "\n";
    exit(0);
}

/* ---- 分支：历史栏目的两条纯函数（分组键 / 日期跳转）----
 * 为什么要把它们从模板与闭包里抽出来单测：
 *   ① 分组键**只许剥「日期形」括号**；行星标题里的「（转逆行）」是语义不是日期，
 *      一刀切地剥会把「留·转逆行」与「留·转顺行」并成一组（两种相反的天象混在一起）。
 *   ② 日期跳转的天数加减若不用闰年做基准，**02-29 永远不可达**（从 02-28 加一天跳到 03-01）。
 *   这两条都藏在「看一眼觉得对」的地方，只有真跑才现形。 */
if ($GLOBALS['kcj_case'] === 'history_helpers') {
    $titles = [
        '英仙座流星雨极大（2025-08-12）',
        '月全食（1900-06-13）',
        '土星冲日',
        '土星留（转逆行）',
        '土星留（转顺行）',
    ];
    $keys = [];
    foreach ($titles as $t) { $keys[$t] = kcj_astro_history_group_key($t); }

    // 跳转：对每个基准月日给出四个偏移后的月日（顺序＝前7天/前一天/后一天/后7天）
    $probe_md = ['02-28', '02-29', '12-31', '01-01', '03-01'];
    $nav = [];
    foreach ($probe_md as $md) {
        $parts = explode('-', $md);
        $nav[$md] = array_map(
            function ($x) { return $x['md']; },
            kcj_astro_history_nav((int) $parts[0], (int) $parts[1]));
    }
    echo json_encode(['case' => 'history_helpers', 'keys' => $keys, 'nav' => $nav],
        JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES), "\n";
    exit(0);
}

/* ---- 分支：栏目激活态（v2.2.7 / F52）----
 * 为什么必须真跑 PHP、而不是读码：
 *   用户报的缺陷（未来栏点「本月/本季/本年」、历史栏点「前一天/后七天」都跳回今日天象）
 *   **既没有报错、也没有坏数据** —— 数据其实已经换对了，只是躺在第 2、3 栏里，
 *   而页面停在第 1 栏。这种「界面在骗人」只能靠「渲染出来哪个 radio 带 checked」来判，
 *   而恰恰是这一处最容易在通读源码时被看漏（本轮改的就是它）。
 * 两件事一起测：① 解析器怎么定栏；② 模板渲染出来 checked 落在谁身上。 */
if ($GLOBALS['kcj_case'] === 'hub_tabs') {
    $SEC = [
        ['key' => 'today',  'title' => '今日天象',       'sub' => 'a', 'html' => 'TODAY'],
        ['key' => 'future', 'title' => '未来天象预告',   'sub' => 'b', 'html' => 'FUTURE'],
        ['key' => 'past',   'title' => '历史上今日天象', 'sub' => 'c', 'html' => 'PAST'],
    ];
    $probes = [
        'none'    => [],                                             // 无参数 ⇒ 第一栏
        'period'  => ['kcj_period' => 'quarter'],                    // 未来栏自己的参数
        'md'      => ['kcj_md' => '09-24'],                          // 历史栏自己的参数
        'both'    => ['kcj_period' => 'year', 'kcj_md' => '09-24'],  // 两个都在（期间链接会保留 kcj_md）
        'tab_win' => ['kcj_tab' => 'past', 'kcj_period' => 'month'], // 显式指定压过推断
        'tab_bad' => ['kcj_tab' => 'nosuch', 'kcj_md' => '09-24'],   // 非法值 ⇒ 落到兜底，不得开空白栏
        'col_off' => ['kcj_period' => 'month'],                      // 未来栏被作者关掉（下面换更短的 sections）
    ];
    $reduced = ['col_off' => true];
    $res = [];
    foreach ($probes as $name => $get) {
        $_GET  = $get;
        $secs  = isset($reduced[$name]) ? [$SEC[0], $SEC[2]] : $SEC;
        $res[$name] = [
            'key'  => kcj_astro_hub_active_key($secs),
            'keys' => array_map(function ($s) { return $s['key']; }, $secs),
        ];
    }
    $_GET = [];
    $h2 = kcj_astro_render_template('astro-hub',
        ['sections' => $SEC, 'tabs' => true, 'active_i' => 2, 'uniq' => 'ab12cd34']);
    $h0 = kcj_astro_render_template('astro-hub',
        ['sections' => $SEC, 'tabs' => true, 'active_i' => 0, 'uniq' => 'ab12cd34']);
    $hx = kcj_astro_render_template('astro-hub',
        ['sections' => $SEC, 'tabs' => true, 'active_i' => 99, 'uniq' => 'ab12cd34']);
    echo json_encode([
        'case'        => 'hub_tabs',
        'res'         => $res,
        'n2'          => substr_count($h2, 'checked="checked"'),
        'id2'         => kcj_hub_checked_ids($h2),
        'n0'          => substr_count($h0, 'checked="checked"'),
        'id0'         => kcj_hub_checked_ids($h0),
        'nx'          => substr_count($hx, 'checked="checked"'),
        'idx'         => kcj_hub_checked_ids($hx),
        'active_attr' => substr_count($h2, 'data-kcj-active="2"'),
        'has_script'  => (strpos($h2, '<script') !== false),
        'len'         => strlen($h2),
    ], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES), "\n";
    exit(0);
}

/* ---- 分支：导入器「多行快路径」真跑（v2.3.1 · F61）----
 * 为什么必须真跑、而且必须**走进闭包里面**：
 *   线上站点健康页报 `Call to a member function prepare() on null`（rest-import.php，
 *   导入 daily_site 时）。根因是 `$flush` 闭包内用了 `$wpdb`，而 PHP 闭包**不继承外层
 *   作用域** —— 外层那句 `global $wpdb;` 到不了闭包里，闭包内 `$wpdb` 是 null。
 *   当时 41 项全绿里**没有任何一条调用过这条快路径**：
 *   判据没覆盖 ≠ 判据通过，一个必崩的分支就这么躺在「全绿」背后上了线。
 * 本用例除「不崩」外，还断言三件**只有真跑才看得见**的事：
 *   ① 两行合成**一条**语句（快路径的本意，否则等于没提速）；
 *   ② NULL 写成**字面 NULL**（走 %s 会被 wpdb 转成空串 —— 「没有数据」≠「空」）；
 *   ③ 唯一键列**不出现在 UPDATE 子句**里（自赋值无意义）。
 */
if ($GLOBALS['kcj_case'] === 'bulk_upsert') {
    $cols = kcj_astro_rest_columns('daily_site');
    $base = [
        'date_str' => '2026-09-23', 'lat' => 22.55, 'lon' => 114.06, 'elev_m' => 6,
        'tz' => 'Asia/Shanghai', 'sunrise_bj' => '06:12', 'sunset_bj' => '18:20',
        'day_length_min' => 728,
        'tw_civil_begin' => null,        // ← 专门测「字面 NULL」这一支
        'tw_civil_end' => null,
        'tw_nautical_begin' => '', 'tw_nautical_end' => '',
        'tw_astro_begin' => '', 'tw_astro_end' => '',
        'moonrise_bj' => '', 'moonset_bj' => '',
        'method' => 'stub', 'data_version' => '1',
    ];
    $rows = [
        array_merge($base, ['city' => 'shenzhen', 'city_cn' => '深圳']),
        array_merge($base, ['city' => 'jieyang',  'city_cn' => '揭阳']),
        ['foo' => 'bar'],                // ← 全在白名单之外 ⇒ normalize 后为空 ⇒ 必须 deferred
    ];
    $res = kcj_astro_rest_bulk_upsert('daily_site', $rows, $cols);
    $sql = isset($GLOBALS['kcj_sql'][0]) ? (string) $GLOBALS['kcj_sql'][0] : '';
    $upd = '';
    if (($p = strpos($sql, 'ON DUPLICATE KEY UPDATE')) !== false) {
        $upd = substr($sql, $p);
    }
    echo json_encode([
        'case'          => 'bulk_upsert',
        'survived'      => true,     // 能走到这里，就证明闭包内没有 null->prepare()
        'is_array'      => is_array($res),
        'written'       => is_array($res) ? $res['written'] : null,
        'failed'        => is_array($res) ? $res['failed'] : null,
        'deferred_keys' => is_array($res) ? array_keys($res['deferred']) : [],
        'sql_count'     => count($GLOBALS['kcj_sql']),
        'sql_head'      => substr($sql, 0, 160),
        'has_update'    => ($upd !== ''),
        'null_literal_n'=> substr_count($sql, 'NULL'),
        // UPDATE 子句里出现唯一键列 = 把「判重依据」当普通列回写（不该有）
        'uk_in_update'  => (strpos($upd, '`date_str`') !== false || strpos($upd, '`city`') !== false),
    ], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES), "\n";
    exit(0);
}

/* ---- 复现 Rank Math 的 json_ld() 主干（源码：includes/modules/schema/class-jsonld.php） ----
 *   $data = array_filter( $this->do_filter( 'json_ld', [], $this ) );
 *   if ( empty( $data ) ) { return; }              // ⇒ 整页零 JSON-LD
 *   echo '<script …>' . wp_json_encode(['@context'=>…, '@graph'=>array_values($data)]) . '</script>';
 * 我们只跑「本插件的回调」，并额外模拟「站点级实体是否会被补上」这一步：
 *   Rank Math 的 add_context_data() 挂优先级 10，其 can_add_global_entities() 在 singular 页
 *   先看 `! empty( $data )`（class-jsonld.php L379）。
 */
$data = [];
$prios = [];
foreach ($GLOBALS['kcj_hooks']['rank_math/json_ld'] as $h) {
    $prios[] = ['prio' => $h['prio'], 'args' => $h['args']];
    $data = call_user_func($h['cb'], $data, null);
}
$data = array_filter((array) $data);

// ★ 先留一份「本插件自己的产出」：下面的站点级实体是模拟 Rank Math 补的，
//   两者混在一起就无法判定「某个 @type 到底是谁出的」——这是本工具的第一个自咬点。
$plugin_data  = $data;
$plugin_types = array_values(array_map(function ($n) { return isset($n['@type']) ? $n['@type'] : null; }, array_values($plugin_data)));

// 站点级实体是否会被 Rank Math 补上（按 L379 的判据：本插件回调早于 10 点 ⇒ 非空即成立）
$first_prio = $prios ? min(array_column($prios, 'prio')) : PHP_INT_MAX;
$globals_added = ($first_prio < 10) && ! empty($data);
if ($globals_added) {
    $data[] = ['@type' => 'Person', '@id' => home_url('/') . '#person'];
    $data[] = ['@type' => 'WebSite', '@id' => home_url('/') . '#website'];
    $data[] = ['@type' => 'WebPage', '@id' => home_url('/') . '#webpage'];
}

$out = [
    'case'            => $GLOBALS['kcj_case'],
    'context'         => kcj_astro_schema_context(),
    'hook_priorities' => $prios,
    'globals_added'   => $globals_added,
    'graph_empty'     => empty($data),
    'plugin_types'    => $plugin_types,
    'graph'           => array_values($data),
    'types'           => array_values(array_map(function ($n) { return isset($n['@type']) ? $n['@type'] : null; }, array_values($data))),
];
echo json_encode($out, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT), "\n";
"""


# ── 工具 ──────────────────────────────────────────────────────────────────────
def find_php(explicit=None):
    if explicit:
        return explicit if os.path.isfile(explicit) else None
    if os.environ.get("PHP_BIN") and os.path.isfile(os.environ["PHP_BIN"]):
        return os.environ["PHP_BIN"]
    managed = os.path.join(os.path.expanduser("~"), ".workbuddy", "binaries", "php")
    hits = sorted(glob.glob(os.path.join(managed, "*", "php.exe"))) or \
           sorted(glob.glob(os.path.join(managed, "*", "bin", "php")))
    if hits:
        return hits[-1]
    return shutil.which("php")


def plugin_php_files():
    out = []
    for dirpath, dirnames, filenames in os.walk(PLUGIN_DIR):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(".php"):
                out.append(os.path.join(dirpath, fn))
    return sorted(out)


def lint(php, files):
    results = []
    for f in files:
        p = subprocess.run([php, "-n", "-l", f], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        results.append({
            "file": os.path.relpath(f, HERE).replace("\\", "/"),
            "ok": p.returncode == 0,
            "out": (p.stdout or "").strip() or (p.stderr or "").strip(),
        })
    return results


def run_case(php, harness, case, no_rankmath=False, now=None):
    env = dict(os.environ)
    env["KCJ_PLUGIN_DIR"] = PLUGIN_DIR
    if no_rankmath:
        env["KCJ_NO_RANKMATH"] = "1"
    else:
        env.pop("KCJ_NO_RANKMATH", None)
    if now:
        env["KCJ_NOW"] = str(now)          # 覆盖桩里的基准时刻（期间口径对拍用）
    else:
        env.pop("KCJ_NOW", None)
    p = subprocess.run([php, "-n", harness, case], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    if p.returncode != 0:
        raise RuntimeError("harness(%s) rc=%s\n%s\n%s" % (case, p.returncode, p.stdout, p.stderr))
    return json.loads(p.stdout)


def types_of(g, t):
    return [n for n in g if n.get("@type") == t]


# ── 主流程 ────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--php", default=None, help="php 可执行文件路径")
    ap.add_argument("--lint-only", action="store_true")
    ap.add_argument("--json", action="store_true", help="只输出 JSON 结果")
    args = ap.parse_args()

    checks = []          # (名称, 是否通过, 说明)
    def chk(name, ok, note=""):
        checks.append({"name": name, "ok": bool(ok), "note": note})

    php = find_php(args.php)
    if not php:
        print("找不到 PHP 可执行文件。请用 --php 指定，或看本文件头的「查找顺序」。")
        return 2
    if not os.path.isdir(PLUGIN_DIR):
        print("找不到插件目录：%s" % PLUGIN_DIR)
        return 2

    files = plugin_php_files()
    linted = lint(php, files)
    bad = [r for r in linted if not r["ok"]]
    chk("语法闸：插件内 %d 个 *.php 全部通过 php -l" % len(linted), not bad,
        "; ".join("%s → %s" % (b["file"], b["out"]) for b in bad))

    payload = {"php": php, "php_version": subprocess.run(
        [php, "-n", "-v"], capture_output=True, text=True).stdout.splitlines()[0:1],
        "lint": linted}

    if not args.lint_only and not bad:
        td = tempfile.mkdtemp(prefix="kcj_php_selftest_")
        harness = os.path.join(td, "harness.php")
        with open(harness, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(HARNESS)
        cases = {}
        try:
            for c in ("event", "event_with_rankmath_meta", "historical", "collection",
                      "daily", "daily_no_shortcode", "hub_page", "hub_page_today_off"):
                # ★ hub_page 的数据集日期取自 current_time('Y-m-d') ⇒ 必须钉住基准日，
                #   否则断言「= 2026-09-23」会在跨日时假红（尤其是 00:00 前后）。
                # ⚠ 第二次 run_case 只能写在**这个 try 块内** —— 桩在 finally 里就删了，
                #   写在外面报的是「Could not open input file」，与缺陷无关（本轮已踩）。
                cases[c] = run_case(php, harness, c,
                                    now=("2026-09-23" if c == "hub_page" else None))
            # 回退路径：Rank Math 未启用 ⇒ 四类全由本插件出（不能因为装了 RM 才有 schema）
            fallback = {}
            for c in ("event", "collection", "daily"):
                fallback[c] = run_case(php, harness, c, no_rankmath=True)

            # ⑨ ★ v2.0.0：期间口径的**跨语言对拍**（PHP 真跑 ↔ Python 同一函数）。
            #   必须放在 try 块内 —— harness 在 finally 里就被删了，
            #   放到 finally 之后再跑只会得到「Could not open input file」。
            #   为什么必须换多组基准日：next12 的两种错法（＋365 天 / strtotime 加月）
            #   **只在闰日附近分岔**，用固定基准日永远测不出来 —— 这正是「判据与适用面
            #   不匹配」的老毛病，故基准日里必须同时含「起算年是闰年」与「起算日恰是闰日」
            #   两种成因，缺一条就等于没测。
            probes = ["2026-09-23", "2026-12-15", "2027-03-01", "2027-12-31", "2028-02-29"]
            try:
                py_dir = os.path.join(HERE, "python")
                if py_dir not in sys.path:
                    sys.path.insert(0, py_dir)
                import datetime as _dt
                import gen_astro_report as gar
                diffs = []
                php_r = None
                for today_s in probes:
                    php_r = run_case(php, harness, "report_range", now=today_s)
                    if php_r.get("today") != today_s:
                        diffs.append("基准日回读不符：%s → %s" % (today_s, php_r.get("today")))
                    y, m, d = (int(x) for x in today_s.split("-"))
                    for per in ("month", "quarter", "year", "next12"):
                        s, e, lab = gar.period_range(per, _dt.date(y, m, d))
                        got = php_r["ranges"][per]
                        if got["start"] != s.isoformat() or got["end"] != e.isoformat():
                            diffs.append("%s/%s：PHP %s→%s vs PY %s→%s" % (
                                today_s, per, got["start"], got["end"],
                                s.isoformat(), e.isoformat()))
                        elif got["label"] != lab:
                            diffs.append("%s/%s 标签：PHP %r vs PY %r"
                                         % (today_s, per, got["label"], lab))
                chk("★ 期间口径跨语言对拍（PHP 真跑 ↔ Python；%d 基准日 × 4 期间）" % len(probes),
                    not diffs, "; ".join(diffs[:4]))
                reg = (php_r or {}).get("registered") or []
                need_sc = ["astro_today", "astro_forecast_list", "astro_related_events",
                           "astro_history_today", "astro_forecast_report", "astro_event_detail",
                           "astro_hub"]
                chk("★ 短代码注册齐（%d 个，含 v2.0.0 新增 3 个）" % len(need_sc),
                    all(t in reg for t in need_sc),
                    "缺 %s" % [t for t in need_sc if t not in reg])

                # ⑩ ★ v2.1.0：历史栏目的两条纯函数（配对在哪个函数里见 harness 的说明）
                hh = run_case(php, harness, "history_helpers")
                hkeys = hh.get("keys") or {}
                hnav = hh.get("nav") or {}
                k_bad = []
                if hkeys.get("英仙座流星雨极大（2025-08-12）") != "英仙座流星雨极大":
                    k_bad.append("流星雨标题的日期括号未被剥掉")
                if hkeys.get("月全食（1900-06-13）") != "月全食":
                    k_bad.append("月食标题的日期括号未被剥掉")
                if hkeys.get("土星冲日") != "土星冲日":
                    k_bad.append("无括号标题被改动")
                # ★ 本条才是重点：语义括号**不得**被剥 ⇒ 两类「留」必须仍是两组
                if hkeys.get("土星留（转逆行）") == hkeys.get("土星留（转顺行）"):
                    k_bad.append("「转逆行／转顺行」被并成同一组（语义括号被误剥）")
                chk("★ 分组键只剥「日期形」括号（语义括号不得剥、不得并组）",
                    not k_bad, "; ".join(k_bad) or "5 个样本全对")

                n_bad = []

                def _nav(md, idx, exp):
                    got = hnav.get(md) or []
                    if len(got) < 4:
                        n_bad.append("%s 跳转项不足（%d 个）" % (md, len(got)))
                    elif got[idx] != exp:
                        n_bad.append("%s 第 %d 项 %s ≠ %s" % (md, idx, got[idx], exp))

                # ★ 02-28 的「后一天」必须是 02-29 —— 用非闰年做基准时会算成 03-01
                _nav("02-28", 2, "02-29")
                _nav("02-29", 1, "02-28")
                _nav("12-31", 2, "01-01")
                _nav("01-01", 1, "12-31")
                chk("★ 日期跳转用闰年基准（02-28 后一天必须可达 02-29）",
                    not n_bad, "; ".join(n_bad) or "4 个基准日 × 4 偏移全对")

                # ⑫ ★ v2.3.1（F61）：导入器「多行快路径」**真跑**。
                #    为什么单列出来：这条路径上线前**从未被执行过一次**，而它一执行就必崩
                #    （闭包内 `$wpdb` 为 null ⇒ 线上「Call to a member function prepare()
                #    on null」）。把「判据没覆盖到」显式地变成一条会失败的检查。
                try:
                    bu = run_case(php, harness, "bulk_upsert")
                    bu_err = ""
                except Exception as ex3:
                    bu = {}
                    bu_err = "%r" % (ex3,)
                # ⚠ 无论成败都出声：跑不起来 ≠ 通过（会静默少一条，条数就不再是判据）
                chk("★ 导入器快路径桩用例可运行（bulk_upsert；F61 的现场）",
                    not bu_err, bu_err or "rc=0")

                bb = []
                if not bu.get("survived"):
                    bb.append("未走完函数体（疑似闭包内 null->prepare() 致命错误）")
                if not bu.get("is_array"):
                    bb.append("返回不是数组（应为 written/failed/deferred 结构）")
                if bu.get("written") != 2:
                    bb.append("written=%r（应为 2）" % (bu.get("written"),))
                if bu.get("failed") != 0:
                    bb.append("failed=%r（应为 0）" % (bu.get("failed"),))
                if bu.get("sql_count") != 1:
                    bb.append("发了 %r 条语句（两行应合成 1 条，否则等于没提速）"
                              % (bu.get("sql_count"),))
                if not bu.get("has_update"):
                    bb.append("缺 ON DUPLICATE KEY UPDATE（重导就不幂等）")
                if bu.get("null_literal_n") != 4:
                    bb.append("字面 NULL 出现 %r 次（2 行 × 2 列应为 4；走 %%s 会变空串）"
                              % (bu.get("null_literal_n"),))
                if bu.get("uk_in_update"):
                    bb.append("唯一键列出现在 UPDATE 子句里（判重依据不该回写）")
                if list(bu.get("deferred_keys") or []) != [2]:
                    bb.append("deferred 行号 %r（应为 [2]：第三行全在白名单之外）"
                              % (bu.get("deferred_keys"),))
                chk("★ 导入器快路径行为（合成一条语句／字面 NULL／唯一键不回写／非法行交回慢路径）",
                    not bb, "; ".join(bb) or "6 项断言全过")

                # ⑪ ★ v2.2.7（F52）：栏目激活态。
                #    三栏是纯 CSS radio 切换，radio 状态不随重载保留 ⇒
                #    此前栏内一点跳转（换期间 / 换日子）就丢回第一栏：数据换对了、
                #    界面停在别处（用户线上报的「点了都跳回今日天象」）。
                #    ⚠ 单独 try：若本用例自身跑不起来，必须报成「跑不起来」，
                #      不能混进上一条的异常文案（那会把「测不了」说成「测过了」）。
                try:
                    hub = run_case(php, harness, "hub_tabs")
                    hub_err = ""
                except Exception as ex2:
                    hub = {}
                    hub_err = "%r" % (ex2,)
                # ★ 这一条**无论成败都要出声**：失败时若只是静默少一条，
                #   总条数会随情形浮动 ⇒ 「条数对不对」本身就不再是判据（本项目踩过）。
                chk("★ 栏目激活态桩用例可运行（hub_tabs）", not hub_err, hub_err or "rc=0")
                hres = hub.get("res") or {}

                def _hk(n):
                    return (hres.get(n) or {}).get("key")

                b0 = []
                if _hk("none") != "today":
                    b0.append("无参数 → %s（应为第一栏 today）" % _hk("none"))
                if _hk("period") != "future":
                    b0.append("?kcj_period= → %s（应为 future）" % _hk("period"))
                if _hk("md") != "past":
                    b0.append("?kcj_md= → %s（应为 past）" % _hk("md"))
                chk("★ 解析器按 URL 定栏（三种基本情形）", not b0, "; ".join(b0) or "3 个样本全对")

                b1 = []
                if _hk("tab_win") != "past":
                    b1.append("?kcj_tab=past 且带 kcj_period → %s（显式指定必须压过推断）" % _hk("tab_win"))
                if _hk("tab_bad") != "past":
                    b1.append("?kcj_tab=nosuch → %s（非法值不得当成未知栏，须落到兜底）" % _hk("tab_bad"))
                chk("★ 显式 kcj_tab 优先，非法值不认（认了会开出空白栏）",
                    not b1, "; ".join(b1) or "2 个样本全对")

                b2 = []
                if _hk("both") != "future":
                    b2.append("两参数同在 → %s（期间链接会保留 kcj_md，故必须有确定口径）" % _hk("both"))
                if _hk("col_off") != "today":
                    b2.append("future 栏被作者关掉时 → %s（不得认页面上不存在的栏）" % _hk("col_off"))
                chk("★ 旧链接兜底口径确定 ＋ 已关掉的栏不认", not b2, "; ".join(b2) or "2 个样本全对")

                b3 = []
                if hub.get("n2") != 1 or not str(hub.get("id2", "")).endswith("-t2"):
                    b3.append("active_i=2 → checked %s 个 %r（应为 1 个 …-t2）"
                              % (hub.get("n2"), hub.get("id2")))
                if hub.get("n0") != 1 or not str(hub.get("id0", "")).endswith("-t0"):
                    b3.append("active_i=0 → checked %s 个 %r（应为 1 个 …-t0）"
                              % (hub.get("n0"), hub.get("id0")))
                if hub.get("active_attr") != 1:
                    b3.append("data-kcj-active 未落成 2（%s 次）" % hub.get("active_attr"))
                chk("★★ 渲染出来 checked 只落一个、且落在 $active_i 那一栏", not b3,
                    "; ".join(b3) or "active_i=2 → …-t2；active_i=0 → …-t0")

                b4 = []
                if hub.get("nx") != 1 or not str(hub.get("idx", "")).endswith("-t0"):
                    b4.append("越界 active_i=99 → checked %s 个 %r（应夹紧到 …-t0 一个）"
                              % (hub.get("nx"), hub.get("idx")))
                chk("★ 越界下标夹紧到第一栏（一个都不 checked 会让三栏同时显示）",
                    not b4, "; ".join(b4) or "夹紧生效")

                chk("★ 模板不含任何脚本（修法是服务端定栏，不靠 JS 拦跳转）",
                    hub.get("has_script") is False,
                    "has_script=%s｜渲染长度=%s" % (hub.get("has_script"), hub.get("len")))
            except Exception as ex:
                chk("★ 期间口径跨语言对拍（PHP 真跑 ↔ Python）", False, "异常：%r" % (ex,))
        finally:
            shutil.rmtree(td, ignore_errors=True)
        payload["cases"] = cases
        payload["fallback_no_rankmath"] = fallback

        # ① 未来事件：必须出 Event，且带时区偏移、作者、无杜撰 location
        ev = cases["event"]
        ev_nodes = types_of(ev["graph"], "Event")
        chk("event 上下文命中（is_singular(astro_event)）", ev["context"] == "event", ev["context"])
        chk("未来事件页出 1 个 Event 节点", len(ev_nodes) == 1, "types=%s" % ev["types"])
        if ev_nodes:
            n = ev_nodes[0]
            chk("Event.startDate 带 +08:00 偏移", str(n.get("startDate", "")).endswith("+08:00"), n.get("startDate"))
            chk("Event.organizer 为 Person", (n.get("organizer") or {}).get("@type") == "Person")
            chk("Event 不杜撰 location（无 obs_site 时不得出现）", "location" not in n)
            chk("Event.name 与事件标题逐字一致", n.get("name") == "土星冲日", n.get("name"))
        chk("★ 本插件回调优先级 < 10（决定站点级实体能否被 Rank Math 补回）",
            bool(ev["hook_priorities"]) and min(h["prio"] for h in ev["hook_priorities"]) < 10,
            "prios=%s" % ev["hook_priorities"])
        chk("★ 因此站点级实体（Person/WebSite/WebPage）在事件页恢复输出", ev.get("globals_added") is True)
        chk("★ 整页非空 ⇒ Rank Math 的 empty($data) 早退不会发生", ev["graph_empty"] is False)

        # ② 负控制：某篇已有 rank_math_schema_* 元数据 ⇒ 本插件必须让位
        hm = cases["event_with_rankmath_meta"]
        chk("负控制：已有文章级 schema 时本插件让位（不出 Event）",
            not types_of(hm["graph"], "Event"), "types=%s" % hm["types"])

        # ③ 历史天象：ScholarlyArticle
        hs = cases["historical"]
        sa = types_of(hs["graph"], "ScholarlyArticle")
        chk("历史天象出 ScholarlyArticle", len(sa) == 1, "types=%s" % hs["types"])
        if sa:
            chk("ScholarlyArticle 带 citation（有 source_ref 时）", sa[0].get("citation", {}).get("name") == "《宋史·天文志》")
            chk("ScholarlyArticle.method 译成人读措辞（analytic_meeus）",
                "Meeus" in str(sa[0].get("measurementTechnique", "")), sa[0].get("measurementTechnique"))
            chk("历史天象不出现 Event（两条分支互斥）", not types_of(hs["graph"], "Event"))

        # ④ 归档：CollectionPage 交给 Rank Math（本插件不重复出）
        cl = cases["collection"]
        chk("归档页本插件不出 CollectionPage（避免与 Rank Math 重复）",
            not types_of(cl["graph"], "CollectionPage"), "types=%s" % cl["types"])

        # ⑤ 今日天象：出 Dataset，WebPage 交给 Rank Math
        dl = cases["daily"]
        chk("含 [astro_today] 的页面出 Dataset", dl["plugin_types"].count("Dataset") == 1, "plugin_types=%s" % dl["plugin_types"])
        chk("daily 上下文不重复出 WebPage（交给 Rank Math）", "WebPage" not in dl["plugin_types"],
            "plugin_types=%s" % dl["plugin_types"])

        # ⑥ 负控制：页面不含短代码 ⇒ 不得给无关页面挂数据集声明
        dn = cases["daily_no_shortcode"]
        chk("负控制：页面不含 [astro_today] 时本插件不出任何节点", not dn["plugin_types"], "plugin_types=%s" % dn["plugin_types"])
        chk("★ 负控制：不得出现日期为空的 Dataset（原 v1.2.x 在首页/博文上输出「揭阳每日天象数据集（）」）",
            not [n for n in dl["graph"] + dn["graph"] if n.get("@type") == "Dataset" and not n.get("temporalCoverage")],
            "types=%s" % dn["types"])

        # ⑥-b ★ v2.3.2（F62）：「天象预告」页用的是 [astro_hub]，不是 [astro_today]。
        #   它的「今日天象」栏默认开启、三栏都渲染进 HTML ⇒ 页面上确实有今日天象内容，
        #   必须同样声明 Dataset。线上探针 H 项报红抓到的就是这个缺口。
        hp = cases["hub_page"]
        chk("★ 含 [astro_hub] 的页面出 Dataset（hub 的「今日天象」栏默认开启）",
            hp["plugin_types"].count("Dataset") == 1, "plugin_types=%s" % hp["plugin_types"])
        _ds = types_of(hp["graph"], "Dataset")
        chk("★ [astro_hub] 页的 Dataset 用「今天」（dateModified/temporalCoverage = 2026-09-23）",
            bool(_ds) and _ds[0].get("dateModified") == "2026-09-23"
            and _ds[0].get("temporalCoverage") == "2026-09-23",
            "nodes=%s" % json.dumps(_ds[:1], ensure_ascii=False))
        hpo = cases["hub_page_today_off"]
        chk("负控制：[astro_hub today=\"0\"] 时不得声明 Dataset（该栏在页面上不存在）",
            not hpo["plugin_types"], "plugin_types=%s" % hpo["plugin_types"])

        # ⑧ 回退路径：Rank Math 未启用时，四类必须全由本插件出
        fb_ev = fallback["event"]
        chk("回退：Rank Math 未启用 ⇒ 事件页仍出 Event", len(types_of(fb_ev["graph"], "Event")) == 1,
            "types=%s" % fb_ev["types"])
        chk("回退：Rank Math 未启用 ⇒ 归档页仍出 CollectionPage",
            len(types_of(fallback["collection"]["graph"], "CollectionPage")) == 1,
            "types=%s" % fallback["collection"]["types"])
        fb_dl = fallback["daily"]
        chk("回退：Rank Math 未启用 ⇒ daily 上下文出 WebPage + Dataset",
            fb_dl["plugin_types"].count("WebPage") == 1 and fb_dl["plugin_types"].count("Dataset") == 1,
            "plugin_types=%s" % fb_dl["plugin_types"])
        chk("回退：不因装了 Rank Math 才补站点级实体（两条路径都非空）",
            all(not v["graph_empty"] for v in fallback.values()))

        # ⑦ 结构闸：所有输出必须是可解析的 JSON、graph 为列表
        for c, v in cases.items():
            try:
                json.dumps(v["graph"], ensure_ascii=False)
                ok = isinstance(v["graph"], list)
            except Exception:
                ok = False
            chk("结构闸：%s 的 @graph 可 JSON 序列化且为列表" % c, ok)

    n_ok = sum(1 for c in checks if c["ok"])
    payload["checks"] = checks
    payload["summary"] = {"pass": n_ok, "fail": len(checks) - n_ok, "total": len(checks)}

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=1))
    else:
        print("PHP 自检 ｜ %s" % payload["php_version"][0] if payload["php_version"] else "PHP 自检")
        print("-" * 72)
        for c in checks:
            print("%s %s%s" % ("PASS" if c["ok"] else "FAIL", c["name"],
                               ("  ← %s" % c["note"]) if (not c["ok"] and c["note"]) else ""))
        print("-" * 72)
        print("通过 %d / %d%s" % (n_ok, len(checks),
                                "" if n_ok == len(checks) else "　★ 有未通过项，插件包不得上传"))
    return 0 if n_ok == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
