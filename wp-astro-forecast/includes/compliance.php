<?php
/**
 * 合规层：统一免责声明自动挂载 + 自动内链（指令 09 + 指令 08 后半）
 *
 * ── 一、免责声明（指令 09）────────────────────────────────────────────
 * 原文要求「通过 the_content 钩子，判断当前页面为天象相关时，自动在底部追加统一免责声明」。
 * 实现要点（三处判断，缺一即出错）：
 *   ① **必须先去重**：本插件的三个模板已各自在板块底部输出声明；
 *      若无脑追加，天象详情页会出现**两份**声明（指令 10 的合规检查项之一）。
 *      故凡是「由本插件模板渲染的页面」一律跳过。
 *   ② **只在真的含天象内容的页面追加**：判据是正文里出现过本插件的短代码，
 *      或页面被管理端显式列入挂载名单。
 *   ③ 追加位置在正文**末尾**，且用 wp_kses 允许的最小标签集，避免注入。
 *
 * ── 二、统一声明文本（逐字沿用，并做一处事实收紧）────────────────────
 *   指令原文：「天象数据基于 NASA JPL DE421 星历计算，节气与月相符合
 *              GB/T 33661—2017 国家标准；预报时刻精度 ±1 分钟……」
 *   收紧点：GB/T 33661—2017《农历的编算和颁行》规定的是**农历的编排规则、
 *   计算模型和精度、表示方法**，其规范性附录 A 即二十四节气、附录 C 为六十干支周；
 *   该标准**不规定月相的公布精度**。故改为「农历日期与二十四节气的编排符合」——
 *   这是该标准真正覆盖的范围，可辩护；原措辞属超范围主张。
 *   仍在的诚实边界：DE421 覆盖区间（1899-07-28 至 2053-10-08）之外的历史回推
 *   走的是 Meeus 解析式，**未使用**行星历表，故统一声明里点明月相/节气口径的同时，
 *   详情页会另行按 method 逐条标注（不得让统一声明掩盖解析降级，见 F12）。
 *
 * ── 三、自动内链（指令 08 后半）──────────────────────────────────────
 * 默认**关闭**。理由：批量自动改写正文是 SEO 风险项（易被判操纵性内链），
 * 且一旦出错是全站性的。开启后行为受三条硬约束：
 *   · 每个关键词**每页最多注入一次**（首次出现处）；
 *   · 不进入 <a>/<h1-6>/<code>/<pre>/<script>/<style> 与已有链接内部；
 *   · 不链向当前页面自身。
 * 关键词表默认从分类法 term 自动派生（关键词 = 类型名，指向该类型归档页），
 * 也可由管理端用「关键词|URL」逐行覆写。
 *
 * 硬性约束：本文件不写入任何占星/运势/吉凶/谶纬字样。
 */

if (!defined('ABSPATH')) {
    exit;
}

/* ========================= 一、免责声明 ========================= */

/** 统一声明的正文（模板与钩子共用；改这一处即全站一致） */
function kcj_astro_disclaimer_text() {
    return '天象数据基于 NASA JPL DE421 星历计算，农历日期与二十四节气的编排符合 '
         . 'GB/T 33661—2017《农历的编算和颁行》；近未来预报时刻精度 ±1 分钟，'
         . '地面观测受天气、大气透明度影响，仅作天文参考。'
         . '历史天象板块为天文史实证研究，基于现代星历回推与历史文献对照，'
         . '仅作学术交流参考；不涉及星占、谶纬、吉凶解读。';
}

/** 免责声明的「指纹」——用于去重判定（取声明中一段稳定子串） */
function kcj_astro_disclaimer_signature() {
    return '不涉及星占、谶纬、吉凶解读';
}

add_filter('the_content', 'kcj_astro_append_disclaimer', 20);
function kcj_astro_append_disclaimer($content) {
    if (is_admin() || is_feed() || is_embed()) {
        return $content;
    }
    if (kcj_astro_is_astro_template_page()) {
        return $content;   // ① 模板已自带声明
    }
    if (!kcj_astro_page_is_astro_related()) {
        return $content;   // ② 非天象页
    }
    if (strpos($content, kcj_astro_disclaimer_signature()) !== false) {
        return $content;   // 已含声明（例如作者手写），不重复
    }
    return $content . kcj_astro_disclaimer_block();
}

