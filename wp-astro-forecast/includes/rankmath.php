<?php
/**
 * SEO 层：Rank Math 适配与结构化数据（指令 07）
 *
 * ── 三条事实纠偏（依据见 docs/rank-math-config.md §0）──────────────────
 *   ① 指令 07 要求「今日天象页面：启用 Calendar + AstronomicalObject Schema」——
 *      **两个类型在 Schema.org 都不存在**。已下载 schema.org 官方词表
 *      release 29.0（schemaorg-current-https.ttl，1,063,736 字节）逐字核对：
 *      AstronomicalObject 出现 0 次、Calendar 出现 0 次（Planet / Star / Constellation 同样为 0）。
 *      故改用实有类型：`WebPage` + 子节点 `Dataset`。
 *   ② 指令 07 要求历史天象用 `ScholarlyArticle`——该类型**存在**
 *      （rdfs:subClassOf schema:Article），但**Rank Math 免费版的类型清单里没有它**，
 *      而「Custom Schema（任意类型）」是 PRO 功能。故这一类**由本插件直接输出 JSON-LD**。
 *   ③ 「Custom Schema 任意类型」仅 PRO；免费版只能从固定清单里选。
 *      ⇒ 本插件采取「分工」：Rank Math 能做的（WebPage / CollectionPage）交给它，
 *        Rank Math 做不到的（Dataset / ScholarlyArticle）由本插件补，**避免重复输出**。
 *   ④ ★ 2026-09-23 追加：**Event 也必须归本插件**。原先把 Event 交给 Rank Math 的
 *      「CPT 级默认 Schema Type」面板配置，实测 79 条事件详情页**整页零 JSON-LD**
 *      （连 Person / WebSite / WebPage 都没有）。核对 Rank Math 免费版源码，根因是白名单：
 *        includes/helpers/class-schema.php :: get_default_schema_type( $post_id, $return_valid )
 *          L70  ⇒ $return_valid 为真时**只认** Article / NewsArticle / BlogPosting /
 *                 WooCommerceProduct / EDDProduct，其余（含 Event）一律 return false；
 *        includes/modules/schema/snippets/class-singular.php :: get_default_schema()
 *          L104 ⇒ singular 页面的默认 schema 正是走 $return_valid = true 这条路。
 *      连带效应更重：can_add_global_entities() 随之判定失败（class-jsonld.php L379/L394），
 *      于是**连站点级实体也一并被放弃**。⇒ 面板选 Event 在前台永不出图，不是配置没保存。
 *      详见 docs/rank-math-config.md §2.5、docs/feasibility-review.md F37。
 *   ⑤ ★ 2026-09-23 追加：**daily 上下文必须先确认取到日期**。原先 payload 为空也照建节点，
 *      线上因此出现「首页 / 每篇博文 / 老黄历页」各挂一个**日期为空**的 Dataset 节点。
 *      修法见 kcj_astro_schema_nodes() 的 'daily' 分支；判据见 php_selftest.py。
 *      详见 docs/feasibility-review.md F38。
 *   ⑥ ★ 2026-09-23 追加（F62）：**daily 判据原先只认字面 `[astro_today]`**，认不出
 *      `[astro_hub]` —— 而「天象预告」页正是用 `[astro_hub]`，且它的「今日天象」栏
 *      **默认开启**、三栏都渲染进 HTML ⇒ 页面上有内容，结构化数据却是 0。
 *      线上直采实测：`/tianxiang-yugao/` 有 `data-kcj-section="today"`、hub 容器 38 处，
 *      Dataset 节点 **0** 个；同一时刻首页（用 `[astro_today]`）**1** 个。
 *      修法见 kcj_astro_page_today_date()；判据见 php_selftest.py 的 hub_page 用例。
 *
 * ── 真实钩子（已下载 rankmath/seo-by-rank-math 源码核对，不是猜的）────
 *   · `rank_math/json_ld` —— 是 **filter**：`do_filter('json_ld', [], $this)`，
 *     回调签名 `( $data, $jsonld )`，**必须 return 合并后的数组**；
 *     最终被包成 `{"@context":..., "@graph":[ ... ]}` 输出在 head。
 *   · 触发点：`rank_math/head` 动作（优先级 90）→ `JsonLD::json_ld()`。
 *   · 标题/描述模板：Rank Math 免费版走**后台设置页**（Titles & Meta），
 *     源码中未见对应的前端 filter，故本插件**不擅自 hook**——
 *     逐屏配置见 docs/rank-math-config.md §2，那是指令 07 原文指定的实现路径。
 *
 * 硬性约束：JSON-LD 内不得出现占星/运势/吉凶字段；不得为不可见内容声明结构化数据。
 */

