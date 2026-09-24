<?php
/**
 * 短代码层（指令 05；v2.0.0 扩到 5 个；v2.3.6 加观测地总览页，共 6 个）
 *
 * 五个短代码：
 *   1. [astro_today date="YYYY-MM-DD" place="auto|城市键|off"]   今日天象板块
 *      · 不传 date 取站点当天；place 控制**观测地**：auto（默认，由 IP/时区推断，可手动切换）、
 *        城市键（固定为该城，隐藏切换器）、off（不查观测地表，纯地心量）。
 *   2. [astro_forecast_list type="..." side="future|past|all"]    天象预告列表（Tab 切换）
 *      type 取值：solar | lunar | solar_eclipse | lunar_eclipse | eclipse |
 *                 planet | meteor | traditional | historical ；留空 = 全部 Tab
 *      ★ side（v2.0.0 新增）默认 future。历史回推的日月食与未来预告**同属一个 event_type**，
 *        不加这层过滤，1900 年的月食会混进「未来预告」列表 —— 这是新数据一入库就会发生的事。
 *   3. [astro_related_events id="N"]           古今对照模块（同类型历史/未来天象）
 *   4. [astro_history_today date="MM-DD"]      **历史上今日天象**（同月同日的日月食，按年倒序）
 *   5. [astro_forecast_report period="month|quarter|year|next12"]  **月/季/年度报告**（页面展示 ＋ 下载）
 *
 *   6. [astro_places_hub title=""]           **观测地总览页**（v2.3.6；省份 Tab ＋ 城市网格的独立落点）
 *
 * 另保留 [astro_event_detail id="N"]（v1.1.0 旧名）——详情页模板与它共用同一渲染块，
 * 不删是为了不让已写好的页面失效；新页面请用 single-astro_event.php 或 [astro_related_events]。
 *
 * 渲染原则（v1.1.0 起）：只读预计算数据（数据表），前端**零实时计算**；
 *   全部输出经 esc_html/esc_attr/esc_url；查询一律 $wpdb->prepare 绑定。
 *   ①「观测地切换」不是计算 —— 38 城的升落/晨昏都是**预计算好的**，
 *     前端只是把已嵌在页面里的那一组值换上去（见 templates/astro-today.php）。
 *   ②「报告下载」也不是计算 —— 期间的条目由 PHP 查出来、序列化进页面，
 *     前端只做 Markdown 文本拼装与 Blob 下载。
 * 硬性约束：输出不含任何占星/运势/吉凶/谶纬内容；时区统一北京时间（UTC+8）。
 */

if (!defined('ABSPATH')) {
    exit;
}

// 样式与脚本（指令 06 的样式文件名：astro-style.css；v2.0.0 加两个脚本）
add_action('wp_enqueue_scripts', function () {
    wp_enqueue_style('kcj-astro', KCJ_ASTRO_URL . 'assets/astro-style.css', array(), KCJ_ASTRO_VER);
    // 观测地定位脚本：只在页面里真的有 [astro_today] 时才需要，但 WP 此时还不知道内容，
    // 故一律注册并置底加载（体积小；脚本自身对「页面上没有 .kcj-astro-place-bar」的情况
    // 直接 return，零副作用）。
    wp_enqueue_script('kcj-astro-place', KCJ_ASTRO_URL . 'assets/astro-place.js',
        array(), KCJ_ASTRO_VER, true);
    // 报告/历史天象的下载脚本。★ 之所以不做模板内联：本站正文会经平台后处理
    // （空行被换块级标签、某些窗口内的裸与号被换实体引用），而 script 内容不做实体解码
    // ⇒ 内联脚本会被拆断（v1.3.0「老黄历线上失效」的真因）。外置资源不经正文后处理。
    wp_enqueue_script('kcj-astro-report', KCJ_ASTRO_URL . 'assets/astro-report.js',
        array(), KCJ_ASTRO_VER, true);
});

/** 默认观测地键与中文名（与 compute_sky.CONFIG.OBS_CITY_KEY 一致：北京）
 *  ★ 开源发布注（2026-09-24）：默认地由作者常住地改为**北京**（中性默认）。
 *    部署时按需改这里 ＋ compute_sky.CONFIG.OBS_* 三行，两处必须同改。 */
function kcj_astro_default_place() {
    return array('key' => 'beijing', 'cn' => '北京');
}

/**
 * 观测地目录（v2.3.0）。
 * 数据源：`assets/places-cn.json` —— 由 `python/build_places.py` 与
 * `data/places_cn.json` **同一轮**产出（紧凑件里记着 canonical 的 sha1，校验器对拍）。
 * 形状：provinces[[adcode,name]] / anchors[[key,cn,prov,lat,lon]] / places[[adcode,cn,anchor,km]]
 *
 * ★ 为什么 PHP 也要读它，而不是只用数据库里那批：
 *   数据库里只有「当天有数据的那 N 个锚点」（平铺、无省市归属）。要让下拉**按省市分组**、
 *   并且**不依赖 JS** 就能选到任一预置观测地，就必须知道「谁属于哪个省」——
 *   那是地理元数据，不在库表里。
 * ★ 只在**渲染**时读一次（static 缓存 + 页面 transient）⇒ 不构成每请求开销。
 */
function kcj_astro_places_catalog() {
    static $cat = null;
    if ($cat !== null) {
        return $cat;
    }
    $cat = array();
    $f   = KCJ_ASTRO_PATH . 'assets/places-cn.json';
    if (!is_readable($f)) {
        return $cat;
    }
    $raw = file_get_contents($f);
    if ($raw === false || $raw === '') {
        return $cat;
    }
    $d = json_decode($raw, true);
    if (!is_array($d) || !isset($d['anchors']) || !is_array($d['anchors']) || !$d['anchors']) {
        return $cat;
    }
    $cat = $d;
    return $cat;
}

/** 目录里声明的锚点总数（＝应有几行观测地数据）。读不到则 0（调用方须区分「0」与「未知」） */
function kcj_astro_places_expected() {
    $c = kcj_astro_places_catalog();
    return isset($c['anchor_count']) ? (int) $c['anchor_count'] : 0;
}

/**
 * 「锚点 key → 省 adcode」（v2.3.5 新增）。
 * 供前端「跨省守卫」用：IP 报的省与命中锚点所在省不一致时，不下自动结论、只提示。
 * 数据源同 `kcj_astro_places_catalog()`，`anchors[i][2]` 即省 adcode（实测 34 种、末四位 0000）。
 * ★ 为什么在前端判而不是在 PHP 判：定位结果只有浏览器拿得到（IP 接口是前端调的），
 *   PHP 无从知道访问者在哪个省。故 PHP 只提供**映射表**，判定交给 JS。
 */
function kcj_astro_place_prov_map() {
    static $m = null;
    if ($m !== null) {
        return $m;
    }
    $m = array();
    $c = kcj_astro_places_catalog();
    if (!$c) {
        return $m;
    }
    $pname = array();
    foreach ((array) $c['provinces'] as $p) {
        if (isset($p[0])) {
            $pname[(string) $p[0]] = (string) (isset($p[1]) ? $p[1] : $p[0]);
        }
    }
    foreach ((array) $c['anchors'] as $a) {
        $key  = isset($a[0]) ? (string) $a[0] : '';
        $prov = isset($a[2]) ? (string) $a[2] : '';
        if ($key === '' || $prov === '') {
            continue;
        }
        $m[$key] = array('p' => $prov, 'n' => isset($pname[$prov]) ? $pname[$prov] : $prov);
    }
    return $m;
}

/**
 * 「省 → 该省锚点」分组，顺序照目录原序（＝官方 subFeatureIndex 顺序，华北→西南→港澳台）。
 * 返回 array( prov_adcode => array('name' => 省名, 'items' => array( key => cn )) )
 */
