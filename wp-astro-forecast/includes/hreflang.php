<?php
/**
 * 双语面：hreflang 标注（v2.3.8）
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
 *   · 首页与归档页**不出 hreflang**（它们不是某组语言面的一员，出了是噪音）；
 *   · ★ **请求末段须与命中页 slug 一致**（v2.3.8 新增）—— 挡「平台就近匹配
 *     把不存在 URL 返 200」导致的**跨组串线**，详见函数内前置约束注释。
 *
 * ── v2.3.8 修订记录（2026-09-24）────────────────────────────────────
 *   修：`/glossary/terms/en/`（**不存在的 URL**，平台返 200）曾输出
 *       `zh-CN → /articles/zh/`／`en → /articles/en/` —— **跨组串线**。
 *   因：`/glossary/terms/` 之下只有 slug `zh` 一页、**没有 `en`**；平台
 *       就近匹配返 200，插件按「命中页的 post_parent」找兄弟 ⇒ 取到别组。
 *   改：加前置约束 —— 请求末段 slug ≠ 命中页 slug  ⇒ 直接 return $empty。
 *   ★ 一句话：**自动配对逻辑，除了验「输出对不对」，还须验「输入真的命中
 *     了它以为命中的那条记录」。** 本例输出格式完全合法，只是配错了对象。
 *
 * ── v2.3.15 修订记录（2026-09-25）：补 article 支路 ──────────────────
 *   修：**全部文章页（post）此前一条 hreflang 都不出。**
 *       实测（2026-09-25）：线上 22 篇 post，hreflang 条数 **= 0**；
 *       而语言子页 16 个（3 条）、父栏目页 8 个（1 条）早已合规。
 *   因：本文件首行的 `if (!is_page()) return $empty;` —— **文章是 post，
 *       `is_page()` 恒为 false**，整条支路被挡死，连 x-default 都出不去。
 *       ⇒ 这是**「设计与实现对不上」**：文件头 L24—34 明明把「首页、文章、
 *       CPT、归档」列为「只出 x-default」，而这道闸让文章连那一条都没有。
 *   改：新增 case ⓪ article 支路，在 `is_page()` 闸**之前**判 `is_single()`。
 *
 *   ── 文章侧的配对锚：**分类 ＋ 互译元字段**，不是 slug、不是父子关系 ──
 *     页面侧靠「父页 ＋ slug(zh/en)」配对；文章侧没有这种结构 ——
 *     中英两篇是**同级的独立 post**，permalink 与 slug 毫无关系
 *     （中文 slug 是 URL 编码的汉字，英文 slug 是英文短语）。
 *     ⇒ 改用线上现成的两条锚：
 *       ① **分类**：`中文版`(默认 id 63494103) / `英文版`(默认 id 63494104)
 *          —— 只用来判「本页属于哪一侧」，**不用它猜对手是谁**；
 *       ② **互译元字段** `_kcj_translation_of`：存**对手 post id**，
 *          中英两篇各存一条（双向）⇒ 配对是**确定性**的，不靠相似度猜。
 *     ★ 为什么不做「按标题/正文相似度自动配」：本项目纪律是**不猜**。
 *       本地篇号命名已实测存在错配（`002` 下中文《立春换岁》配英文
 *       `Eclipse-Records-on-Oracle-Bones`，二者非互译）⇒ 任何「按命名
 *       或相似度推配对」的做法都会复活这个错误。宁可只出 x-default。
 *     ★ 分类 id 允许用 filter 覆盖，不写死在调用点（见 kcj_astro_hreflang_cat_ids）。
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

    // ── case ⓪（v2.3.15）：**文章页** —— 必须在 is_page() 闸之前判 ──────
    //   ★ 顺序是关键：文章是 post，`is_page()` 恒 false。若把本支路写在
    //     那道闸之后，它会**永远跑不到** —— 正是本次缺陷的成因。
    //   ★ 只在「单篇文章」上跑；归档（is_home / is_archive）不跑 ——
    //     归档不是某组语言面的一员，出了是噪音（沿用既有纪律）。
    if (function_exists('is_single') && is_single()) {
        return kcj_astro_hreflang_post_group();
    }

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

    // ── 前置约束（v2.3.8）：**请求末段须与命中页 slug 一致** ─────────────
    //   ★ 为什么必须加这道闸（2026-09-24 线上实测出的真实缺陷）：
    //   `/glossary/terms/en/` **这一页并不存在**（terms 之下只有 slug `zh`
    //   一页），但平台做了**就近匹配**，返回了某个页面且 **HTTP 200**。
    //   插件随后按「命中页的 post_parent」去找 zh/en 兄弟 —— 找到的是
    //   **别的组**的兄弟 ⇒ 输出 `zh-CN → /articles/zh/`、`en → /articles/en/`。
    //   等于对外声明「这个不存在的 URL 是 articles 的英文版」：
    //     · 假 URL 返 200 ⇒ 给搜索引擎送收录入口；
    //     · 假配对关系   ⇒ 可能污染 articles 的语言判定。
    //   ⇒ 判据修正：**配对正确还不算对，输入必须先真的命中它以为命中的那页。**
    //     末段不吻合 ⇒ 视为「URL 未精确命中」，直接跳过输出（宁缺勿造，绝不串组）。
    //   ★ 只在能取到请求路径时校验；取不到（CLI / 异常）时**从宽放行** ——
    //     本闸是为挡「假 URL」，不是为挡正常页面。
    if (!empty($_SERVER['REQUEST_URI'])) {
        $req_path = (string) parse_url(wp_unslash($_SERVER['REQUEST_URI']), PHP_URL_PATH);
        $req_seg  = trim(basename(rtrim($req_path, '/')), '/');
        // 首页等末段为空的情形不在此闸范围（本函数只跑 is_page）
        if ($req_seg !== '' && rawurldecode($req_seg) !== $self_slug) {
            return $empty;
        }
    }

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

/**
 * 文章页（post）的 hreflang 组 —— v2.3.15 新增。
 *
 * ── 配对锚：**分类判侧 ＋ 互译元字段定对手** ─────────────────────────
 *   ① 本页属哪一侧：读它的分类，看是否含「英文版」分类。
 *   ② 对手是谁：读 post meta `_kcj_translation_of`（存对手 post id）。
 *      该字段**双向存**（中篇存英篇 id，英篇存中篇 id）——
 *      只要一侧写了、另一侧也写了，配对才成立；**只写一侧视为配对不齐**。
 *      ⇒ 这就是文章侧的「双向契约」落点，与 hreflang 本身的双向要求同构。
 *
 * ── 取不到配对时的行为：宁缺勿造 ──────────────────────────────────
 *   · 本页无英文对手（纯中文文章）⇒ 只出 `x-default` 指自身，**不出 `zh`**。
 *     为什么不出 `zh`：那等于声明「本页是中文版」，而它并没有英文版，
 *     单侧声明会被 Google 整体忽略，还可能污染语言判定。⇒ 与既有口径一致。
 *   · 对手 id 存在但那篇**没发布／不存在／没回指本页** ⇒ 同上，只出 x-default。
 *     ★ 「不回指」也算配对不齐：hreflang 是双向契约，单侧无效（本项目已定谳）。
 *
 * @return array { links: array<code => url>, self_lang: string }
 */