if (!defined('ABSPATH')) {
    exit;
}

/** Rank Math 是否启用（它没有稳定的「is_active」常量，故按主类/常量判） */
function kcj_astro_rankmath_active() {
    return defined('RANK_MATH_VERSION') || class_exists('RankMath\\Helper');
}

/**
 * Rank Math 是否已为**当前这篇文章**写过文章级 schema 元数据。
 *
 * 依据：Rank Math 自己按 `meta_key LIKE 'rank_math_schema_'` 认文章级 schema
 * （includes/modules/schema/class-db.php :: get_schemas()；同文件 L244 亦以此前缀删除）。
 * 用户在编辑器里打开并保存某篇后，Rank Math 会把该篇的 schema 写进这类元数据，
 * 此时前台由它输出 ⇒ 本插件的 Event 必须让位，否则同一页会出现两个 Event 节点。
 */
function kcj_astro_rankmath_has_post_schema() {
    if (!kcj_astro_rankmath_active()) {
        return false;
    }
    $post_id = get_the_ID();
    if (!$post_id) {
        return false;
    }
    foreach ((array) get_post_meta($post_id) as $key => $val) {
        if (strpos((string) $key, 'rank_math_schema_') === 0) {
            return true;
        }
    }
    return false;
}

/**
 * 本插件是否应输出该类型。
 *
 * 分工原则（避免同一页面出现两份同类型结构化数据）：
 *   · Rank Math 未启用 ⇒ 四类全由本插件输出；
 *   · Rank Math 已启用 ⇒ 本插件**只**输出 Rank Math 免费版做不到的类型：
 *       - Dataset（PRO 才有）
 *       - ScholarlyArticle（免费版清单里没有，且自定义类型是 PRO 功能）
 *       - Event（★ 文件头 ④：免费版 CPT 级默认 schema 的白名单不含 Event ⇒ 面板选了也不出）
 *     其余（WebPage / CollectionPage）交给 Rank Math 的逐屏配置。
 */
function kcj_astro_schema_should_emit($type) {
    $only_mine = array('Dataset', 'ScholarlyArticle', 'Event');
    if (in_array($type, $only_mine, true)) {
        // Event 是「本插件兜底、Rank Math 优先」：某篇若已有文章级 schema 元数据，就让位。
        if ($type === 'Event' && kcj_astro_rankmath_has_post_schema()) {
            return false;
        }
        return true;
    }
    return !kcj_astro_rankmath_active();
}

/* --------------------------- 节点构造 --------------------------- */

/** 作者节点（与站点身份一致；ORCID 已为公开页真值） */
function kcj_astro_schema_author() {
    return array(
        '@type'       => 'Person',
        'name'        => '邝楚嘉',
        'alternateName' => '嘉言一得',
        'url'         => home_url('/'),
        'sameAs'      => array('https://orcid.org/0009-0002-7650-833X'),
    );
}

/** 观测地节点（默认观测地：揭阳） */
function kcj_astro_schema_place($city, $lat, $lon) {
    return array(
        '@type' => 'Place',
        'name'  => $city,
        'geo'   => array(
            '@type'     => 'GeoCoordinates',
            'latitude'  => $lat,
            'longitude' => $lon,
        ),
    );
}

/**
 * 今日天象：WebPage（节点级） + Dataset（数据实体）。
 * 用 Dataset 而非已废弃/不存在的 Calendar —— 「每日天象数据集」正是数据集语义，
 * 还能顺带挂 temporalCoverage / creator / license，比空壳 Calendar 信息量大。
 */
