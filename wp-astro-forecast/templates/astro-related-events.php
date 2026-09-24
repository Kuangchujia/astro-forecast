<?php
/**
 * 模板 D：古今对照 / 相关事件块（指令 05 的短代码 3，以及详情页内嵌）
 *
 * 变量：$src（源事件行）$items（关联行数组）$mode（auto|historical|future）
 *
 * 两条来源会在数据层合并（见 shortcodes.php kcj_astro_fetch_related）：
 *   · relation —— 显式关系（wp_astro_relations，来自后台元字段或导入）
 *   · same_type —— 同类型兜底（按 jd_core 最接近的）
 * 页面上如实区分这两者，不让读者把「同类型」误当成「已考证的对应关系」。
 *
 * 硬性约束：仅陈述时间与类型；不做任何吉凶、对应、预言式陈述。
 */
if (!defined('ABSPATH')) { exit; }

$src   = isset($src)   && is_array($src)   ? $src   : array();
$items = isset($items) && is_array($items) ? $items : array();
$mode  = isset($mode) ? (string) $mode : 'auto';

$mode_label = array(
    'historical' => '同类历史天象',
    'future'     => '同类未来天象',
    'auto'       => '古今对照 / 相关',
);
$heading = isset($mode_label[$mode]) ? $mode_label[$mode] : $mode_label['auto'];

if (!$items) {
    return;   // 无关联就不占版面（模板被 include，return 即输出为空）
}
?>
<section class="kcj-astro-block kcj-astro-related-block">
  <h2><?php echo esc_html($heading); ?></h2>
  <p class="kcj-astro-note">
    与「<?php echo esc_html($src['title'] ?? ''); ?>」的关联条目。
    「已关联」为人工/导入建立的关系；「同类型」是按天象类型与发生时刻就近列出，
    两者性质不同，请勿混同。
  </p>
  <ul class="kcj-astro-related">
  <?php foreach ($items as $r): ?>
    <li>
      <?php if (!empty($r['rel_type'])): ?>
        <span class="kcj-astro-reltag">已关联·<?php echo esc_html($r['rel_type']); ?></span>
      <?php else: ?>
        <span class="kcj-astro-reltag kcj-astro-reltag-alt">同类型</span>
      <?php endif; ?>
      <a href="<?php echo esc_url(kcj_astro_event_permalink($r)); ?>"><?php echo esc_html($r['title'] ?? ''); ?></a>
      <?php if (!empty($r['event_time_bj'])): ?>
        <span class="kcj-astro-time"><?php echo esc_html($r['event_time_bj']); ?></span>
      <?php endif; ?>
    </li>
  <?php endforeach; ?>
  </ul>
</section>
