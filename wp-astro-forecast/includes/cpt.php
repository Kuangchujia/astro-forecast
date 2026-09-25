<?php
/**
 * 功能层：自定义文章类型 / 分类法 / 元字段 / 模板注入（指令 04 + 指令 06）
 *
 * ★ v1.2.0 修掉的必崩缺陷（F20）：
 *   v1.1.0 把 register_post_type() 写在 **register_activation_hook 里**。
 *   WordPress 的 CPT 必须在**每个请求**的 init 阶段注册，激活钩子只跑一次，
 *   所以激活之后每次请求 astro_event 都是「未注册」状态 —— 详情页与归档页
 *   **必然 404**，后台菜单也会消失。本文件把注册改到 init 上（标准做法），
 *   激活钩子只保留「建表 + flush_rewrite_rules」。
 *
 * ★ 另一处架构裁定（F21）：指令 06 要求把模板放进
 *   `wp-content/themes/seedlet/`。**本站做不到**：kuangchujia.com 托管在
 *   WordPress.com，主题目录对用户不可写（也不该写——主题升级会覆盖）。
 *   故改为「插件内置模板 + template_include 过滤器注入」，
 *   并保留 WP 惯例的优先级：**若主题里存在同名模板，以主题为准**。
 *
 * URL 前缀：`sky-forecast`（指令 04 指定）—— 归档 /sky-forecast/，详情 /sky-forecast/{slug}/。
 *   v1.1.0 用的是 `sky/forecast`（两段式），与「单段前缀」相比更易被同名页面抢占路由，
 *   故此处统一为指令指定的单段式，并对旧 URL 加 301（可能已被收录）。
 *
 * 硬性约束：全站禁占星/运势/吉凶/谶纬；不得虚构；时刻口径统一北京时间（UTC+8）。
 */

if (!defined('ABSPATH')) {
    exit;
}

const KCJ_ASTRO_CPT     = 'astro_event';
const KCJ_ASTRO_TAX     = 'event_type';
const KCJ_ASTRO_SLUG    = 'sky-forecast';
const KCJ_ASTRO_OLD_URL = '/sky/forecast/';

/* -------------------------------------------------------------------------
 * 事件类型：单一真值源
 * ---------------------------------------------------------------------- */

/**
 * 存进数据表 event_type 列的 6 个值（与 sql/install_tables.sql 的 ENUM 一致）。
 * 指令 05 的 type 参数正好也是这 6 个，一一对应。
 */
function kcj_astro_event_types() {
    return array(
        'solar_eclipse' => '日食',
        'lunar_eclipse' => '月食',
        'planet'        => '行星天象',
        'meteor'        => '流星雨',
        'traditional'   => '传统天象',
        'historical'    => '历史天象',
    );
}

/**
 * 分类法的顶层树（指令 04 的「日月食类 / 行星天象 / 流星雨 / 传统天象 / 历史天象」5 类）。
 * 指令 04 把日月食合成一类，指令 05 的 type 却分列 solar / lunar —— 两者在此同时满足：
 * 顶层 5 类中「日月食」为父项，其下挂 solar_eclipse / lunar_eclipse 两个子项。
 */
function kcj_astro_type_tree() {
    return array(
        array('slug' => 'eclipse', 'label' => '日月食', 'parent' => '',
              'members' => array('solar_eclipse', 'lunar_eclipse')),
        array('slug' => 'solar_eclipse', 'label' => '日食', 'parent' => 'eclipse', 'members' => array()),
        array('slug' => 'lunar_eclipse', 'label' => '月食', 'parent' => 'eclipse', 'members' => array()),
        array('slug' => 'planet', 'label' => '行星天象', 'parent' => '', 'members' => array()),
        array('slug' => 'meteor', 'label' => '流星雨', 'parent' => '', 'members' => array()),
        array('slug' => 'traditional', 'label' => '传统天象', 'parent' => '', 'members' => array()),
        array('slug' => 'historical', 'label' => '历史天象', 'parent' => '', 'members' => array()),
    );
}

/**
 * 短代码 type 参数 → 一组 event_type 值。未知取值返回 null（调用方据此报错）。
 * 兼容三套写法：指令 05 的短名（solar/lunar）、表内真名（solar_eclipse/lunar_eclipse）、
 * 以及父类名（eclipse = 日月食合计）。
 */