function kcj_astro_schema_daily($date_str, $data) {
    $url   = get_permalink() ?: home_url('/');
    $obs   = isset($data['observer']) ? $data['observer'] : array();
    $city  = isset($obs['city']) ? $obs['city'] : '揭阳';
    $lat   = isset($obs['lat']) ? $obs['lat'] : 23.35;
    $lon   = isset($obs['lon']) ? $obs['lon'] : 116.36;
    $nodes = array();

    if (kcj_astro_schema_should_emit('WebPage')) {
        $nodes[] = array(
            '@type'      => 'WebPage',
            '@id'        => $url . '#webpage',
            'name'       => sprintf('今日天象 · %s', $date_str),
            'dateModified' => $date_str,
            'isPartOf'   => array('@type' => 'WebSite', '@id' => home_url('/') . '#website'),
            'about'      => kcj_astro_schema_place($city, $lat, $lon),
        );
    }

    if (kcj_astro_schema_should_emit('Dataset')) {
        $vars = array();
        foreach (array('sun' => '太阳位置与升落', 'moon' => '月球位置与月相', 'planets' => '五大行星视位置与星等',
                       'xiu' => '二十八宿黄道宿度') as $k => $label) {
            if (!empty($data[$k])) {
                $vars[] = array('@type' => 'PropertyValue', 'name' => $label);
            }
        }
        $nodes[] = array(
            '@type'             => 'Dataset',
            '@id'               => $url . '#dataset-' . $date_str,
            'name'              => sprintf('揭阳每日天象数据集（%s）', $date_str),
            'description'       => '含太阳与月球视位置、月相与月龄、五大行星视星等、二十八宿黄道宿度的每日预计算值。'
                                 . '计算方法与星历档在页面内逐条标注。',
            'creator'           => kcj_astro_schema_author(),
            'dateModified'      => $date_str,
            'temporalCoverage'  => $date_str,
            'spatialCoverage'   => kcj_astro_schema_place($city, $lat, $lon),
            'variableMeasured'  => $vars,
            'isAccessibleForFree' => true,
            'license'           => 'https://creativecommons.org/licenses/by/4.0/',
            'isPartOf'          => array('@type' => 'WebPage', '@id' => $url . '#webpage'),
        );
    }
    return $nodes;
}

/** 未来天象事件：Event */
function kcj_astro_schema_event($ev) {
    $url = get_permalink() ?: home_url('/');
    $node = array(
        '@type'               => 'Event',
        '@id'                 => $url . '#event',
        'name'                => (string) $ev['title'],
        'description'         => wp_strip_all_tags((string) $ev['summary']),
        'eventAttendanceMode' => 'https://schema.org/OfflineEventAttendanceMode',
        'eventStatus'         => 'https://schema.org/EventScheduled',
        'isAccessibleForFree' => true,
        'organizer'           => kcj_astro_schema_author(),
    );
    // startDate 必须带时区偏移（本模块统一北京时间 UTC+8）
    if (!empty($ev['event_time_bj']) && $ev['event_time_bj'] !== '0000-00-00 00:00:00') {
        $node['startDate'] = str_replace(' ', 'T', (string) $ev['event_time_bj']) . '+08:00';
    }
    // ★ 刻意不填 location：天文事件没有「举办场地」，把默认观测地当成 venue 是失真。
    //   只有当事件行确实指定了观测地（obs_site）时才给出，且措辞为观测地而非场地。
    if (!empty($ev['obs_site'])) {
        $node['location'] = array('@type' => 'Place', 'name' => (string) $ev['obs_site']);
    }
    return array($node);
}

/** 历史天象事件：ScholarlyArticle（Rank Math 免费版无此类型 ⇒ 必由本插件输出） */
function kcj_astro_schema_scholarly($ev) {
    $url = get_permalink() ?: home_url('/');
    $node = array(
        '@type'    => 'ScholarlyArticle',
        '@id'      => $url . '#article',
        'headline' => (string) $ev['title'],
        'author'   => kcj_astro_schema_author(),
        'isAccessibleForFree' => true,
        'inLanguage' => 'zh-Hans',
        'abstract' => wp_strip_all_tags((string) $ev['summary']),
        'about'    => array('@type' => 'Thing', 'name' => '历史天象的现代回推与文献对照'),
    );
    if (!empty($ev['source_ref'])) {
        $node['citation'] = array(
            '@type' => 'CreativeWork',
            'name'  => wp_strip_all_tags((string) $ev['source_ref']),
        );
    }
    if (!empty($ev['literature'])) {
        $node['isBasedOn'] = wp_strip_all_tags((string) $ev['literature']);
    }
    // 回推结果受 ΔT 影响，按区间交付；此处把区间写进 temporalCoverage 便于机器理解
    if (!empty($ev['time_uncertainty'])) {
        $node['temporalCoverage'] = sprintf('回推区间：%s', wp_strip_all_tags((string) $ev['time_uncertainty']));
    }
    if (!empty($ev['method'])) {
        $node['measurementTechnique'] = ($ev['method'] === 'analytic_meeus')
            ? 'Meeus 解析式（截断级数近似；未使用行星历表）'
            : 'JPL 星历精算';
    }
    return array($node);
}

