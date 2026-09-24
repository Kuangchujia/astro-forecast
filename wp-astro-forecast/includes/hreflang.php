<?php
/**
 * 双语面：hreflang 标注（v2.3.7）
 *
 * ── 为什么由本插件做，而不是 Rank Math ────────────────────────────────
 *   站上已装 Rank Math 免费版。其 hreflang 能力（`hreflang` 标签面）属
 *   PRO / 或需后台逐页配置，免费版**没有**可编程的 `rank_math/…hreflang` filter。
 *   （沿用 includes/rankmath.php 文件头同一套「不猜源码」纪律：本项目对
 *   Rank Math 免费版的结论都来自下载源码逐行核对，不是推测。）
 *   故本插件直接在 `wp_head` 输出 —— 与 JSON-LD 走的两条路（有插件时并进
 *   `rank_math/json_ld` / 无插件时自打）**互不干扰**：那是 JSON-LD，这是 link 标签。
 *
 * ── ★ 用户原稿为什么不能用（2026-09-24 校验结论）────────────────────
 *   用户给的三条示例：
 *     <link rel="alternate" hreflang="zh"       href="https://kuangchujia.com" />
 *     <link rel="alternate" hreflang="en"       href="https://kuangchujia.com" />
 *     <link rel="alternate" hreflang="x-default" href="https://kuangchujia.com" />
 *   问题不在标签写法，在 **href 三条全同** —— 等于声明「中英两版都在同一个
 *   URL」，Google 会判定为**自指重复**并整体忽略该组，且可能反过来污染
 *   原页面的语言判定。**hreflang 是双向契约**：A 声明 B 是它的英文版，
 *   B 也必须声明 A 是它的中文版，缺一侧则整组作废。
 *   ⇒ 本文件按「**每页只声明自己所在那一组**」实现，天然满足双向。
 *
 * ── 站上三类页面，三种处理（实测取自线上 319 页）─────────────────────
 *   ① **语言子页**（8 组 × zh/en ＝ 16 页）：
 *      `/publications/zh/` ↔ `/publications/en/` …… 共 8 组。
 *      ⇒ 各页输出三条：`zh` 指中文页、`en` 指英文页、`x-default` 指**中文页**
 *        （站点主受众为中文读者，与 `locale` 一致；x-default 指中文而非
 *        英文，是本项目的口径选择，非技术必然）。
 *   ② **父栏目页 / 列表页**（`/publications/`、`/papers/`、`/all-posts/` …）：
 *      它们是**双语 Tab 单页**（同一 URL 内两面板切换），**不存在 en/zh 两版**
 *      ⇒ 只输出 `x-default` 指自身。**不输出 `zh`/`en`** —— 若强行指自身，
 *      就是在声明「本页是中文版」，而它同时是英文版，属反向失真。
 *   ③ 其余页（首页、文章、CPT、归档）：同上，只出 `x-default` 指自身。
 *
 * ── ★ 配对靠「父子关系 ＋ slug」，不靠写死 ID 表 ────────────────────
 *   写死 `585/592` 这类 ID 表会在站点改版时静默失效（本项目已因「工具未同批
 *   改指」踩过一次：`wp_pub_cite.py` 第一版写死 `PAGE_ID = 29`，站点改版后
 *   每日定时任务当场断言失败）。故本实现改为：
 *     · 取当前页的 `post_parent`；
 *     · 在该父页之下找 **slug === 'en'** 与 **slug === 'zh'** 的子页；
 *     · 两者俱全 ⇒ 判为语言对，按 slug 归位。
 *   **同一 parent 下 slug 为 en/zh 的页各至多一个**，这是 WordPress 的
 *   slug 唯一性保证（同父同级不许重名），故此配对是确定性的、不需要 ID 表。
 *   实测（2026-09-24，线上 319 页）：16 个子页分布在 8 个 parent 之下
 *   （29 / 35 / 74 / 75 / 13 / 53 / 616 / 700），每 parent 之下恰一枚 zh、
 *   一枚 en，**结论成立**。
 *
 * ── 硬约束 ─────────────────────────────────────────────────────────
 *   · 只输出**自身语言与配对语言**，不臆造第三语言；
 *   · 语言码用 `zh-CN` / `en`（BCP 47）；`x-default` 必出且恰一条；
 *   · **不写 `robots`／不写 `canonical`** —— 那是 Rank Math 的面，本插件不越界；
 *   · 首页与归档页**不出 hreflang**（它们不是某组语言面的一员，出了是噪音）。
 */

if (!defined('ABSPATH')) {
    exit;
}

/**
 * 取当前页的 hreflang 组。
 *
 * @return array { links: array<code => url>, self_lang: string }
 *               links 为空数组 ⇒ 不输出任何标签（首页/归档/非页）
 */
