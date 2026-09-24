<?php
/**
 * 单页模板：天象事件详情（指令 06 的 single-astro_event.php）
 *
 * ★ 为什么在插件里而不是主题目录（F21）：
 *   指令 06 原文让把模板放到 `wp-content/themes/seedlet/`。本站托管在 WordPress.com，
 *   **主题目录不可写**，且写进去会被主题升级覆盖。故改为插件内置模板 +
 *   `template_include` 过滤器注入（见 includes/cpt.php），并保留 WP 惯例：
 *   若主题里存在同名 single-astro_event.php，以主题为准。
 *
 * 渲染分工：正文内容全部由 kcj_astro_render_event_detail() 从数据表结构化输出，
 * 因此本页无需（也不该）调用 the_content()。文章编辑框里的正文刻意留空，
 * 以免出现「同一段文字两个来源」的分叉（这类分叉必然漂移）。
 */
if (!defined('ABSPATH')) { exit; }

get_header();

$kcj_eid = 0;
if (function_exists('get_the_ID')) {
    global $wpdb;
    $pid = get_the_ID();
    if ($pid) {
        $tbl = KCJ_Astro_DB::table('events');
        $kcj_eid = (int) $wpdb->get_var(
            $wpdb->prepare("SELECT event_id FROM {$tbl} WHERE post_id = %d LIMIT 1", $pid)
        );
    }
}
?>
<main id="primary" class="site-main kcj-astro-main kcj-astro-single">
  <div class="kcj-astro-wrap">

    <nav class="kcj-astro-breadcrumb" aria-label="位置导航">
      <a href="<?php echo esc_url(home_url('/')); ?>">首页</a>
      <span aria-hidden="true">›</span>
      <a href="<?php echo esc_url(home_url('/' . KCJ_ASTRO_SLUG . '/')); ?>">天象预告</a>
    </nav>

    <?php
    while (have_posts()) :
        the_post();
        if ($kcj_eid > 0) {
            // 已与数据表关联：按结构化数据渲染（含参数表、观测指南/文献三层、古今对照、声明）
            echo kcj_astro_render_event_detail($kcj_eid);   // phpcs:ignore WordPress.Security.EscapeOutput
        } else {
            // 后台手工新建、尚未关联数据表：退化为常规文章渲染，不伪造天象参数
            ?>
            <article class="kcj-astro-block">
              <h1 class="kcj-astro-title"><?php the_title(); ?></h1>
              <p class="kcj-astro-meta">
                本条目尚未关联天象数据集（wp_astro_events 无对应行），故不展示参数与回推结果。
              </p>
              <div class="kcj-astro-fallback"><?php the_content(); ?></div>
            </article>
            <?php
        }
    endwhile;
    ?>

  </div>
</main>
<?php
get_footer();