function kcj_astro_place_groups() {
    $c = kcj_astro_places_catalog();
    if (!$c) {
        return array();
    }
    $pname = array();
    foreach ((array) $c['provinces'] as $p) {
        if (isset($p[0])) {
            $pname[(string) $p[0]] = (string) (isset($p[1]) ? $p[1] : $p[0]);
        }
    }
    $out = array();
    foreach ((array) $c['anchors'] as $a) {
        $key  = isset($a[0]) ? (string) $a[0] : '';
        $cn   = isset($a[1]) ? (string) $a[1] : '';
        $prov = isset($a[2]) ? (string) $a[2] : '';
        if ($key === '') {
            continue;
        }
        if (!isset($out[$prov])) {
            $out[$prov] = array('name' => isset($pname[$prov]) ? $pname[$prov] : $prov, 'items' => array());
        }
        $out[$prov]['items'][$key] = $cn;
    }
    return $out;
}
/**
 * 模板渲染：把数据数组 extract 成同名变量后 include。
 * 模板内所有输出必须转义；数据键 → 变量名，故键名须为合法标识符。
 */
function kcj_astro_render_template($name, $data) {
    $tpl = KCJ_ASTRO_PATH . 'templates/' . $name . '.php';
    if (!file_exists($tpl)) {
        return '<p class="kcj-astro-error">模板缺失：' . esc_html($name) . '</p>';
    }
    if (!is_array($data)) {
        $data = array();
    }
    ob_start();
    extract($data, EXTR_SKIP);
    include $tpl;
    return ob_get_clean();
}

/**
 * 事件详情页 URL。
 * 优先走 WP 自己的固定链接（尊重站点的 permalink 设置），
 * 只有拿不到 post_id 时才退回按 slug 拼路径（路径口径 = sky-forecast）。
 */
function kcj_astro_event_permalink($row) {
    if (!empty($row['post_id'])) {
        $link = get_permalink((int) $row['post_id']);
        if ($link) {
            return $link;
        }
    }
    // ★ v2.3.0 加固：`slug` 原先**不加判断直接用** ⇒ 行里没有 slug 时 PHP 8 报
    //   「Undefined array key "slug"」并把警告**打进模板输出**（报告表里一眼可见）。
    //   更坏的是会拼出 `…/sky-forecast//` 这种**空 slug 链接**（点进去 404）。
    //   现在：没有 slug 就**不产链接**，由调用方退回纯文本。
    $slug = isset($row['slug']) ? trim((string) $row['slug']) : '';
    if ($slug === '') {
        return '';
    }
    return home_url('/' . KCJ_ASTRO_SLUG . '/' . rawurlencode($slug) . '/');
}

/** 后台/模板共用的错误与空数据提示（样式类名统一） */
function kcj_astro_notice($text, $cls = 'kcj-astro-nodata') {
    return '<p class="' . esc_attr($cls) . '">' . esc_html($text) . '</p>';
}

/* -------------------------------------------------------------------------
 * 短代码 8：观测地总览页（v2.3.6）
 *
 * 为什么单出一页（用户原话）：
 *   「这个界面太长了，不行！…… 首页首屏仅保留『当前选中城市』以及『按我的位置』按钮。
 *     将『两级联动省份标签+城市网格面板』完全移出首页，单独做成一个独立的 WordPress 页面。」
 *
 * 实测依据：线上首页 HTML 205,161 字符，其中城市相关（340 个 <option>、34 个 radio、
 *   34 个 tab、35 个 pane、41,007 字符载荷 JSON）约 100 KB、占 49%。
 *   ⇒ 首页被这团「城市文本」压得首屏全是字，正文与学术关键词被稀释。
 *
 * ★ 本页**不引入第二套数据路径**：
 *   网格仍由 assets/astro-place.js 的 buildGrid() 绑定，点击仍只做「替读者动 select」
 *   （value ＋ 派发 change）。本页的 select 是**本页自己的**，只用来承载「读者点的是哪一格」，
 *   真正的数据渲染发生在首页（或任何放了 [astro_today] 的页）——
 *   故本页选完城后写 localStorage（键 KCJ_PLACE_STORE）并**跳回来源页**。
 *
 * ★ 为什么不用伪静态 /observatories/<城市>/（用户意见④）：
 *   那会让 341 个城市各自成为一个**可索引 URL**，等于把「邝楚嘉在揭阳」结构化公开
 *   —— 与「不碰具体经济财务」「授权不授柄」及个人信息保护口径相悖。故本页只有一个 URL，
 *   城市选择**不进 URL**（与 v2.3.3「换城不换 URL」的纪律一致）。
 *
 * ★ 无 JS 降级：本页的 <select> 平铺可见（没有网格时它就是选择器），
 *   选中后**必须点「查看」按钮**才跳转 —— 一行原生表单就够，不依赖任何脚本。
 */

/** localStorage 键名（首页脚本读它 → 手动选择优先于自动定位；两端必须一致） */
function kcj_astro_place_store_key() {
    return 'kcj_astro_place';
}

/** 观测地总览页地址。优先用站点上真有一页挂了 [astro_places_hub] 的那个；取不到退回默认路径。 */
function kcj_astro_places_hub_url() {
    static $url = null;
    if ($url !== null) {
        return $url;
    }
    $url = '';
    // 先看有没有显式配置（后台/选项），再看有没有页面正文里含本短代码。
    $opt = get_option('kcj_astro_places_hub_url', '');
    if (is_string($opt) && $opt !== '') {
        $url = $opt;
        return $url;
    }
    global $wpdb;
    $hit = $wpdb->get_var($wpdb->prepare(
        "SELECT ID FROM {$wpdb->posts}
          WHERE post_status = 'publish' AND post_type IN ('page','post')
            AND post_content LIKE %s
          ORDER BY post_type = 'page' DESC, ID ASC LIMIT 1",
        '%' . $wpdb->esc_like('[astro_places_hub') . '%'
    ));
    if ($hit) {
        $link = get_permalink((int) $hit);
        if ($link) {
            $url = (string) $link;
            return $url;
        }
    }
    // 兜底：约定路径（.htaccess 与 WP 都会把它当成不存在的页 → 404，故只是最后手段）
    $url = home_url('/observatories/');
    return $url;
}

/** 首页那个「[切换观测地]」小链接（排版在 CSS 的 .kcj-astro-place-switch） */
function kcj_astro_place_switch_link() {
    $u = kcj_astro_places_hub_url();
    if ($u === '') {
        return '';
    }
    return '<a class="kcj-astro-place-switch" href="' . esc_url($u) . '">切换观测地</a>';
}

/**
 * 渲染观测地总览页的网格。
 *
 * 数据来源与 [astro_today] **同一份**：kcj_astro_place_groups()（目录）＋
 * kcj_astro_load_places()（当天真有数据的锚点）。故本页不需要 data_json，
 * 也就不必重复渲染整块今日天象 —— 正是「瘦身」要的效果。
 *
 * ★ 只列「当天真有数据」的锚点：列了没数据的，读者选完回到首页会看到一片「—」。
 */
function kcj_astro_render_places_hub() {
    $groups = function_exists('kcj_astro_place_groups') ? kcj_astro_place_groups() : array();
    if (!$groups) {
        return kcj_astro_notice('观测地目录（assets/places-cn.json）不可读，暂时无法列出可选观测地。');
    }
    // 当天有数据的锚点集合：与 [astro_today] 同源（同一天、同一张表）
    $places = array();
    if (function_exists('kcj_astro_has_site_table') && kcj_astro_has_site_table()) {
        $places = kcj_astro_load_places(current_time('Y-m-d'));
    }
    $covered = array();
    foreach ($groups as $g) {
        foreach ($g['items'] as $k => $cn2) {
            if (isset($places[$k])) {
                $covered[$k] = true;
            }
        }
    }
    // 当前生效的观测地：默认城（服务端口径；前端读到 localStorage 后会另说）
    $dflt = kcj_astro_default_place();
    $cur  = $dflt['key'];
    $cur_cn = $dflt['cn'];
    if (isset($places[$cur])) {
        $cur_cn = $places[$cur]['cn'];
    }

    // 当前城所在省 —— 决定网格默认打开哪一省（与 astro-today.php 同一算法、同一理由）
    $cur_prov = '';
    foreach ($groups as $pad => $g) {
        if (isset($g['items'][$cur])) {
            $cur_prov = (string) $pad;
            break;
        }
    }

    return kcj_astro_render_template('astro-places', array(
        'groups'       => $groups,
        'covered'      => $covered,
        'places'       => $places,
        'cur'          => $cur,
        'cur_cn'       => $cur_cn,
        'cur_prov'     => $cur_prov,
        'flat_fallback' => (!$groups || !$covered),
        'hub_url'      => kcj_astro_places_hub_url(),
        'store_key'    => kcj_astro_place_store_key(),
        'anchor_count' => function_exists('kcj_astro_places_expected') ? kcj_astro_places_expected() : 0,
        'date_str'     => current_time('Y-m-d'),
    ));
}