function kcj_astro_hreflang_group() {
    $empty = array('links' => array(), 'self_lang' => '');

    // 只处理**单篇页面**。首页、博客列表页、归档页、分类页一律跳过。
    if (!function_exists('is_page') || !is_page()) {
        return $empty;
    }

    $pid = (int) get_queried_object_id();
    if ($pid <= 0) {
        return $empty;
    }

    $self_slug = (string) get_post_field('post_name', $pid);
    $parent    = (int) get_post_field('post_parent', $pid);

    // ── case ①：本页就是语言子页（slug 为 zh 或 en，且父页存在）──────
    if (($self_slug === 'zh' || $self_slug === 'en') && $parent > 0) {
        $sibs = kcj_astro_hreflang_children($parent, array('zh', 'en'));
        if (isset($sibs['zh']) && isset($sibs['en'])) {
            // ★ x-default 指**中文页**：站点主受众为中文读者
            return array(
                'links' => array(
                    'zh-CN'     => $sibs['zh'],
                    'en'        => $sibs['en'],
                    'x-default' => $sibs['zh'],
                ),
                'self_lang' => ($self_slug === 'zh') ? 'zh-CN' : 'en',
            );
        }
        // 配对不齐（只有一侧）：宁缺勿造 —— 单侧 hreflang 会被 Google 整体忽略
        return array(
            'links' => array('x-default' => (string) get_permalink($pid)),
            'self_lang' => ($self_slug === 'zh') ? 'zh-CN' : 'en',
        );
    }

    // ── case ②：本页是父栏目页，且其下确实有一对语言子页 ──────────────
    //    父页是「双语 Tab 单页」（同 URL 内两面板），**不是** en/zh 之一
    //    ⇒ 只声明 x-default 指自身，不出 zh/en（出了即反向失真）。
    if ($parent === 0) {
        $kids = kcj_astro_hreflang_children($pid, array('zh', 'en'));
        if (isset($kids['zh']) && isset($kids['en'])) {
            return array(
                'links' => array('x-default' => (string) get_permalink($pid)),
                'self_lang' => 'zh-CN',
            );
        }
    }

    // ── case ③：普通页面 —— 只声明 x-default 指自身 ───────────────────
    return array(
        'links' => array('x-default' => (string) get_permalink($pid)),
        'self_lang' => 'zh-CN',
    );
}

/**
 * 在指定父页之下，按 slug 取子页永久链接。
 *
 * ★ 为什么用 `get_posts` 而不是直接 SQL：本函数在 `wp_head` 上跑，
 *   结果需进对象缓存；`get_posts` 自带的查询缓存能让同页多次调用零额外查询。
 *   且它已处理 `post_status`／`post_type` 的默认过滤，比手写 SQL 更难写错。
 *
 * @param int   $parent 父页 ID
 * @param array $slugs  要取的 slug 列表
 * @return array<slug => url>  —— 取不到的 slug 不在返回数组里（宁缺勿造）
 */
function kcj_astro_hreflang_children($parent, $slugs) {
    $out = array();
    foreach ((array) $slugs as $sl) {
        $hits = get_posts(array(
            'post_type'        => 'page',
            'post_status'      => 'publish',
            'post_parent'      => (int) $parent,
            'name'             => (string) $sl,
            'posts_per_page'   => 1,
            'fields'           => 'ids',
            'suppress_filters' => false,
        ));
        if ($hits) {
            $u = get_permalink((int) $hits[0]);
            if (is_string($u) && $u !== '') {
                $out[(string) $sl] = $u;
            }
        }
    }
    return $out;
}

/** 组装 hreflang link 标签（不打印，便于自检与复用） */
function kcj_astro_hreflang_tags() {
    $g = kcj_astro_hreflang_group();
    if (empty($g['links'])) {
        return '';
    }
    $out = '';
    foreach ($g['links'] as $code => $url) {
        $out .= '<link rel="alternate" hreflang="' . esc_attr($code) . '"'
              . ' href="' . esc_url($url) . '" />' . "\n";
    }
    return $out;
}

/**
 * 输出到 head。
 *
 * ★ 优先级 1 而不是 20：hreflang 与 canonical 同属 head 内语义标签，
 *   早晚不影响解析，但排在最前便于人工核对「这一页声明了哪几种语言」。
 *   与同文件的 JSON-LD（优先级 20）**不冲突** —— 两者输出的是不同标签名。
 */
add_action('wp_head', function () {
    echo kcj_astro_hreflang_tags();   // phpcs:ignore WordPress.Security.EscapeOutput -- 函数内已 esc
}, 1);