/** 列表 / 归档页：CollectionPage */
function kcj_astro_schema_collection($items) {
    $url = home_url('/' . KCJ_ASTRO_SLUG . '/');
    $parts = array();
    foreach ((array) $items as $it) {
        $p = array('@type' => 'Event', 'name' => (string) $it['title']);
        if (!empty($it['event_time_bj'])) {
            $p['startDate'] = str_replace(' ', 'T', (string) $it['event_time_bj']) . '+08:00';
        }
        $parts[] = $p;
    }
    return array(array(
        '@type'   => 'CollectionPage',
        '@id'     => $url . '#collection',
        'name'    => '天象预告',
        'isPartOf' => array('@type' => 'WebSite', '@id' => home_url('/') . '#website'),
        'hasPart' => $parts,
    ));
}

/**
 * 首页「Recommended Starting Reading · 入门推荐」两件学术资产。
 *
 * ★ 2026-09-25（v2.3.17）：补 `headline`（仅预印本）与 `image`（两件）。
 *   依据＝Google 富结果对这两节点报「未填写 image / headline / author」共 5 条提示；
 *   逐条核线上原文后确认：**真缺 2 条**（预印本 headline、两件 image），
 *   **误报 3 条**（预印本 author 实为 Person 且已填；Dataset 用 creator、不适用 author/headline
 *   —— 那是 Article 家族规则套到 Dataset 上）。故本次**只补真缺的两项**。
 *   仍有 3 条误报提示属校验器规则所限，**不为消提示而添加无意义字段**。
 *
 * ★ 2026-09-24（F63）新增。起因：用户核出首页最底部那两条 DOI 虽在正文里，
 *   却**只有 `<ul class="wp-block-list">` 包着**——DOM 与 JSON-LD 里都没有任何语义标记，
 *   AI 爬虫容易当「普通友链」丢弃。修法＝**两层都给**：
 *     ① 正文层：两条 `<li>` 加 `itemscope itemtype`（见页面 36 的 content.raw）；
 *     ② 结构化层：本函数把同两件资产并进站点 @graph（就是这里）。
 *
 * ⚠ 硬约束对齐（本文件开头）：**不得为不可见内容声明结构化数据**。
 *   故此处**不照抄后台文字**，而是声明「首页上确实看得见」的那两件资产。
 *   若日后首页删了这两条，本节点必须同删 —— 否则又是 F38 那种「架空声明」。
 *
 * ⚠ 与既有 `Dataset` 节点不冲突：那个是**每日天象数据集**（揭阳·逐日），
 *   这两件是**历法数据集与预印本**，`@id` 各自带独立 fragment。
 *
 * @return array 两节点（ScholarlyArticle ＋ Dataset）
 * @param array $which array('paper'=>bool,'dataset'=>bool) —— 逐件开关；
 *                     传空数组＝两件都发（向后兼容）。
 */