add_shortcode('astro_places_hub', function ($atts) {
    $atts = shortcode_atts(array('title' => ''), $atts, 'astro_places_hub');
    $body = kcj_astro_render_places_hub();
    if ($atts['title'] !== '') {
        $body = '<h3 class="kcj-astro-hub-title">' . esc_html($atts['title']) . '</h3>' . $body;
    }
    return $body;
});

/* -------------------------------------------------------------------------
/* -------------------------------------------------------------------------
 * 短代码 1：今日天象
 * ---------------------------------------------------------------------- */

add_shortcode('astro_today', function ($atts) {
    global $wpdb;
    $atts = shortcode_atts(array('date' => '', 'place' => 'auto'), $atts, 'astro_today');
    $date = $atts['date'] ? $atts['date'] : current_time('Y-m-d');
    if (!preg_match('/^\d{4}-\d{2}-\d{2}$/', $date)) {
        return kcj_astro_notice('日期格式应为 YYYY-MM-DD', 'kcj-astro-error');
    }
    $place = sanitize_key((string) $atts['place']);
    if ($place === '') {
        $place = 'auto';
    }
    // 观测地口径（三种）：
    //   off   = 不查观测地表，只出地心量（页面上没有切换器）
    //   城市键 = 固定在那一城（页面上没有切换器，但标明观测地）
    //   auto  = 默认城起步（**保证无 JS、无网络时也完整可读**），
    //           页面带出全部预置城市当日数据，由 assets/astro-place.js 按 IP 选中并允许手动切换
    $sites_table_exists = kcj_astro_has_site_table();

    // ★★ v2.2.6：缓存键**必须带上「数据纪元」**，而且**降级渲染不得缓存 12 小时**。
    //   本轮线上症状：导入已跑完（daily_site 29,298 行在库、events 也已写入），
    //   而前台仍显示「观测地维度数据未覆盖 2026-09-23（需导入 wp_astro_daily_site）」，
    //   页面上一个城也选不到（`<option>` 数 = 0）。
    //   成因（两条，都要堵）：
    //     ① **负缓存**：渲染发生在「表已建好但数据还没导进去」的那几十秒里，
    //        那段「空态 HTML」被 set_transient 写成 **12 小时**，数据到位后它还会一直被端上来。
    //        ⇒ 空态/降级态一律只缓存 5 分钟（不进 12 小时档）。
    //     ② **缓存穿透不了**：导入结束时调 kcj_astro_forecast_flush_cache()，
    //        而它当时只 `DELETE FROM wp_options` —— WP.com 有**持久对象缓存**，
    //        transient 的值可能在对象缓存里，删表删不掉它，表现为「清了缓存页面还是旧的」。
    //        ⇒ 改为「纪元号 +1」（缓存键随之改变，旧键自然失效，不依赖能否删掉）+ 逐键 delete_transient。
    //   纪元号是**自动加载**的单值 option，代价可忽略；它一变，所有旧键同时作废。
    $epoch     = kcj_astro_data_epoch();
    $cache_key = 'kcj_astro_today_' . $date . '_' . $place . '_'
        . ($sites_table_exists ? '1' : '0') . '_e' . $epoch;
    $html = get_transient($cache_key);
    if (false === $html) {
        $degraded = false;   // 渲染结果是否「降级」（缺当日地心量或缺观测地表）
        $tbl = KCJ_Astro_DB::table('daily');
        $row = $wpdb->get_row(
            $wpdb->prepare("SELECT data_json, data_version, method, special_event_ids FROM {$tbl} WHERE date_str = %s LIMIT 1", $date),
            ARRAY_A
        );
        if (!$row) {
            $degraded = true;
            $html = kcj_astro_notice('暂无 ' . $date . ' 的预计算天象数据（构建流水线每日刷新）。');
        } else {
            $data = json_decode($row['data_json'], true);
            if (!is_array($data)) {
                $data = array();
            }
            $data['_data_version'] = $row['data_version'];
            // special_event 优先取显式列（指令 02 的 special_event_ids），无则用 data_json 内的
            if (empty($data['special_event']) && !empty($row['special_event_ids'])) {
                $data['special_event'] = kcj_astro_load_special_events($row['special_event_ids']);
            }
            // —— 观测地维度覆盖 ——
            $places = array();
            if ($sites_table_exists && $place !== 'off') {
                $places = kcj_astro_load_places($date);
                if (!$places) {
                    $degraded = true;   // 该日无观测地数据 ⇒ 页面会显示「未覆盖」，这类结果不许缓存 12 小时
                }
            }
            $data['places']       = $places;
            $data['place_mode']   = ($place === 'off') ? 'off' : (($place === 'auto') ? 'auto' : 'fixed');
            $data['place_fixed']  = ($place === 'off' || $place === 'auto') ? '' : $place;
            // 默认观测地由 PHP 侧单一常量给出（不写死在模板里，免得两处各改一半）
            $dflt                 = kcj_astro_default_place();
            $data['place_default'] = $dflt['key'];
            $data['date_str']     = $date;
            $html = kcj_astro_render_template('astro-today', $data);
        }
        set_transient($cache_key, $html, $degraded ? (5 * MINUTE_IN_SECONDS) : (12 * HOUR_IN_SECONDS));
    }
    return $html;
});

/** 观测地维度表是否已建（没建时页面要能如实降级，而不是白屏或报错） */
function kcj_astro_has_site_table() {
    static $yes = null;
    if ($yes !== null) {
        return $yes;
    }
    global $wpdb;
    $tbl = KCJ_Astro_DB::table('daily_site');
    $yes = ($tbl && $wpdb->get_var($wpdb->prepare('SHOW TABLES LIKE %s', $tbl)) === $tbl);
    return $yes;
}

/**
 * 取某日**全部预置观测地**的升落与晨昏。
 * 返回 array( city_key => array(cn, lat, lon, elev, sunrise, sunset, daylen,
 *                                 tw_c, tw_c_end, tw_n, tw_n_end, tw_a, tw_a_end,
 *                                 moonrise, moonset, tz) )
 * 一次查询取全（38 行 × 十余列），比按需查询更省往返，且前端切换时零请求。
 */
function kcj_astro_load_places($date) {
    global $wpdb;
    $tbl  = KCJ_Astro_DB::table('daily_site');
    $rows = $wpdb->get_results(
        $wpdb->prepare(
            "SELECT city, city_cn, lat, lon, elev_m, tz, sunrise_bj, sunset_bj, day_length_min,
                    tw_civil_begin, tw_civil_end, tw_nautical_begin, tw_nautical_end,
                    tw_astro_begin, tw_astro_end, moonrise_bj, moonset_bj
             FROM {$tbl} WHERE date_str = %s ORDER BY city ASC",
            $date
        ),
        ARRAY_A
    );
    // ★ 该日为空的两种情况必须区分：表里没有这一天（数据未覆盖）≠ 该地没有升落。
    //   前端据此显示「未覆盖」而不是把空值当「无日出」。
    if (!$rows) {
        kcj_astro_audit_places($date, 0);
        return array();
    }
    kcj_astro_audit_places($date, count($rows));
    $out = array();
    foreach ($rows as $r) {
        $out[(string) $r['city']] = array(
            'cn'      => (string) $r['city_cn'],
            'lat'     => (float) $r['lat'],
            'lon'     => (float) $r['lon'],
            'elev'    => (float) $r['elev_m'],
            'tz'      => (string) $r['tz'],
            'sunrise' => $r['sunrise_bj'],
            'sunset'  => $r['sunset_bj'],
            'daylen'  => ($r['day_length_min'] === null ? null : (int) $r['day_length_min']),
            'tw_c'    => array($r['tw_civil_begin'], $r['tw_civil_end']),
            'tw_n'    => array($r['tw_nautical_begin'], $r['tw_nautical_end']),
            'tw_a'    => array($r['tw_astro_begin'], $r['tw_astro_end']),
            'moonrise' => $r['moonrise_bj'],
            'moonset'  => $r['moonset_bj'],
        );
    }
    return $out;
}

