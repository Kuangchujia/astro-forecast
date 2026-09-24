<?php
/**
 * 归档模板：天象事件列表（指令 06 的 archive-astro_event.php）
 *
 * 覆盖三种请求：CPT 归档 /sky-forecast/、分类法归档（event_type）、以及类型筛选。
 * 内容由 kcj_astro_render_template('astro-forecast-list') 渲染，
 * 与页面里插 [astro_forecast_list] 的短代码版共用同一份排版，避免两套样式漂移。
 *
 * 分类法归档时只展示该类型一个 Tab（active 已设定），不铺开全部 6 个。
 */
if (!defined('ABSPATH')) { exit; }

get_header();

global $wpdb;
$all_types = kcj_astro_event_types();
$tbl       = KCJ_Astro_DB::table('events');
$cols      = 'event_id, event_type, title, event_time_bj, summary, slug, post_id, method';

// 当前请求是否限定到某个类型（分类法归档 / ?event_type=）
$only = '';
if (is_tax(KCJ_ASTRO_TAX)) {
    $term = get_queried_object();
    if ($term && !empty($term->slug) && isset($all_types[$term->slug])) {
        $only = $term->slug;
    }
}
if ($only === '' && isset($_GET['event_type'])) {
    $req  = sanitize_key(wp_unslash($_GET['event_type']));
    $only = isset($all_types[$req]) ? $req : '';
}

$show   = ($only !== '') ? array($only => $all_types[$only]) : $all_types;
$groups = array();
foreach (array_keys($show) as $t) {
    $ord = ($t === 'historical') ? 'DESC' : 'ASC';
    $groups[$t] = $wpdb->get_results(
        $wpdb->prepare(
            "SELECT {$cols} FROM {$tbl} WHERE event_type = %s AND publish_status = 1 ORDER BY jd_core {$ord} LIMIT 200",
            $t
        ),
        ARRAY_A
    );
}
?>
<main id="primary" class="site-main kcj-astro-main kcj-astro-archive">
  <div class="kcj-astro-wrap">

    <nav class="kcj-astro-breadcrumb" aria-label="位置导航">
      <a href="<?php echo esc_url(home_url('/')); ?>">首页</a>
      <span aria-hidden="true">›</span>
      <a href="<?php echo esc_url(home_url('/' . KCJ_ASTRO_SLUG . '/')); ?>">天象预告</a>
    </nav>

    <header class="kcj-astro-archive-head">
      <h1><?php
        if ($only !== '') {
            echo esc_html($all_types[$only] . ' · 天象事件');
        } elseif (is_post_type_archive(KCJ_ASTRO_CPT)) {
            echo '天象预告';
        } else {
            echo esc_html(wp_get_document_title());
        }
      ?></h1>
      <p class="kcj-astro-note">
        本页数据为离线预计算结果的静态展示，前端不发起实时计算请求。
        预报时刻统一为北京时间（UTC+8）。
      </p>
    </header>

    <?php
    echo kcj_astro_render_template('astro-forecast-list', array(
        'types'  => $show,
        'groups' => $groups,
        'active' => $only,
    ));   // phpcs:ignore WordPress.Security.EscapeOutput
    ?>

  </div>
</main>
<?php
get_footer();