function kcj_astro_schema_front_assets($which = array()) {
    $all   = empty($which);
    $want  = function ($k) use ($which, $all) { return $all || !empty($which[$k]); };
    $home = home_url('/');
    // ★ 2026-09-25 修（Google 富结果校验 5 处缺陷）：原写法是**纯 @id 引用**，两处致命：
    //   ① `$who` 的 @id 拼成 `#person-author`，而图中只有 `#person` ⇒ **悬空引用**；
    //   ② `$pub` 指向 `https://zenodo.org`，该 @id **图内不存在**，且无 `name` ⇒ 校验器判「应指定 name 或 url」。
    //   修法：**一律内联 name／url**，不再依赖跨节点解析（Google 校验器不解析 @graph 内引用）。
    $who  = array(
        '@type' => 'Person',
        '@id'   => $home . '#person',          // ← 纠正：与图内 #person 节点同 id
        'name'  => '邝楚嘉 Chujia Kuang',
        'url'   => $home,
    );
    $pub  = array(
        '@type' => 'Organization',
        '@id'   => 'https://zenodo.org',
        'name'  => 'Zenodo',
        'url'   => 'https://zenodo.org/',
    );
    // 数据集的上级容器：原用 `#webpage`（＝当前页面），语义错位（页面不是数据集的父容器）。
    // 改指「站点」这一稳定容器，并内联 name／url。
    $partof = array(
        '@type' => 'WebSite',
        '@id'   => $home . '#website',
        'name'  => '邝楚嘉 Chujia Kuang — Chinese Calendrics & Solar Terms',
        'url'   => $home,
    );
    $out = array();
    // ★ v2.3.17（2026-09-25）：Google 富结果报这两件资产「未填写 image」。
    //   修法＝取站点**已有且真实可访问**的那张 OG 图 —— 与本图内 #richSnippet 节点同源，
    //   不新引任何外部资源。用 CDN 形态（i0.wp.com ... ?fit=1200%2C630），与图内既有
    //   ImageObject 节点的 URL 形态保持一致，避免同一张图出现两种写法。
    //   ⚠ 硬约束：图片必须是真实存在的资源 —— 不得填占位域（如 https://wp.com），
    //     那会让「未填写」变成「填了但无效」，评分可能更低。
    $og_image = 'https://i0.wp.com/kuangchujia.com/wp-content/uploads/2026/09/og-site-3.jpg?fit=1200%2C630&amp;ssl=1';

    // ① 预印本（002 · 换岁节点考据）
    if ($want('paper')) {
        $out[] = array(
            '@type'            => 'ScholarlyArticle',
            '@id'              => $home . '#asset-preprint-year-turn',
            'name'             => 'When Does the Year Turn: at Lichun, or at the First Day of the First Month?',
            // ★ v2.3.17：Google 对 Article 家族（含 ScholarlyArticle）**另有 headline 必填项**，
            //   填了 name 仍会报「未填写 headline」。按 Article 家族惯例，headline 与 name 同值。
            'headline'         => 'When Does the Year Turn: at Lichun, or at the First Day of the First Month?',
            'alternativeHeadline' => '立春换岁，还是正月初一换岁？',
            'image'            => $og_image,
            'abstract'         => '中国历法换岁节点的原始文献考据：立春换岁与正月初一换岁两说的来历与文献依据。',
            'inLanguage'       => array('en', 'zh-Hans'),
            'author'           => $who,
            'publisher'        => $pub,
            'isPartOf'         => $partof,
            'identifier'       => array(
                '@type' => 'PropertyValue',
                'propertyID' => 'DOI',
                'value'  => '10.5281/zenodo.22803746',
            ),
            'sameAs'           => 'https://doi.org/10.5281/zenodo.22803746',
            'url'              => 'https://doi.org/10.5281/zenodo.22803746',
            'license'          => 'https://creativecommons.org/licenses/by/4.0/',
            'creativeWorkStatus' => 'Preprint',
            'mainEntityOfPage' => array('@type' => 'WebPage', '@id' => $home . '#webpage'),
            'isAccessibleForFree' => true,
        );
    }

    // ② 开放数据集（chinese-calendar-dataset）
    if ($want('dataset')) {
        $out[] = array(
            '@type'            => 'Dataset',
            '@id'              => $home . '#asset-calendar-datasets',
            'name'             => 'Chinese Calendar Open Datasets',
            // ★ v2.3.17：同上报「未填写 image」。Dataset 无 headline/author 之要求
            //   （那是 Article 家族的规则，套到 Dataset 上属误报），故此处**只补 image**。
            'image'            => $og_image,
            'version'          => '1.0.0',
            // ★ 2026-09-25：原 36 字被判「description 字符串长度无效（过短）」⇒ 扩写到 150+ 字，
            //   交代数据内容、时间跨度、文件形态与用途（面向检索与复用者，非营销语）。
            'description'      => '中国历法开放数据集（Chinese Calendar Open Datasets）：收录干支纪日与纪年的推排结果、'
                . '二十四节气逐年交节时刻、历代历法改革（岁首与置闰变更）对照表，以及中国古代天象记录的整理条目。'
                . '数据以 CSV 与 JSON 两种格式随预印本一并公开，供天文史、历法史与数字人文研究核验与复用。',
            'inLanguage'       => array('en', 'zh-Hans'),
            'creator'          => $who,
            'publisher'        => $pub,
            'isPartOf'         => $partof,
            'identifier'       => array(
                '@type' => 'PropertyValue',
                'propertyID' => 'DOI',
                'value'  => '10.5281/zenodo.22788686',
            ),
            'sameAs'           => 'https://doi.org/10.5281/zenodo.22788686',
            'url'              => 'https://doi.org/10.5281/zenodo.22788686',
            'codeRepository'   => 'https://github.com/Kuangchujia/chinese-calendar-dataset',
            'license'          => 'https://creativecommons.org/licenses/by/4.0/',
            'isAccessibleForFree' => true,
        );
    }

    return $out;
}

/* --------------------------- 输出 --------------------------- */