/**
 * 观测地覆盖审计 —— **按时间追加、保留近 N 次**（写 option，供 /health 与后台自检读数；
 * 不写日志、不影响渲染）。
 *
 * ★ v2.3.0 改（用户报「/tianxiang-yugao/ 曾瞬时降级：审计只留最后一次观测值，取不到历史」）
 *   改前是 `$last[$date] = array(rows, at)` —— **以日期为键覆盖**。于是：
 *     · 同一日期只有**最后一次**观测值：先查到 340 行、后被一次降级渲染查到 0 行，
 *       340 那条就被 0 **原地覆盖**，站外只能看见「现在 0 行」，**看不出它曾经是好的**；
 *     · 保留窗口是「最近 20 个**日期**」而不是「最近 20 次**观测**」—— 同一日期反复观测
 *       挤不出多一条，而 20 个日期一旦攒满，旧的就静默丢失。
 *   ⇒ 两种观测形态（**瞬时降级**＝一次 0 夹在两次正常之间；**持续为零**＝连续多次 0）
 *     在原格式下长得一模一样，无法区分 —— 而这两种要采取的动作完全不同
 *     （前者是缓存/竞态，后者是数据没进库）。
 *   改后：**只追加、不覆盖**，每条记 (at, date, rows, expect)。
 *     · `expect` ＝ 目录声明的锚点总数（现 340）⇒ 站外可判「340/340 齐」还是「38/340 缺」，
 *       不必知道当时应该有多少个。
 *     · 同一「分钟 + 日期 + 行数」的重复观测**合并为一条**（只刷新时间）——
 *       否则页面被反复打开会在一分钟内灌进几十条同义记录，把历史挤掉。
 *     · 保留**最近 50 条观测**（不是 50 个日期）。
 *
 * ⚠ 本函数在**每次真正查询**时被调用（含降级态）。它不得抛错、不得阻断渲染。
 */
function kcj_astro_audit_places($date, $n) {
    $log = get_option('kcj_astro_places_seen', array());
    if (!is_array($log)) {
        $log = array();
    }

    // ── 旧格式迁移（{date => {rows, at}} → [{at, date, rows, expect}]）──────────
    //   迁移而非丢弃：旧条目是唯一的历史证据，丢掉就等于把用户报的那次降级抹掉。
    if ($log && !isset($log[0])) {
        $mig = array();
        foreach ($log as $d => $v) {
            if (!is_array($v)) {
                continue;
            }
            $mig[] = array(
                'at'     => isset($v['at']) ? (string) $v['at'] : '',
                'date'   => (string) $d,
                'rows'   => isset($v['rows']) ? (int) $v['rows'] : 0,
                'expect' => 0,          // 旧格式没有这个量，如实记 0（＝未知），不猜
            );
        }
        usort($mig, function ($a, $b) { return strcmp($a['at'], $b['at']); });
        $log = $mig;
    }

    $now = current_time('mysql');
    $row = array(
        'at'     => $now,
        'date'   => (string) $date,
        'rows'   => (int) $n,
        'expect' => kcj_astro_places_expected(),
    );

    // 与上一条同分钟、同日期、同行数 ⇒ 合并（只刷新时间戳），不追加
    $last_i = count($log) - 1;
    if ($last_i >= 0 && is_array($log[$last_i])) {
        $prev = $log[$last_i];
        if ((string) (isset($prev['date']) ? $prev['date'] : '') === $row['date']
            && (int) (isset($prev['rows']) ? $prev['rows'] : -1) === $row['rows']
            && substr((string) (isset($prev['at']) ? $prev['at'] : ''), 0, 16) === substr($now, 0, 16)
        ) {
            $log[$last_i]['at']     = $now;
            $log[$last_i]['expect'] = $row['expect'];
            update_option('kcj_astro_places_seen', $log, false);
            return;
        }
    }

    $log[] = $row;
    if (count($log) > 50) {
        $log = array_slice($log, -50);
    }
    update_option('kcj_astro_places_seen', $log, false);
}

/** special_event_ids（逗号分隔的事件 ID 串）→ 事件摘要数组 */
function kcj_astro_load_special_events($ids) {
    global $wpdb;
    $want = array();
    foreach (explode(',', (string) $ids) as $id) {
        $id = (int) trim($id);
        if ($id > 0) {
            $want[] = $id;
        }
    }
    if (!$want) {
        return null;
    }
    $tbl  = KCJ_Astro_DB::table('events');
    $ph   = implode(',', array_fill(0, count($want), '%d'));
    $rows = $wpdb->get_results(
        $wpdb->prepare("SELECT event_id, title, event_time_bj, slug, post_id FROM {$tbl} WHERE event_id IN ($ph)", $want),
        ARRAY_A
    );
    $out = array();
    foreach ((array) $rows as $r) {
        $out[] = array(
            'event_id' => (int) $r['event_id'],
            'title'    => $r['title'],
            'time_bj'  => $r['event_time_bj'],
            'url'      => kcj_astro_event_permalink($r),
        );
    }
    return $out ? $out : null;
}

/* -------------------------------------------------------------------------
 * 短代码 2：天象预告列表
 * ---------------------------------------------------------------------- */

add_shortcode('astro_forecast_list', function ($atts) {
    global $wpdb;
    $atts   = shortcode_atts(array('type' => '', 'limit' => '200', 'side' => 'future'),
                             $atts, 'astro_forecast_list');
    $all    = kcj_astro_event_types();          // 6 个规范值（= Tab 的顺序）
    $groups = kcj_astro_resolve_type($atts['type']);

    if ($groups === null) {
        return kcj_astro_notice(
            '未知类型：' . $atts['type'] . '（可用：solar / lunar / solar_eclipse / lunar_eclipse / '
            . 'eclipse / planet / meteor / traditional / historical）',
            'kcj-astro-error'
        );
    }
    $side = strtolower(trim((string) $atts['side']));
    if (!in_array($side, array('future', 'past', 'all'), true)) {
        return kcj_astro_notice('side 取值应为 future / past / all（收到：'
            . esc_html($atts['side']) . '）', 'kcj-astro-error');
    }
    $limit = max(1, min(500, (int) $atts['limit']));
    $tbl   = KCJ_Astro_DB::table('events');
    $cols  = 'event_id, event_type, title, event_time_bj, summary, slug, post_id, method';

    // ★ side 过滤（v2.0.0）：历史回推的日月食与「未来预告」**同属一个 event_type**，
    //   不加这层过滤，1900 年的月食会混进「未来天象预告」。以 event_time_bj 与今天比较
    //   （DATETIME 串比较，与站点时区同为北京时，无需换算 JD）。
    //   例外：event_type='historical' 是「史料型」条目，其 event_time_bj 常为 NULL
    //   （古代事件的时刻本就不可考），故该类型不受 side 约束。
    $today = current_time('Y-m-d') . ' 00:00:00';
    $data  = array();
    foreach ($groups as $t) {
        if (!isset($all[$t])) {
            continue;
        }
        $where = "event_type = %s AND publish_status = 1";
        $args  = array($t);
        if ($t !== 'historical' && $side !== 'all') {
            $where .= ($side === 'future') ? " AND event_time_bj >= %s" : " AND event_time_bj < %s";
            $args[] = $today;
        }
        // 排序：历史侧按时间倒序（由近及远）；其余按时间正序。
        $ord = (($t === 'historical') || ($side === 'past')) ? 'DESC' : 'ASC';
        $args[] = $limit;
        $data[$t] = $wpdb->get_results(
            $wpdb->prepare("SELECT {$cols} FROM {$tbl} WHERE {$where} ORDER BY jd_core {$ord} LIMIT %d", $args),
            ARRAY_A
        );
    }

    return kcj_astro_render_template('astro-forecast-list', array(
        'types'  => array_intersect_key($all, $data),   // 只渲染本次要显示的 Tab
        'groups' => $data,
        'active' => (count($data) === 1) ? key($data) : '',
        'side'   => $side,
    ));
});