function kcj_astro_resolve_type($type) {
    $type = strtolower(trim((string) $type));
    if ($type === '') {
        return array_keys(kcj_astro_event_types());   // 空 = 全部
    }
    $alias = array(
        'solar'         => array('solar_eclipse'),
        'solar_eclipse' => array('solar_eclipse'),
        'lunar'         => array('lunar_eclipse'),
        'lunar_eclipse' => array('lunar_eclipse'),
        'eclipse'       => array('solar_eclipse', 'lunar_eclipse'),
        'eclipses'      => array('solar_eclipse', 'lunar_eclipse'),
        'planet'        => array('planet'),
        'meteor'        => array('meteor'),
        'traditional'   => array('traditional'),
        'historical'    => array('historical'),
    );
    return isset($alias[$type]) ? $alias[$type] : null;
}

/* -------------------------------------------------------------------------
 * CPT / 分类法 / 元字段注册（必须在 init）
 * ---------------------------------------------------------------------- */

add_action('init', 'kcj_astro_register_cpt', 5);
function kcj_astro_register_cpt() {
    register_post_type(KCJ_ASTRO_CPT, array(
        'labels' => array(
            'name'               => '天象事件',
            'singular_name'      => '天象事件',
            'add_new'            => '新建事件',
            'add_new_item'       => '新建天象事件',
            'edit_item'          => '编辑天象事件',
            'new_item'           => '新天象事件',
            'view_item'          => '查看天象事件',
            'search_items'       => '搜索天象事件',
            'not_found'          => '未找到天象事件',
            'all_items'          => '全部天象事件',
            'archives'           => '天象事件归档',
        ),
        'public'             => true,
        'show_ui'            => true,
        'show_in_menu'       => true,
        'show_in_rest'       => true,
        'menu_position'      => 26,
        'menu_icon'          => 'dashicons-star-filled',
        'has_archive'        => KCJ_ASTRO_SLUG,
        'rewrite'            => array('slug' => KCJ_ASTRO_SLUG, 'with_front' => false),
        'supports'           => array('title', 'editor', 'excerpt', 'thumbnail', 'custom-fields', 'revisions'),
        'taxonomies'         => array(KCJ_ASTRO_TAX),
        'capability_type'    => 'post',
        'map_meta_cap'       => true,
    ));

    register_taxonomy(KCJ_ASTRO_TAX, array(KCJ_ASTRO_CPT), array(
        'labels' => array(
            'name'          => '天象类型',
            'singular_name' => '天象类型',
            'all_items'     => '全部天象类型',
            'edit_item'     => '编辑天象类型',
            'add_new_item'  => '新建天象类型',
        ),
        'public'            => true,
        'hierarchical'      => true,
        'show_admin_column' => true,
        'show_in_rest'      => true,
        'rewrite'           => array('slug' => KCJ_ASTRO_SLUG, 'with_front' => false),
    ));

    // 默认分类项（幂等：已存在则跳过）
    foreach (kcj_astro_type_tree() as $node) {
        $parent_id = 0;
        if ($node['parent'] !== '') {
            $pt = get_term_by('slug', $node['parent'], KCJ_ASTRO_TAX);
            if ($pt && !is_wp_error($pt)) {
                $parent_id = (int) $pt->term_id;
            }
        }
        if (!get_term_by('slug', $node['slug'], KCJ_ASTRO_TAX)) {
            wp_insert_term($node['label'], KCJ_ASTRO_TAX, array(
                'slug'   => $node['slug'],
                'parent' => $parent_id,
            ));
        }
    }
}

/**
 * 元字段（指令 04 的「事件参数」清单）。
 * 与数据表 wp_astro_events 的列一一对应；表为权威存储，元字段供后台编辑与 REST 读写。
 * 关联类（历史/未来事件 ID）以逗号分隔的 ID 串存于元字段，
 * 落库时展开为 wp_astro_relations 的行（保住 1NF，见 class-astro-db.php）。
 */
function kcj_astro_meta_fields() {
    return array(
        'kcj_jd_core'            => array('type' => 'number', 'label' => '事件核心时刻（TT 儒略日）'),
        'kcj_event_time_bj'      => array('type' => 'string', 'label' => '北京时间（东八区）'),
        'kcj_params'             => array('type' => 'string', 'label' => '事件参数（食分/视星等/角距，JSON）'),
        'kcj_obs_site'           => array('type' => 'string', 'label' => '观测地 / 坐标口径'),
        'kcj_source_ref'         => array('type' => 'string', 'label' => '文献出处'),
        'kcj_method'             => array('type' => 'string', 'label' => '计算方法（ephemeris_de421 / analytic_meeus）'),
        'kcj_ephemeris'          => array('type' => 'string', 'label' => '星历档与覆盖区间（溯源）'),
        'kcj_related_hist_ids'   => array('type' => 'string', 'label' => '关联历史事件 ID（逗号分隔）'),
        'kcj_related_future_ids' => array('type' => 'string', 'label' => '关联未来事件 ID（逗号分隔）'),
    );
}