/** 供模板调用：给定上下文与数据，返回应输出的节点数组 */
function kcj_astro_schema_nodes($context, $payload = array()) {
    switch ($context) {
        case 'daily':
            // ★ 2026-09-23（F38）：date_str 取不到时**必须直接返回空**。
            //   原先无论 payload 是否为空都照建节点，于是在**首页、每一篇博文、老黄历承载页**
            //   都输出了一个日期为空的 Dataset（线上实测值：name = 揭阳每日天象数据集（）、
            //   @id 以 `-` 结尾、temporalCoverage 缺失）—— 等于给「看不到该数据集」的页面
            //   声明数据集，违反本文件开头的硬约束「不得为不可见内容声明结构化数据」。
            if (empty($payload['date_str'])) {
                return array();
            }
            return kcj_astro_schema_daily(
                $payload['date_str'],
                isset($payload['data']) ? $payload['data'] : array()
            );
        case 'event':
            $ev = isset($payload['ev']) ? $payload['ev'] : array();
            if (($ev['event_type'] ?? '') === 'historical') {
                return kcj_astro_schema_scholarly($ev);
            }
            return kcj_astro_schema_should_emit('Event') ? kcj_astro_schema_event($ev) : array();
        case 'collection':
            return kcj_astro_schema_should_emit('CollectionPage')
                ? kcj_astro_schema_collection(isset($payload['items']) ? $payload['items'] : array())
                : array();
        case 'front':
            // ★ 2026-09-24（F63）：首页两件学术资产（预印本 ＋ 数据集）。
            //   与 daily 分支的差别：daily 要「页面确实渲染出今日天象」才发节点；
            //   这里同样守「可见才声明」——判据是**正文里确实有那两条**（见 payload 分支）。
            //   payload['assets'] 是逐件布尔：缺哪件就只发另一件。
            if (empty($payload['assets'])) {
                return array();
            }
            return kcj_astro_schema_front_assets($payload['assets']);
    }
    return array();
}

/** 把节点打成可安全嵌入的 <script> 标签 */
function kcj_astro_schema_tag($nodes) {
    if (!$nodes) {
        return '';
    }
    $json = wp_json_encode(
        array('@context' => 'https://schema.org', '@graph' => array_values($nodes)),
        JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE
    );
    if (!$json) {
        return '';
    }
    return '<script type="application/ld+json" class="kcj-astro-schema">' . $json . '</script>' . "\n";
}

/**
 * Rank Math 已启用时：把本插件负责的节点并进它的 @graph。
 * 注意 `rank_math/json_ld` 是 filter，回调必须 return。
 *
 * ★ 优先级为什么是 5 而不是 20（2026-09-23 改）：
 *   Rank Math 的 `add_context_data()` 挂在同一 filter 的**默认优先级 10**
 *   （includes/modules/schema/class-jsonld.php :: setup()），它按
 *   `can_add_global_entities()` 决定要不要补站点级实体（Person / WebSite /
 *   ImageObject / WebPage）。而该函数在 singular 页会先看 `! empty( $data )`：
 *   ```
 *   if ( is_front_page() || ! is_singular() || ! Helper::can_use_default_schema( $post_id ) || ! empty( $data ) )
 *       return true;   // class-jsonld.php L379
 *   ...
 *   return $this->do_filter( 'schema/add_global_entities', Helper::get_default_schema_type( $post_id, true ), $this ); // L394
 *   ```
 *   事件详情页的 CPT 默认 schema 在白名单外 ⇒ L394 拿到 false ⇒ **站点级实体被整体放弃**
 *   （这正是 79 页连 Person / WebSite 都没有的原因）。
 *   本插件若在它**之前**（优先级 < 10）就放入自己的节点，`! empty( $data )` 成立 ⇒
 *   站点级实体恢复输出。⇒ 放在 5，与「先由内容层提供实体、再由 Rank Math 补站点层」的设计一致。
 */
add_filter('rank_math/json_ld', function ($data, $jsonld = null) {
    $nodes = kcj_astro_schema_nodes(kcj_astro_schema_context(), kcj_astro_schema_payload());
    if (!$nodes) {
        return $data;
    }
    foreach ($nodes as $n) {
        $data[] = $n;
    }
    return $data;
}, 5, 2);