function kcj_astro_hreflang_post_group() {
    $empty = array('links' => array(), 'self_lang' => '');

    if (!function_exists('get_queried_object_id')) {
        return $empty;
    }
    $pid = (int) get_queried_object_id();
    if ($pid <= 0) {
        return $empty;
    }

    $self_url = (string) get_permalink($pid);
    if ($self_url === '') {
        return $empty;
    }

    // ① 本页属于哪一侧？—— 靠分类，不靠 slug／篇号／标题相似度（纪律：不猜）
    $cats       = kcj_astro_hreflang_cat_ids();
    $is_en_side = false;
    if ($cats['en'] > 0 && function_exists('has_category')) {
        $is_en_side = (bool) has_category($cats['en'], $pid);
    }
    $self_lang = $is_en_side ? 'en' : 'zh-CN';

    // ② 对手是谁？—— 靠互译元字段，**不做相似度推断**
    $other_id = (int) get_post_meta($pid, '_kcj_translation_of', true);
    if ($other_id <= 0 || $other_id === $pid) {
        return array('links' => array('x-default' => $self_url), 'self_lang' => $self_lang);
    }

    // 对手必须：已发布、且**回指本页**（双向契约），否则视为配对不齐
    $opp = get_post($other_id);
    if (!$opp || $opp->post_status !== 'publish') {
        return array('links' => array('x-default' => $self_url), 'self_lang' => $self_lang);
    }
    $back = (int) get_post_meta($other_id, '_kcj_translation_of', true);
    if ($back !== $pid) {
        // 单侧声明 ⇒ 整组无效。宁缺勿造，只出 x-default。
        return array('links' => array('x-default' => $self_url), 'self_lang' => $self_lang);
    }

    $other_url = (string) get_permalink($other_id);
    if ($other_url === '') {
        return array('links' => array('x-default' => $self_url), 'self_lang' => $self_lang);
    }

    // ③ 三条齐出。x-default 指**中文页**（与站点既有口径一致：主受众为中文读者）
    $zh_url = $is_en_side ? $other_url : $self_url;
    $en_url = $is_en_side ? $self_url : $other_url;

    return array(
        'links' => array(
            'zh-CN'     => $zh_url,
            'en'        => $en_url,
            'x-default' => $zh_url,
        ),
        'self_lang' => $self_lang,
    );
}