/** 本插件模板负责渲染的页面（这些页面的声明由模板输出，钩子让位） */
function kcj_astro_is_astro_template_page() {
    if (function_exists('is_singular') && is_singular(KCJ_ASTRO_CPT)) {
        return true;
    }
    if (function_exists('is_post_type_archive') && is_post_type_archive(KCJ_ASTRO_CPT)) {
        return true;
    }
    if (function_exists('is_tax') && is_tax(KCJ_ASTRO_TAX)) {
        return true;
    }
    return false;
}

/** 页面是否天象相关：含本插件短代码，或被列入挂载名单 */
function kcj_astro_page_is_astro_related() {
    $id = get_the_ID();
    if (!$id) {
        return false;
    }
    $extra = kcj_astro_opt('disclaimer_page_ids', '');
    foreach (explode(',', (string) $extra) as $pid) {
        if ((int) trim($pid) === (int) $id) {
            return true;
        }
    }
    $raw = (string) get_post_field('post_content', $id);
    foreach (array('astro_today', 'astro_forecast_list', 'astro_related_events', 'astro_event_detail') as $sc) {
        if (has_shortcode($raw, $sc)) {
            return true;
        }
    }
    return false;
}

function kcj_astro_disclaimer_block() {
    return "\n" . '<div class="kcj-astro-disclaimer-block">'
         . '<p class="kcj-astro-disclaimer">' . esc_html(kcj_astro_disclaimer_text()) . '</p>'
         . '</div>' . "\n";
}

/* ========================= 二、自动内链 ========================= */

add_filter('the_content', 'kcj_astro_auto_internal_links', 21);
function kcj_astro_auto_internal_links($content) {
    if (is_admin() || is_feed() || is_embed()) {
        return $content;
    }
    if (kcj_astro_opt('auto_links', 0) != 1) {
        return $content;   // 默认关闭
    }
    $map = kcj_astro_link_map();
    if (!$map) {
        return $content;
    }
    $self = get_permalink();
    $parts = preg_split('/(<[^>]*>)/', $content, -1, PREG_SPLIT_DELIM_CAPTURE);
    if (!is_array($parts)) {
        return $content;
    }

    $suppress = 0;        // 进入 <a>/<h*>/<code>/<pre>/<script>/<style> 即 +1
    $used     = array();

    foreach ($parts as $i => $seg) {
        if ($seg === '') {
            continue;
        }
        if ($seg[0] === '<') {
            if (preg_match('#^<(a|h[1-6]|code|pre|script|style)\b#i', $seg)) {
                $suppress++;
            } elseif (preg_match('#^</(a|h[1-6]|code|pre|script|style)\s*>#i', $seg)) {
                $suppress = max(0, $suppress - 1);
            }
            continue;
        }
        if ($suppress > 0) {
            continue;
        }
        foreach ($map as $kw => $url) {
            if (isset($used[$kw]) || $kw === '') {
                continue;
            }
            if ($self && strpos($url, $self) === 0) {
                continue;   // 不链自身
            }
            $pos = mb_strpos($seg, $kw);
            if ($pos === false) {
                continue;
            }
            $parts[$i] = mb_substr($seg, 0, $pos)
                       . '<a href="' . esc_url($url) . '" class="kcj-astro-inlink">' . esc_html($kw) . '</a>'
                       . mb_substr($seg, $pos + mb_strlen($kw));
            $used[$kw] = true;
            // ★ 必须跳出：插入锚点后本段已含 HTML（href 与锚文本），
            //   若继续用同一 $seg 匹配别的关键词，会命中刚插入的标签内部。
            //   语义上也更干净——一个文本节点只注入一条内链。
            $seg = $parts[$i];
            break;
        }
    }
    return implode('', $parts);
}