/**
 * ★ v2.3.18（2026-09-25）：把「街道级地址」从结构化数据里滤掉。
 *
 * 背景：Rank Math 的「知识图谱 / 个人」设置把 `PostalAddress` 整块输出到站点每一页的
 *   `@graph`（实测首页 / About / Papers / 典籍页各 1 处），其中 `streetAddress` 是
 *   **精确到门牌小区**的住址。结构化数据是**写给机器读的公开数据** —— 比页面上肉眼可见
 *   的文字更容易被采集与聚合，故只保留到「省 + 邮编 + 国别」，删掉街道层。
 *
 * 为什么只删一个字段、其余一律保留：用户口径是「详细地址隐藏，其它可以公开」。
 *   故 `addressRegion`（广东）/ `postalCode` / `addressCountry`（中国）/ `email` /
 *   `telephone` 全部**原样保留**，`@type` 也保留（只去字段、不去节点类型）。
 *
 * 为什么用递归遍历而非定点改键：Rank Math 的 `@graph` 结构随版本与页面类型变化
 *   （首页 8 节点、非首页 6 节点，节点位置不确定），且地址块可能嵌在任意节点下。
 *   定点路径会在下次升级时**静默失效** ⇒ 改为「深度优先找所有带 streetAddress 的节点」。
 *
 * ⚠ 本过滤器只对 **Rank Math 的输出**生效。若日后本插件自己也输出地址，须另行处理。
 * ⚠ 这是**输出层过滤**，不改 Rank Math 的存储值 —— 后台设置里那个地址还在，
 *   只是不再进 `@graph`。若要从根上删除，须去 Rank Math 后台设置。
 *
 * @param array $data Rank Math 的 @graph 数组（每个元素是一个节点）
 * @return array 过滤后的数组
 */
add_filter('rank_math/json_ld', function ($data) {
    if (!is_array($data)) {
        return $data;
    }
    foreach ($data as &$node) {
        kcj_astro_schema_strip_street($node);
    }
    unset($node);
    return $data;
}, 99);

/**
 * 递归删除节点（及其子节点）里的 `streetAddress` 键。
 * 只删这一个键：其余地址成分与节点类型全部保留。
 *
 * @param mixed $v 任意节点/子节点（引用传入，就地修改）
 * @return void
 */
function kcj_astro_schema_strip_street(&$v) {
    if (!is_array($v)) {
        return;
    }
    // 仅当该层是「地址节点」时才动它 —— 用 @type 判，避免误删同名业务字段。
    if ((isset($v['@type']) && $v['@type'] === 'PostalAddress')
        || (isset($v['streetAddress']) && !isset($v['@type']))) {
        unset($v['streetAddress']);
    }
    foreach ($v as &$child) {
        kcj_astro_schema_strip_street($child);
    }
    unset($child);
}

/** Rank Math 未启用时：自己往 head 打一份（优先级 20，排在正文之前） */
add_action('wp_head', function () {
    if (kcj_astro_rankmath_active()) {
        return;   // 上面那个 filter 已经并进 Rank Math 的 @graph，避免重复
    }
    $nodes = kcj_astro_schema_nodes(kcj_astro_schema_context(), kcj_astro_schema_payload());
    echo kcj_astro_schema_tag($nodes);   // phpcs:ignore WordPress.Security.EscapeOutput
}, 20);

/** 当前请求属于哪一类页面 */
function kcj_astro_schema_context() {
    if (function_exists('is_singular') && is_singular(KCJ_ASTRO_CPT)) {
        return 'event';
    }
    if ((function_exists('is_post_type_archive') && is_post_type_archive(KCJ_ASTRO_CPT))
        || (function_exists('is_tax') && is_tax(KCJ_ASTRO_TAX))) {
        return 'collection';
    }
    // ★ 2026-09-24（F63）：首页单列一类 —— 它有「两件学术资产」这一独有内容，
    //   既不是 CPT 详情／归档，也不该被归进 daily（daily 的语义是「逐日天象数据」）。
    //   ⚠ 判据**必须严**：只看 is_front_page()；**不可**用 `$data` 是否为空之类
    //     的间接迹象 —— 同页在不同插件状态下 $data 会变（见下方优先级 5 的说明）。
    if (function_exists('is_front_page') && is_front_page()) {
        return 'front';
    }
    return 'daily';
}

/**
 * 页面里是否**确实渲染出**「今日天象」块；是则返回该块所用的日期，否则返回空串。
 *
 * ★ v2.3.2（F62）：判据原先只认字面 `[astro_today]`。而「天象预告」页用的是
 *   `[astro_hub]` —— 它的「今日天象」栏**默认开启**（`today="1"`，见
 *   includes/shortcodes.php 的 shortcode_atts），且三栏都会渲染进 HTML
 *   （模板是 radio + CSS 切换，不是 JS 按需取数）⇒ 页面上确实有今日天象内容，
 *   却因为判据认不出这个短代码而**不声明 Dataset**。
 *
 * ⚠ today 的判定必须与短代码**逐字对齐**：`[astro_hub]` 里写的是
 *   `if ($atts['today'] === '1')`（**严格**比较字符串）⇒ 写 `today="true"` 或
 *   裸写 `today` 都算**关闭**。此处若改用宽松判据（`(bool)` 转换、`!= '0'` 之类），
 *   就会出现「页面上根本没这一栏、却声明了数据集」的**反向失真** —— 与本文件开头的
 *   硬约束「不得为不可见内容声明结构化数据」直接冲突。
 */