add_action('init', 'kcj_astro_register_meta', 6);
function kcj_astro_register_meta() {
    foreach (kcj_astro_meta_fields() as $key => $def) {
        register_post_meta(KCJ_ASTRO_CPT, $key, array(
            'type'              => $def['type'],
            'single'            => true,
            'show_in_rest'      => true,
            'sanitize_callback' => ($def['type'] === 'number') ? 'kcj_astro_sanitize_float' : 'sanitize_text_field',
            'auth_callback'     => function () {
                return current_user_can('edit_posts');
            },
        ));
    }
}

function kcj_astro_sanitize_float($v) {
    return is_numeric($v) ? (float) $v : '';
}

/** 元字段编辑界面（原生自定义字段面板对使用者不友好，故给一个明确的分组框） */
add_action('add_meta_boxes', function () {
    add_meta_box('kcj_astro_params', '天象参数（与数据表同步）', function ($post) {
        wp_nonce_field('kcj_astro_save_meta', 'kcj_astro_nonce');
        echo '<p style="margin:0 0 8px;color:#666">本页正文由数据表结构化渲染，无需在此填写；'
           . '下方参数保存后写回 wp_astro_events。</p><table class="form-table">';
        foreach (kcj_astro_meta_fields() as $key => $def) {
            $val = get_post_meta($post->ID, $key, true);
            printf(
                '<tr><th style="width:34%%"><label for="%1$s">%2$s</label></th>'
                . '<td><input type="%3$s" id="%1$s" name="%1$s" value="%4$s" class="regular-text" '
                . 'step="any" /></td></tr>',
                esc_attr($key),
                esc_html($def['label']),
                ($def['type'] === 'number') ? 'number' : 'text',
                esc_attr($val)
            );
        }
        echo '</table>';
    }, KCJ_ASTRO_CPT, 'normal', 'high');
});

/**
 * 保存：元字段 → 数据表 → 关联表。写回是**单向**的（后台 → 表），
 * 避免与 REST 导入形成双向竞争。
 */
add_action('save_post_' . KCJ_ASTRO_CPT, 'kcj_astro_save_meta_to_table', 10, 2);
function kcj_astro_save_meta_to_table($post_id, $post) {
    if (defined('DOING_AUTOSAVE') && DOING_AUTOSAVE) {
        return;
    }
    if (wp_is_post_revision($post_id)) {
        return;
    }
    if (!isset($_POST['kcj_astro_nonce']) || !wp_verify_nonce($_POST['kcj_astro_nonce'], 'kcj_astro_save_meta')) {
        return;
    }
    if (!current_user_can('edit_post', $post_id)) {
        return;
    }

    foreach (array_keys(kcj_astro_meta_fields()) as $key) {
        if (isset($_POST[$key])) {
            $raw = wp_unslash($_POST[$key]);
            $val = (strpos($key, 'ids') !== false) ? kcj_astro_sanitize_id_list($raw) : sanitize_text_field($raw);
            update_post_meta($post_id, $key, $val);
        }
    }

    global $wpdb;
    $tbl = KCJ_Astro_DB::table('events');
    $row = $wpdb->get_row($wpdb->prepare("SELECT event_id FROM {$tbl} WHERE post_id = %d LIMIT 1", $post_id), ARRAY_A);
    if (!$row) {
        return;   // 尚未与表建立关联（一般由 REST 导入创建），不新建表行，避免两套真值
    }
    $eid = (int) $row['event_id'];

    $wpdb->update($tbl, array(
        'title'          => $post->post_title,
        'slug'           => $post->post_name,
        'summary'        => $post->post_excerpt,
        'obs_site'       => get_post_meta($post_id, 'kcj_obs_site', true),
        'source_ref'     => get_post_meta($post_id, 'kcj_source_ref', true),
        'method'         => get_post_meta($post_id, 'kcj_method', true),
        'ephemeris'      => get_post_meta($post_id, 'kcj_ephemeris', true),
        'publish_status' => ($post->post_status === 'publish') ? 1 : 0,
    ), array('event_id' => $eid));

    // 两个关联 ID 串 → 关系表（整表替换，保证幂等）
    $pairs = array();
    foreach (array('kcj_related_hist_ids' => 'same_type', 'kcj_related_future_ids' => 'related') as $k => $rel) {
        foreach (explode(',', (string) get_post_meta($post_id, $k, true)) as $id) {
            $id = (int) trim($id);
            if ($id > 0) {
                $pairs[] = array('to' => $id, 'type' => $rel);
            }
        }
    }
    KCJ_Astro_DB::replace_relations($eid, $pairs);
}