/* -------------------------------------------------------------------------
 * 短代码 3：古今对照（指令 05 的第 3 个）
 * ---------------------------------------------------------------------- */

/**
 * 用法：
 *   [astro_related_events]                  在当前事件详情页自动取当前事件
 *   [astro_related_events id="12"]          指定源事件
 *   [astro_related_events id="12" mode="historical"]  只看同类型历史天象
 *   [astro_related_events id="12" mode="future"]      只看同类未来天象
 */
add_shortcode('astro_related_events', function ($atts) {
    global $wpdb;
    $atts = shortcode_atts(array('id' => '0', 'mode' => 'auto', 'limit' => '10'), $atts, 'astro_related_events');

    $eid = (int) $atts['id'];
    if ($eid <= 0 && function_exists('get_the_ID')) {
        $pid = get_the_ID();
        if ($pid) {
            $tbl = KCJ_Astro_DB::table('events');
            $eid = (int) $wpdb->get_var($wpdb->prepare("SELECT event_id FROM {$tbl} WHERE post_id = %d LIMIT 1", $pid));
        }
    }
    if ($eid <= 0) {
        return kcj_astro_notice('未能确定源事件（请传 id，或在事件详情页内使用）。', 'kcj-astro-error');
    }

    $src = kcj_astro_event_by_id($eid);
    if (!$src) {
        return kcj_astro_notice('未找到源事件（id=' . $eid . '）。');
    }

    $limit = max(1, min(50, (int) $atts['limit']));
    $rows  = kcj_astro_fetch_related($eid, $atts['mode'], $limit);

    return kcj_astro_render_template('astro-related-events', array(
        'src'    => $src,
        'items'  => $rows,
        'mode'   => $atts['mode'],
    ));
});

/** 按 event_id 取一行事件 */
function kcj_astro_event_by_id($event_id) {
    global $wpdb;
    $tbl = KCJ_Astro_DB::table('events');
    $row = $wpdb->get_row(
        $wpdb->prepare("SELECT * FROM {$tbl} WHERE event_id = %d LIMIT 1", (int) $event_id),
        ARRAY_A
    );
    return $row ?: null;
}

/**
 * 取关联事件。
 * 两条来源合并去重：
 *   ① 显式关系（wp_astro_relations，由后台元字段或导入写入）；
 *   ② 同类型兜底（关系表为空时，按 event_type 取最接近的 N 条）——
 *      否则新站没有任何关系数据时该模块永远空着，属「功能看着有、实际从不显示」。
 * mode = auto|historical|future 决定是否限制在历史/未来侧。
 */
function kcj_astro_fetch_related($event_id, $mode = 'auto', $limit = 10) {
    global $wpdb;
    $ev_tbl  = KCJ_Astro_DB::table('events');
    $rel_tbl = KCJ_Astro_DB::table('relations');
    $src     = kcj_astro_event_by_id($event_id);
    if (!$src) {
        return array();
    }

    $mode = strtolower((string) $mode);
    $out  = array();
    $seen = array((int) $event_id => true);

    // ① 显式关系
    $rows = $wpdb->get_results(
        $wpdb->prepare(
            "SELECT r.rel_type, e.event_id, e.event_type, e.title, e.slug, e.post_id, e.event_time_bj
             FROM {$rel_tbl} r JOIN {$ev_tbl} e ON e.event_id = r.to_event
             WHERE r.from_event = %d AND e.publish_status = 1 LIMIT %d",
            (int) $event_id, $limit
        ),
        ARRAY_A
    );
    foreach ((array) $rows as $r) {
        $r['source'] = 'relation';
        if (kcj_astro_mode_match($mode, $r, $src)) {
            $out[] = $r;
            $seen[(int) $r['event_id']] = true;
        }
    }

    // ② 同类型兜底（不足 limit 时补）
    if (count($out) < $limit) {
        $rows2 = $wpdb->get_results(
            $wpdb->prepare(
                "SELECT '' AS rel_type, event_id, event_type, title, slug, post_id, event_time_bj
                 FROM {$ev_tbl}
                 WHERE event_type = %s AND publish_status = 1 AND event_id <> %d
                 ORDER BY ABS(jd_core - %f) ASC LIMIT %d",
                $src['event_type'], (int) $event_id, (float) $src['jd_core'], $limit
            ),
            ARRAY_A
        );
        foreach ((array) $rows2 as $r) {
            if (isset($seen[(int) $r['event_id']])) {
                continue;
            }
            $r['source'] = 'same_type';
            if (kcj_astro_mode_match($mode, $r, $src)) {
                $out[] = $r;
                $seen[(int) $r['event_id']] = true;
            }
            if (count($out) >= $limit) {
                break;
            }
        }
    }
    return array_slice($out, 0, $limit);
}

/** mode 过滤：historical 只看历史侧，future 只看非历史侧，auto 全要 */
function kcj_astro_mode_match($mode, $row, $src) {
    if ($mode === 'historical') {
        return $row['event_type'] === 'historical';
    }
    if ($mode === 'future') {
        return $row['event_type'] !== 'historical';
    }
    return true;
}

/* -------------------------------------------------------------------------
 * 短代码 4：历史上今日天象（v2.0.0）
 * ---------------------------------------------------------------------- */

/**
 * 历史条目 → **分组键**：把标题末尾的**日期形括号**剥掉。
 *
 * 用途：`astro-history-today.php` 里「同一天里同名条目过多 ⇒ 折成年份清单」。
 *
 * ★ 为什么只剥「**日期形**」括号，而不是一刀切地剥「（…）」：
 *   行星条目里有「土星留（转逆行）」这类括号，那是**语义**不是日期 ——
 *   一刀切会把「留·转逆行」与「留·转顺行」并成一组（两种**相反**的天象混在一起，
 *   页面会显示成「某行星留 · 共 N 次」而看不出方向）。
 *   ⇒ 判据必须精确到「括号里是 ISO 日期 YYYY-MM-DD」。
 */
function kcj_astro_history_group_key($title) {
    $t = (string) $title;
    $k = preg_replace('/\s*（\d{4}-\d{2}-\d{2}）\s*$/u', '', $t);
    return (is_string($k) && $k !== '') ? $k : $t;
}

/**
 * 「前后几天」跳转项。让「这一天确实没有」时读者能走到邻日 ——
 * 否则一年里有大半日子打开是空的，而读者**没有任何办法**换一天看。
 *
 * ★ 天数加减用**闰年（2028）**做基准：若用非闰年，从 02-28 加一天会跳到 03-01，
 *   于是 **02-29 永远不在可达集合里**（自己写不出来、也没法跳过去）。
 */
function kcj_astro_history_nav($mon, $day, $offsets = null, $extra = null) {
    $offsets = is_array($offsets)
        ? $offsets
        : array(-7 => '前 7 天', -1 => '前一天', 1 => '后一天', 7 => '后 7 天');
    $out = array();
    foreach ($offsets as $off => $label) {
        $ts = mktime(0, 0, 0, (int) $mon, (int) $day + (int) $off, 2028);
        if (!$ts) { continue; }
        $md = date('m-d', $ts);
        // ★ v2.2.7（F52）：跳转链接要**自带「回去时该开哪一栏」**（$extra，由调用方给）。
        //   否则整页重载后 [astro_hub] 无从判断读者刚才在哪一栏，只能把他丢回第 0 栏 ——
        //   也就是用户报的「点前一天/后一天都跳回今日天象」。
        //   ⚠ $extra 在**独立使用**本短代码时（不在 [astro_hub] 里）是惰性参数：
        //     没有 hub 读它，URL 上多一个参数而已，无副作用。
        $q = array('kcj_md' => $md);
        if (is_array($extra)) {
            foreach ($extra as $k => $v) {
                $q[$k] = $v;
            }
        }
        $out[] = array('md' => $md, 'label' => $label,
                       'url' => add_query_arg($q));
    }
    return $out;
}