/**
 * 中／英文版分类的 term id。
 *
 * ★ 为什么给 filter 而不是写死：分类 id 由站点生成（本项目线上为
 *   63494103 / 63494104），换站点或重建分类即变。写死在调用点会让
 *   「站点改版后静默失效」重演（本项目已因写死 PAGE_ID = 29 踩过一次）。
 *   默认值取线上实测值，站点可 filter 覆盖。
 *
 * @return array { zh: int, en: int }
 */
function kcj_astro_hreflang_cat_ids() {
    $ids = array('zh' => 63494103, 'en' => 63494104);
    if (function_exists('apply_filters')) {
        $ids = apply_filters('kcj_astro_hreflang_cat_ids', $ids);
    }
    return array(
        'zh' => isset($ids['zh']) ? (int) $ids['zh'] : 0,
        'en' => isset($ids['en']) ? (int) $ids['en'] : 0,
    );
}

/**
 * 注册互译元字段 `_kcj_translation_of` —— v2.3.15 新增。
 *
 * ★ 为什么必须注册（2026-09-25 实测踩到）：
 *   WordPress 的 REST `meta` 字段是**白名单制** —— 未注册的 meta 键，
 *   即使 PUT 带上去也**静默丢弃**，且**仍返 200**。
 *   实测：`PUT /wp/v2/sites/<id>/posts/10 {"meta":{"_kcj_translation_of":190}}`
 *   → 200，回读 `meta` 里**没有这个键**。`POST` 同样无效。
 *   这正与本项目在 Zenodo 侧记下的同一类坑：**「返 200」不等于「落库了」，
 *   只信回读。** ⇒ 要能写，必须先在服务端注册。
 *
 * ★ 为什么用 `register_post_meta` 而不是自己接 `rest_pre_insert_*`：
 *   注册是 WordPress 的标准做法，一次声明即同时打通
 *   「REST 读写 · `get_post_meta` · 权限校验 · 类型转换（integer）」四件事；
 *   自己接 filter 只解决写入，读取仍要另写一套，且类型不保证。
 *
 * ★ `single => true` / `type => integer`：字段值就是**对手 post 的 id**，
 *   不是数组、不是字符串。类型写对，`get_post_meta` 回读即得 int，
 *   免去调用点再做 `(int)` 转换 —— 少一层转换即少一处出错面。
 *
 * ★ 权限：`auth_callback` 用 `edit_post` 能力，**不用 `edit_posts`** ——
 *   后者只问「能不能编辑文章」这一类，前者才问「能不能编辑**这一篇**」。
 *   REST 写 meta 走的是逐篇鉴权，用错会越权。
 */
function kcj_astro_hreflang_register_meta() {
    if (!function_exists('register_post_meta')) {
        return;
    }
    register_post_meta('post', '_kcj_translation_of', array(
        'type'              => 'integer',
        'single'            => true,
        'default'           => 0,
        'show_in_rest'      => true,
        'sanitize_callback' => 'absint',
        'auth_callback'     => function ($allowed, $meta_key, $post_id) {
            return function_exists('current_user_can')
                ? current_user_can('edit_post', (int) $post_id)
                : false;
        },
    ));
}
if (function_exists('add_action')) {
    add_action('init', 'kcj_astro_hreflang_register_meta');
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