function kcj_astro_sanitize_id_list($raw) {
    $out = array();
    foreach (explode(',', (string) $raw) as $id) {
        $id = (int) trim($id);
        if ($id > 0) {
            $out[] = $id;
        }
    }
    return implode(',', $out);
}

/**
 * 事件表 → CPT 文章（指令 03：「天象事件自动导入为自定义文章类型，同时写入自定义元字段」）。
 * 幂等：有 post_id 就更新，没有就新建并回填 post_id。
 */
function kcj_astro_sync_event_to_post($event_id) {
    global $wpdb;
    $tbl = KCJ_Astro_DB::table('events');
    $ev  = $wpdb->get_row($wpdb->prepare("SELECT * FROM {$tbl} WHERE event_id = %d LIMIT 1", (int) $event_id), ARRAY_A);
    if (!$ev) {
        return 0;
    }

    $postarr = array(
        'post_type'    => KCJ_ASTRO_CPT,
        'post_title'   => $ev['title'],
        'post_name'    => $ev['slug'],
        'post_excerpt' => (string) $ev['summary'],
        // 正文留空：前端由 single-astro_event.php 按数据表结构化渲染（单一真值源）。
        'post_content' => '',
        'post_status'  => ((int) $ev['publish_status'] === 1) ? 'publish' : 'draft',
    );
    if (!empty($ev['post_id'])) {
        $postarr['ID'] = (int) $ev['post_id'];
    } else {
        // ★ v2.2.0（F52）：**先按 slug 认领已有文章**，再决定是否新建。
        //   原来直接 wp_insert_post：同一 slug 第二次同步会因 post_name 撞车，
        //   被 WordPress 自动改成 `-2`、`-3`，于是同一事件长出多篇页面，
        //   且**不会报任何错**（线上此前已有 79 篇由 REST 建出的文章，
        //   而数据表为空 —— 导入时若不同步这一步就会整批重复）。
        $adopt = (int) $wpdb->get_var($wpdb->prepare(
            "SELECT ID FROM {$wpdb->posts}
             WHERE post_type = %s AND post_name = %s AND post_status NOT IN ('trash','auto-draft')
             ORDER BY ID ASC LIMIT 1",
            KCJ_ASTRO_CPT,
            (string) $ev['slug']
        ));
        if ($adopt > 0) {
            $postarr['ID'] = $adopt;
        }
    }

    $post_id = wp_insert_post($postarr, true);
    if (is_wp_error($post_id) || !$post_id) {
        return 0;
    }

    if (empty($ev['post_id'])) {
        $wpdb->update($tbl, array('post_id' => (int) $post_id), array('event_id' => (int) $event_id));
    }

    $meta = array(
        'kcj_jd_core'       => $ev['jd_core'],
        'kcj_event_time_bj' => (string) $ev['event_time_bj'],
        'kcj_params'        => (string) $ev['params_json'],
        'kcj_obs_site'      => (string) $ev['obs_site'],
        'kcj_source_ref'    => (string) $ev['source_ref'],
        'kcj_method'        => (string) $ev['method'],
        'kcj_ephemeris'     => (string) $ev['ephemeris'],
    );
    foreach ($meta as $k => $v) {
        update_post_meta($post_id, $k, $v);
    }
    $rel = $wpdb->get_results($wpdb->prepare(
        "SELECT to_event, rel_type FROM " . KCJ_Astro_DB::table('relations') . " WHERE from_event = %d",
        (int) $event_id
    ), ARRAY_A);
    $same = array();
    $fut  = array();
    foreach ((array) $rel as $r) {
        if ($r['rel_type'] === 'same_type') {
            $same[] = (int) $r['to_event'];
        } else {
            $fut[] = (int) $r['to_event'];
        }
    }
    update_post_meta($post_id, 'kcj_related_hist_ids', implode(',', $same));
    update_post_meta($post_id, 'kcj_related_future_ids', implode(',', $fut));

    // 分类项
    if (isset(kcj_astro_event_types()[$ev['event_type']])) {
        $t = get_term_by('slug', $ev['event_type'], KCJ_ASTRO_TAX);
        if ($t && !is_wp_error($t)) {
            wp_set_object_terms($post_id, array((int) $t->term_id), KCJ_ASTRO_TAX, false);
        }
    }

    return (int) $post_id;
}