/**
 * 用法：
 *   [astro_history_today]                              今天这个月日，历史上发生过的日月食/流星雨/行星天象
 *   [astro_history_today date="09-23"]                 指定月日
 *   [astro_history_today types="lunar_eclipse"]        只看月食
 *   [astro_history_today before="1950"]                只看 1950 年以前
 *   …?kcj_md=08-12                                     URL 参数覆盖月日（页面上的「前后几天」链接即用它）
 *
 * ★ 数据面口径（必须如实标注在页面上，已由模板承担）：
 *   本模块可**自算**的族：
 *     · 月食（几何求根，1900 起，星历 de421 覆盖内）
 *     · 流星雨极大（太阳 J2000 黄经达该群约定 λ☉ 之时；λ☉ 照录 IMO／RASC）
 *     · 行星天象（合日/冲日、大距；黄经求根）
 *   日食依赖 **NASA GSFC 日食目录**照录，本机 skyfield 无日食函数、项目亦不自算日食，
 *   故日食条目只能随目录逐年补录（现目录覆盖 2026—2030）。
 *   ⇒ 页面对「日食在本回溯段内暂无条目」与「本回溯段确实没有日食」**必须区分**，
 *     否则就是把「没查」说成「没有」（本项目反复踩的静默失败）。
 *   ⇒ 故 `types` 默认**包含日食**：日食在历史段内 coverage=0 ⇒ 页面会如实说
 *     「一条都没收录 ⇒ 属未录入，不能据此说这一天没有」。**不能因为「反正没数据」
 *     就把它从默认列表里删掉**，那样这一句如实说明也就跟着消失了。
 *
 * ★ 为什么默认收四族（2026-09-23 实测依据）：只收月食时，288 条摊到 366 个月-日，
 *   只有 133 天有内容（36.3%）；补上流星雨（覆盖 38 天）与行星天象（覆盖率最高的自算族）
 *   之后，绝大多数日子打开都有内容。
 */
add_shortcode('astro_history_today', function ($atts) {
    global $wpdb;
    $atts = shortcode_atts(array(
        'date'   => '',          // MM-DD；留空取 URL 参数，再留空取站点当天
        'types'  => 'lunar_eclipse,solar_eclipse,meteor,planet',
        'before' => '',          // 只看某年之前（含该年用 before_year 不行，语义为「早于」）
        'from'   => '1900',      // 回溯下限（可自算诸族的起点）
        'limit'  => '80',
        'report' => 'on',        // 是否给下载按钮
        'nav'    => 'on',        // 是否给「前后几天」跳转
    ), $atts, 'astro_history_today');

    $mmdd = trim((string) $atts['date']);
    // URL 参数覆盖（`?kcj_md=08-12`）—— 让「这一天确实没有」时读者能走到邻日，
    // 否则一年里有大半日子打开是空的，而读者**没有任何办法**换一天看。
    if ($mmdd === '' && isset($_GET['kcj_md'])) {
        $mmdd = sanitize_text_field(wp_unslash($_GET['kcj_md']));
    }
    if ($mmdd === '') {
        $mmdd = current_time('m-d');
    }
    if (!preg_match('/^(\d{2})-(\d{2})$/', $mmdd, $m)) {
        return kcj_astro_notice('date 应为 MM-DD 格式（收到：' . esc_html($mmdd) . '）', 'kcj-astro-error');
    }
    $mon = (int) $m[1];
    $day = (int) $m[2];
    if ($mon < 1 || $mon > 12 || $day < 1 || $day > 31) {
        return kcj_astro_notice('date 不是有效月日：' . esc_html($mmdd), 'kcj-astro-error');
    }

    $all_types = kcj_astro_event_types();
    $want      = array();
    foreach (explode(',', (string) $atts['types']) as $t) {
        $t = sanitize_key(trim($t));
        if ($t !== '' && isset($all_types[$t])) {
            $want[] = $t;
        }
    }
    if (!$want) {
        return kcj_astro_notice('types 未给出任何有效天象类型（可用：'
            . esc_html(implode(' / ', array_keys($all_types))) . '）', 'kcj-astro-error');
    }

    $from   = (int) $atts['from'];
    $before = ($atts['before'] === '' ? null : (int) $atts['before']);
    $this_y = (int) current_time('Y');
    $upper  = ($before === null) ? $this_y : min($before, $this_y);   // 永远不含今年（今年不是历史）
    $limit  = max(1, min(300, (int) $atts['limit']));

    $tbl = KCJ_Astro_DB::table('events');
    $ph  = implode(',', array_fill(0, count($want), '%s'));
    // ★ v2.2.0：本栏**不按 publish_status 过滤**，这是有意的。
    //   历史天象是**数据集**，不是「已发布文章」：1900—2025 那 4,672 条在库里是
    //   publish_status = 0（且不生成详情页）。而本栏是**页面内联渲染**
    //   （astro-history-today.php 全程不外链），不需要文章实体。
    //   反过来，其它消费方（归档页、结构化数据、站点地图、未来预告）**照旧只要
    //   publish_status = 1** —— 于是历史数据既展示得出来，又不会污染归档与索引。
    //   改动此处务必同步 make_datasets.py 的 publish_status 裁定。
    $sql = "SELECT event_id, event_type, title, event_time_bj, summary, slug, post_id,
                   method, time_uncertainty, literature, discussion, source_ref
            FROM {$tbl}
            WHERE event_type IN ($ph)
              AND event_time_bj IS NOT NULL
              AND MONTH(event_time_bj) = %d AND DAY(event_time_bj) = %d
              AND YEAR(event_time_bj) >= %d AND YEAR(event_time_bj) < %d
            ORDER BY jd_core DESC LIMIT %d";
    $args = array_merge($want, array($mon, $day, $from, $upper, $limit));
    $rows = $wpdb->get_results($wpdb->prepare($sql, $args), ARRAY_A);

    // 「本回溯段内根本没录这类条目」与「这一天确实没有」是两件事，必须分别报。
    // 判据：该类在整个回溯段内的条目总数（与月日无关）。
    $coverage = array();
    foreach ($want as $t) {
        $coverage[$t] = (int) $wpdb->get_var($wpdb->prepare(
            "SELECT COUNT(*) FROM {$tbl}
             WHERE event_type = %s AND event_time_bj IS NOT NULL
               AND YEAR(event_time_bj) >= %d AND YEAR(event_time_bj) < %d",
            $t, $from, $upper
        ));
    }

    // 「前后几天」跳转。★ 抽成函数（`kcj_astro_history_nav`）是为了**可单测**：
    //   闰年基准那条规则若留在闭包里，桩测试就碰不到它（本项目反复吃这个亏）。
    // ★ v2.2.7（F52）：第四个参数把「本栏 = past」写进链接 —— 见 [astro_hub] 的说明。
    $nav = (strtolower((string) $atts['nav']) === 'off')
        ? array()
        : kcj_astro_history_nav($mon, $day, null, array('kcj_tab' => 'past'));

    return kcj_astro_render_template('astro-history-today', array(
        'mmdd'     => sprintf('%02d-%02d', $mon, $day),
        'mon'      => $mon,
        'day'      => $day,
        'types'    => $want,
        'type_cn'  => array_intersect_key($all_types, array_flip($want)),
        'rows'     => $rows,
        'coverage' => $coverage,
        'from'     => $from,
        'before'   => $upper,
        'nav'      => $nav,
        'report'   => (strtolower((string) $atts['report']) !== 'off'),
    ));
});

/* -------------------------------------------------------------------------
 * 短代码 5：月 / 季 / 年度天象报告（v2.0.0）
 * ---------------------------------------------------------------------- */