/** 关键词 → URL 映射：管理端覆写优先，否则从分类法 term 派生 */
function kcj_astro_link_map() {
    $map  = array();
    $raw  = (string) kcj_astro_opt('link_map', '');
    if (trim($raw) !== '') {
        foreach (preg_split('/\r\n|\r|\n/', $raw) as $line) {
            if (strpos($line, '|') === false) {
                continue;
            }
            list($kw, $url) = array_map('trim', explode('|', $line, 2));
            if ($kw !== '' && $url !== '') {
                $map[$kw] = $url;
            }
        }
        return $map;
    }
    foreach (kcj_astro_event_types() as $slug => $label) {
        $t = get_term_by('slug', $slug, KCJ_ASTRO_TAX);
        if ($t && !is_wp_error($t)) {
            $link = get_term_link($t);
            if (!is_wp_error($link)) {
                $map[$label] = $link;
            }
        }
    }
    return $map;
}

/* ========================= 三、选项与设置页 ========================= */

function kcj_astro_opt($key, $default = '') {
    $o = get_option('kcj_astro_options', array());
    return (is_array($o) && array_key_exists($key, $o)) ? $o[$key] : $default;
}

add_action('admin_menu', function () {
    add_submenu_page(
        'edit.php?post_type=' . KCJ_ASTRO_CPT,
        '天象模块设置',
        '模块设置',
        'manage_options',
        'kcj-astro-settings',
        'kcj_astro_render_settings'
    );
});

add_action('admin_init', function () {
    register_setting('kcj_astro_settings_group', 'kcj_astro_options', array(
        'type'              => 'array',
        'sanitize_callback' => function ($in) {
            return array(
                'auto_links'           => (isset($in['auto_links']) && $in['auto_links'] == 1) ? 1 : 0,
                'link_map'             => sanitize_textarea_field(isset($in['link_map']) ? $in['link_map'] : ''),
                'disclaimer_page_ids'  => sanitize_text_field(isset($in['disclaimer_page_ids']) ? $in['disclaimer_page_ids'] : ''),
            );
        },
    ));
});

function kcj_astro_render_settings() {
    $o = get_option('kcj_astro_options', array());
    $o = is_array($o) ? $o : array();
    ?>
    <div class="wrap">
      <h1>天象模块设置</h1>
      <form method="post" action="options.php">
        <?php settings_fields('kcj_astro_settings_group'); ?>
        <table class="form-table">
          <tr>
            <th>自动内链</th>
            <td>
              <label><input type="checkbox" name="kcj_astro_options[auto_links]" value="1"
                <?php checked(isset($o['auto_links']) && $o['auto_links'] == 1); ?> /> 启用</label>
              <p class="description">默认关闭。每页每个关键词只注入一次；不进入已有链接与标题。</p>
            </td>
          </tr>
          <tr>
            <th>关键词映射</th>
            <td>
              <textarea name="kcj_astro_options[link_map]" rows="8" class="large-text code"
                placeholder="日食|/sky-forecast/solar_eclipse/"><?php
                echo esc_textarea(isset($o['link_map']) ? $o['link_map'] : ''); ?></textarea>
              <p class="description">每行一条「关键词|URL」。留空则自动从分类法类型名派生。</p>
            </td>
          </tr>
          <tr>
            <th>额外挂载免责声明的页面 ID</th>
            <td>
              <input type="text" class="regular-text" name="kcj_astro_options[disclaimer_page_ids]"
                value="<?php echo esc_attr(isset($o['disclaimer_page_ids']) ? $o['disclaimer_page_ids'] : ''); ?>" />
              <p class="description">逗号分隔。含本插件短代码的页面会自动挂载，无需在此填写。</p>
            </td>
          </tr>
        </table>
        <?php submit_button(); ?>
      </form>
      <hr />
      <h2>声明文本（当前生效版）</h2>
      <textarea rows="6" class="large-text" readonly><?php echo esc_textarea(kcj_astro_disclaimer_text()); ?></textarea>
      <p class="description">文本在插件内单一真值源维护（includes/compliance.php），模板与此处共用。</p>
    </div>
    <?php
}