/* -------------------------------------------------------------------------
 * 后台列表：加类型 / 北京时间 / 状态三列，便于人工核对
 * ---------------------------------------------------------------------- */

add_filter('manage_' . KCJ_ASTRO_CPT . '_posts_columns', function ($cols) {
    $new = array();
    foreach ($cols as $k => $v) {
        $new[$k] = $v;
        if ($k === 'title') {
            $new['kcj_type']     = '天象类型';
            $new['kcj_time_bj']  = '北京时间';
            $new['kcj_method']   = '计算方法';
        }
    }
    return $new;
});

add_action('manage_' . KCJ_ASTRO_CPT . '_posts_custom_column', function ($col, $post_id) {
    if ($col === 'kcj_type') {
        $terms = get_the_terms($post_id, KCJ_ASTRO_TAX);
        echo (is_array($terms) && $terms) ? esc_html($terms[0]->name) : '—';
    } elseif ($col === 'kcj_time_bj') {
        echo esc_html(get_post_meta($post_id, 'kcj_event_time_bj', true) ?: '—');
    } elseif ($col === 'kcj_method') {
        echo esc_html(get_post_meta($post_id, 'kcj_method', true) ?: '—');
    }
}, 10, 2);

/* -------------------------------------------------------------------------
 * 模板注入（指令 06 的可执行替代方案）
 * ---------------------------------------------------------------------- */

/**
 * 优先级：主题同名模板 > 插件内置模板。
 * 这样既能在 WP.com（主题目录不可写）上工作，也不妨碍将来自建主题时覆写。
 */
add_filter('template_include', function ($template) {
    if (is_singular(KCJ_ASTRO_CPT)) {
        $theme = locate_template(array('single-' . KCJ_ASTRO_CPT . '.php'));
        if ($theme) {
            return $theme;
        }
        $mine = KCJ_ASTRO_PATH . 'templates/single-' . KCJ_ASTRO_CPT . '.php';
        return file_exists($mine) ? $mine : $template;
    }
    if (is_post_type_archive(KCJ_ASTRO_CPT) || is_tax(KCJ_ASTRO_TAX)) {
        $theme = locate_template(array('archive-' . KCJ_ASTRO_CPT . '.php'));
        if ($theme) {
            return $theme;
        }
        $mine = KCJ_ASTRO_PATH . 'templates/archive-' . KCJ_ASTRO_CPT . '.php';
        return file_exists($mine) ? $mine : $template;
    }
    return $template;
});

/* -------------------------------------------------------------------------
 * 旧 URL 301（F21）：/sky/forecast/... → /sky-forecast/...
 * ---------------------------------------------------------------------- */

/**
 * 为什么要加：v1.1.0 的 CPT 用的是两段式前缀 `sky/forecast`，
 * v1.2.0 按指令 04 改为单段式 `sky-forecast`。若旧 URL 已被收录，
 * 不留跳转就会产生一批 404（指令 10 明确要求「无错链、无死链」）。
 * 该跳转**不依赖 CPT 是否注册**，故挂在 template_redirect 上直接判原串。
 */
add_action('template_redirect', function () {
    if (is_admin() || wp_doing_ajax()) {
        return;
    }
    $uri = isset($_SERVER['REQUEST_URI']) ? (string) $_SERVER['REQUEST_URI'] : '';
    $pos = strpos($uri, KCJ_ASTRO_OLD_URL);
    if ($pos === false) {
        return;
    }
    // 只处理以旧前缀开头的路径，避免误伤含该片段的查询串
    $path = strtok($uri, '?');
    if (strpos($path, KCJ_ASTRO_OLD_URL) !== 0) {
        return;
    }
    $target = home_url(str_replace(KCJ_ASTRO_OLD_URL, '/' . KCJ_ASTRO_SLUG . '/', $path));
    wp_safe_redirect($target, 301);
    exit;
});