/**
 * 用法：
 *   [astro_forecast_report]                    当期（本月）报告
 *   [astro_forecast_report period="quarter"]   本季
 *   [astro_forecast_report period="year"]      本年
 *   [astro_forecast_report period="next12"]    未来 12 个月
 *
 * 报告的两个出口（都**不需要**任何后端写权限／凭据）：
 *   ① 页面表格 —— 分类别列全期间的已发布天象；
 *   ② 页面内**即时生成并下载** Markdown，或直接打印成 PDF
 *      （期间条目由 PHP 序列化进页面，前端只拼文本，不做天文计算）。
 */
add_shortcode('astro_forecast_report', function ($atts) {
    global $wpdb;
    $atts = shortcode_atts(array(
        'period'  => 'month',
        'limit'   => '300',
        'title'   => '',
        'download' => 'on',
    ), $atts, 'astro_forecast_report');

    // ★ v2.2.0（F51）：URL 参数覆盖短代码属性 —— `?kcj_period=quarter`。
    //   为什么必须有：报告模板此前**没有任何期间切换 UI**，整栏锁死在短代码写死的
    //   那一个期间上；而需求是「月 / 季 / 年度汇总，可下载」⇒ 实际只达 1/3。
    //   成法与历史栏的 `?kcj_md=` 完全一致：**纯链接、零脚本**
    //   （平台会对正文跑 wpautop 并替换裸与号，内联脚本随时被拆断 —— 见 astro-hub.php 的说明）。
    //   值非法时的语义刻意分两路：**短代码写错**（作者可见）⇒ 报错；**URL 参数非法**
    //   （读者可能手改地址栏）⇒ 静默忽略、保持原期间。让读者看见「参数错误」是没有意义的。
    $period = strtolower(trim((string) $atts['period']));
    if (!in_array($period, array('month', 'quarter', 'year', 'next12'), true)) {
        return kcj_astro_notice('period 取值应为 month / quarter / year / next12（收到：'
            . esc_html($period) . '）', 'kcj-astro-error');
    }
    if (isset($_GET['kcj_period'])) {
        $p_url = strtolower(trim(sanitize_text_field(wp_unslash($_GET['kcj_period']))));
        if (in_array($p_url, array('month', 'quarter', 'year', 'next12'), true)) {
            $period = $p_url;
        }
    }
    $rng = kcj_astro_report_range($period);
    $limit = max(1, min(1000, (int) $atts['limit']));

    $tbl  = KCJ_Astro_DB::table('events');
    $rows = $wpdb->get_results(
        $wpdb->prepare(
            "SELECT event_id, event_type, title, event_time_bj, summary, slug, post_id,
                    method, obs_site, params_json
             FROM {$tbl}
             WHERE publish_status = 1 AND event_time_bj IS NOT NULL
               AND event_time_bj >= %s AND event_time_bj < %s
             ORDER BY jd_core ASC LIMIT %d",
            $rng['start'] . ' 00:00:00', $rng['end'] . ' 00:00:00', $limit
        ),
        ARRAY_A
    );

    $type_cn = kcj_astro_event_types();
    return kcj_astro_render_template('astro-forecast-report', array(
        'period'   => $period,
        'period_cn' => kcj_astro_period_label($period, $rng),
        'range'    => $rng,
        'rows'     => $rows,
        'type_cn'  => $type_cn,
        'title'    => (string) $atts['title'],
        'download' => (strtolower((string) $atts['download']) !== 'off'),
        'site'     => home_url('/'),
        'generated' => current_time('Y-m-d H:i'),
    ));
});

/** 期间边界（含首、不含尾）。基准＝站点当天（北京时间）。 */
function kcj_astro_report_range($period) {
    $y = (int) current_time('Y');
    $m = (int) current_time('n');
    switch ($period) {
        case 'quarter':
            $qs = (int) (floor(($m - 1) / 3) * 3 + 1);
            $start = sprintf('%04d-%02d-01', $y, $qs);
            $qe = $qs + 3;
            $ey = $y; if ($qe > 12) { $qe -= 12; $ey = $y + 1; }
            $end = sprintf('%04d-%02d-01', $ey, $qe);
            break;
        case 'year':
            $start = sprintf('%04d-01-01', $y);
            $end   = sprintf('%04d-01-01', $y + 1);
            break;
        case 'next12':
            // ★ 「未来十二个月」＝从今天起**满十二个日历月**（含首不含尾）。
            //   两条错路都踩过，记在此处免得再走：
            //     ① strtotime('+12 months') —— 对「目标月没有该日」的输入（如 2/29）
            //        PHP 会**进位到下月 1 日**，与 Python 侧的日历月加法**差一天**；
            //     ② 「＋365 天」—— 闰年会少一天（2027-03-01 起会算成 2028-02-29）。
            //   故显式按日历月算，并明确定义：目标月没有该日时取**该月最后一天**。
            //   改动此段必须同批改 python/gen_astro_report.py 的 period_range()
            //   （verify_package.py 有跨语言对拍判据，两处不一致会当场报红）。
            $start = current_time('Y-m-d');
            $y2    = (int) substr($start, 0, 4) + 1;
            $m2    = (int) substr($start, 5, 2);
            $d2    = (int) substr($start, 8, 2);
            $last  = (int) date('t', mktime(0, 0, 0, $m2, 1, $y2));
            if ($d2 > $last) { $d2 = $last; }
            $end = sprintf('%04d-%02d-%02d', $y2, $m2, $d2);
            break;
        case 'month':
        default:
            $start = sprintf('%04d-%02d-01', $y, $m);
            $mn = $m + 1; $ey = $y; if ($mn > 12) { $mn = 1; $ey = $y + 1; }
            $end = sprintf('%04d-%02d-01', $ey, $mn);
            break;
    }
    return array('start' => $start, 'end' => $end);
}

/** 期间的人话标签（写进标题与下载文件名，故不用斜杠等非法字符） */
function kcj_astro_period_label($period, $rng) {
    $s = $rng['start'];
    switch ($period) {
        case 'quarter':
            return substr($s, 0, 4) . ' 年第 ' . (int) ceil(((int) substr($s, 5, 2)) / 3) . ' 季度';
        case 'year':
            return substr($s, 0, 4) . ' 年度';
        case 'next12':
            return '未来十二个月（' . $rng['start'] . ' 起）';
        case 'month':
        default:
            return substr($s, 0, 4) . ' 年 ' . (int) substr($s, 5, 2) . ' 月';
    }
}

/* -------------------------------------------------------------------------
 * 兼容：旧短代码 [astro_event_detail id="N"]
 * ---------------------------------------------------------------------- */

add_shortcode('astro_event_detail', function ($atts) {
    $atts = shortcode_atts(array('id' => '0'), $atts, 'astro_event_detail');
    $id   = (int) $atts['id'];
    if ($id <= 0) {
        return kcj_astro_notice('请提供有效的事件 id', 'kcj-astro-error');
    }
    $out = kcj_astro_render_event_detail($id);
    return $out;
});