function kcj_astro_page_today_date($raw) {
    $raw = (string) $raw;
    if ($raw === '' || strpos($raw, '[') === false) {
        return '';
    }
    // ① [astro_today date="YYYY-MM-DD"] —— 显式日期优先，逐字用它
    if (preg_match('/\[astro_today[^\]]*date=["\']([0-9]{4}-[0-9]{2}-[0-9]{2})["\']/', $raw, $m)) {
        return $m[1];
    }
    // ② 裸 [astro_today] —— 即「今天」
    if (has_shortcode($raw, 'astro_today')) {
        return current_time('Y-m-d');
    }
    // ③ [astro_hub]（它内部会嵌套渲染 [astro_today]）。逐处读 today 开关，
    //    任一处开着即成立 —— 同一页放两个 hub 时，只要有一个开着就有内容。
    if (preg_match_all('/\[astro_hub\b([^\]]*)\]/', $raw, $mm)) {
        foreach ($mm[1] as $atts_raw) {
            $a = shortcode_parse_atts($atts_raw);
            // 没写 today 时与 shortcodes.php 的 shortcode_atts 默认值一致：'1'
            $today = (is_array($a) && array_key_exists('today', $a)) ? $a['today'] : '1';
            if ($today === '1') {
                return current_time('Y-m-d');
            }
        }
    }
    return '';
}

/** 依据上下文取节点所需的数据（只读数据表；查不到就返回空，宁缺勿造） */
function kcj_astro_schema_payload() {
    global $wpdb;
    $ctx = kcj_astro_schema_context();

    if ($ctx === 'event') {
        $post_id = get_the_ID();
        if (!$post_id) {
            return array();
        }
        $tbl = KCJ_Astro_DB::table('events');
        $ev  = $wpdb->get_row($wpdb->prepare("SELECT * FROM {$tbl} WHERE post_id = %d LIMIT 1", $post_id), ARRAY_A);
        return $ev ? array('ev' => $ev) : array();
    }

    // front：判据是「首页正文里**确实有**那两条」。用两个 DOI 号做锚 ——
    // ★ 为什么锚 DOI 而不锚栏目名或 <li>：栏目名是文案、会改；<li> 太泛（首页还有别的列表）。
    //   DOI 是**资产本身的永久标识**，它出现 ⇔ 资产在该页可见。
    // ⚠ 一旦首页删掉某一条，对应节点即自动不发 —— 守「不可见不声明」。
    if ($ctx === 'front') {
        $pid  = get_the_ID();
        $body = $pid ? (string) get_post_field('post_content', $pid) : '';
        $has_paper = (strpos($body, 'zenodo.22803746') !== false);
        $has_data  = (strpos($body, 'zenodo.22788686') !== false);
        if (!$has_paper && !$has_data) {
            return array();
        }
        return array('assets' => array('paper' => $has_paper, 'dataset' => $has_data));
    }

    if ($ctx === 'collection') {
        $tbl = KCJ_Astro_DB::table('events');
        $rows = $wpdb->get_results(
            "SELECT title, event_time_bj FROM {$tbl} WHERE publish_status = 1 ORDER BY jd_core ASC LIMIT 100",
            ARRAY_A
        );
        return array('items' => (array) $rows);
    }

    // daily：只有页面**确实渲染出**「今日天象」块时才给节点 ——
    // 判据（含 [astro_today] 与 [astro_hub] 两种承载方式）见 kcj_astro_page_today_date()。
    $post_id  = get_the_ID();
    $date_str = $post_id
        ? kcj_astro_page_today_date((string) get_post_field('post_content', $post_id))
        : '';
    if ($date_str === '') {
        return array();
    }
    $tbl = KCJ_Astro_DB::table('daily');
    $row = $wpdb->get_row($wpdb->prepare("SELECT data_json FROM {$tbl} WHERE date_str = %s LIMIT 1", $date_str), ARRAY_A);
    if (!$row) {
        return array();
    }
    $data = json_decode($row['data_json'], true);
    return array('date_str' => $date_str, 'data' => is_array($data) ? $data : array());
}