/* -------------------------------------------------------------------------
 * 栏目激活态：URL 参数 → 「重载后该打开哪一栏」（v2.2.7 / F52）
 *
 * 病根（用户线上报：未来栏点「本月／本季／本年」、历史栏点「前一天／前七天／
 * 后一天／后七天」，点完都跳回「今日天象」）：
 *   三栏切换是**纯 CSS radio**，而模板把**第 0 个** radio 写死成 checked。
 *   栏内每个跳转链接都是普通 <a href>（换期间 / 换日子）⇒ 一定整页重载；
 *   重载后浏览器的 radio 状态不保留，于是永远复位的第 0 栏 —— 看起来「点了没反应」。
 *   ⚠ 它**其实生效了**：新期间/新日子的数据已经在页面里，只是躺在第 2、3 栏里
 *     而页面停在第 1 栏。这种「数据是对的、界面在骗人」比真失败更难察觉。
 *
 * 成法：**纯服务端**按 URL 参数算出激活栏，模板据此决定 checked 落在谁身上。
 *   不靠脚本 —— 平台对正文的后处理会拆断内联脚本（v1.3.0 起的老账），
 *   且这样连 JS 被禁、被拦截也照样正确。
 *   （★ 反面记录：一度考虑「用脚本拦掉跳转、不重载」。**那是错的** ——
 *     本页各期间/各日子的数据是**服务端按参数渲染**的，不重载就换不了内容，
 *     拦住跳转只会让地址栏与页面内容不一致，把「看起来没生效」升级成「真的没生效」。）
 *
 * 判定优先级（高 → 低）：
 *   ① `?kcj_tab=`     显式指定 —— 各栏自己的跳转链接都会带上它，故**新链接永不歧义**
 *   ② `?kcj_period=`  未来栏自己的参数 → future
 *   ③ `?kcj_md=`      历史栏自己的参数 → past
 *   ④ 都没有          → 第一栏（today）
 *   ⚠ ② ③ 只作**旧链接兜底**。为什么不靠它们定案：期间链接会**保留** kcj_md
 *     （见 astro-forecast-report.php 的 $kcj_keep），而历史栏的跳转用 add_query_arg
 *     又**保留** kcj_period —— 两侧互相保留，于是 `?kcj_period=quarter&kcj_md=09-24`
 *     这种「两个都在」的 URL 是常态，而**从 URL 上看不出先后**。
 *     所以链接端必须自带 kcj_tab；② ③ 的次序只是「二选一」的兜底，不作正解。
 *
 * ⚠ 本函数只认**参数在不在**，不校验取值合法性 ——
 *   取值合法性各栏自己判（[astro_forecast_report] 不认的期间会静默回落默认值）。
 *   此处再校验一遍就成了第二份口径，迟早与那边漂移。
 * ⚠ 返回的是**该栏的 key**，定位成下标由调用方做：本函数不知道 $sections 的顺序，
 *   也不该知道（key 才是稳定标识；三栏的开关顺序将来可能变）。
 */
function kcj_astro_hub_active_key($sections) {
    $keys = array();
    foreach ($sections as $s) {
        if (isset($s['key'])) {
            $keys[] = (string) $s['key'];
        }
    }
    if (!$keys) {
        return '';
    }
    if (isset($_GET['kcj_tab'])) {
        $t = strtolower(trim(sanitize_text_field(wp_unslash($_GET['kcj_tab']))));
        // 值非法 ⇒ 不当成「未知栏」（那会开出空白页），落到下面的兜底
        if (in_array($t, $keys, true)) {
            return $t;
        }
    }
    // ★ 每个候选都要先确认**该栏此刻真的在页面上**：作者可以用 future="0" 关掉某栏，
    //   此时 URL 里还带着 kcj_period 也不能返回 future（返回了就等于认了一个不存在的栏）。
    if (isset($_GET['kcj_period']) && in_array('future', $keys, true)) {
        return 'future';
    }
    if (isset($_GET['kcj_md']) && in_array('past', $keys, true)) {
        return 'past';
    }
    return $keys[0];
}

/* -------------------------------------------------------------------------
 * 短代码 7：天象预告「三栏目」外壳（v2.0.0）
 *
 * 为什么是栏目而不是菜单（用户原话）：
 *   「3个子项以三个栏目的样式体现，不能做成菜单」
 * ⇒ 三个子项在**同一页面内**以三个栏目（页内切换）呈现，**不产生任何导航菜单项**。
 *
 * 实现上刻意避开的三个坑（都是被平台环境逼出来的）：
 *   ① **纯 CSS 切换**（radio + label），**零脚本**。
 *      平台会对正文跑 wpautop（空行换块级标签）、并替换某些窗口内的裸与号，
 *      内联脚本随时可能被拆断（v1.3.0「老黄历线上失效」的真因）；
 *      外置资源又要求本页有入队点。不用脚本，这两个问题一起消失。
 *   ② 三个栏目的内容**全部在 DOM 里**（仅以 CSS 隐藏），
 *      故搜索引擎抓得到每一个分区；`tabs="0"` 则纵向平铺。
 *   ③ **打印时强制三栏全展开**（见 CSS 的 @media print）——
 *      否则「打印出来的报告少了两栏」这种错很难被发现。
 */
add_shortcode('astro_hub', function ($atts) {
    $atts = shortcode_atts(array(
        'tabs'   => '1',        // 1=页内切换；0=三栏目纵向平铺
        'today'  => '1',        // 是否含「今日天象」栏目
        'place'  => 'auto',     // 透传给 [astro_today]
        'future' => '1',        // 是否含「未来天象预告」栏目
        // ★ v2.2.0（F51）：默认由 month 改为 **next12（未来十二个月）**。
        //   原因：本栏是「未来天象预告」，读者来这一栏想看的是**接下来有什么**；
        //   默认「本月」会在月末（或当月条目已过）时呈现一栏空表 —— 线上实测正是如此
        //   （2026-09 条目数为 0，整栏只剩一句「暂无条目」）。改期可由 `?kcj_period=` 切换。
        'period' => 'next12',   // 透传给 [astro_forecast_report]；可被 ?kcj_period= 覆盖
        'past'   => '1',        // 是否含「历史上今日天象」栏目
    ), $atts, 'astro_hub');

    $sections = array();
    if ($atts['today'] === '1') {
        $sections[] = array(
            'key'   => 'today',
            'title' => '今日天象',
            'sub'   => '观测地可选 · 默认按访问地就近',
            'html'  => do_shortcode('[astro_today place="' . esc_attr($atts['place']) . '"]'),
        );
    }
    if ($atts['future'] === '1') {
        $sections[] = array(
            'key'   => 'future',
            'title' => '未来天象预告',
            'sub'   => '月 / 季 / 年度汇总，可下载',
            'html'  => do_shortcode('[astro_forecast_report period="' . esc_attr($atts['period']) . '"]'),
        );
    }
    if ($atts['past'] === '1') {
        $sections[] = array(
            'key'   => 'past',
            'title' => '历史上今日天象',
            'sub'   => '史载天象 · 逐年照录，可下载',
            'html'  => do_shortcode('[astro_history_today]'),
        );
    }
    if (!$sections) {
        return kcj_astro_notice('天象预告栏目已全部关闭（today / future / past 均为 0）。',
            'kcj-astro-error');
    }
    // ★ v2.2.7（F52）：把「重载后该打开哪一栏」算出来传给模板。
    //   不传的话模板只能把第 0 栏写死成打开态 ⇒ 读者在栏内点任何跳转链接，
    //   重载回来都停在「今日天象」，看起来「点了没反应」（用户线上报的就是这个）。
    //   key → 下标：key 是稳定标识，下标随 sections 的开关顺序变，故在此换算。
    $active_key = kcj_astro_hub_active_key($sections);
    $active_i   = 0;
    foreach ($sections as $i => $s) {
        if ($s['key'] === $active_key) {
            $active_i = (int) $i;
            break;
        }
    }
    // uniq 只用于生成页面内唯一的 id/name —— 同一页放两个 [astro_hub] 时，
    // radio 的 name 若相同，两组栏目会互相串扰（选了一个、另一个被取消）。
    return kcj_astro_render_template('astro-hub', array(
        'sections' => $sections,
        'tabs'     => ($atts['tabs'] === '1'),
        'active_i' => $active_i,
        'uniq'     => substr(md5(uniqid('kcjhub', true)), 0, 8),
    ));
});

/** 详情渲染块（供旧短代码与 single-astro_event.php 共用，避免两套排版漂移） */
function kcj_astro_render_event_detail($event_id) {
    global $wpdb;
    $ev = kcj_astro_event_by_id($event_id);
    if (!$ev) {
        return kcj_astro_notice('未找到该天象事件（id=' . (int) $event_id . '）。');
    }
    $params = !empty($ev['params_json']) ? json_decode($ev['params_json'], true) : array();
    $related = kcj_astro_fetch_related($event_id, 'auto', 10);
    return kcj_astro_render_template('astro-event-detail', array(
        'ev'      => $ev,
        'related' => $related,
        'params'  => is_array($params) ? $params : array(),
    ));
}
