<?php
/**
 * 模板 B：天象预告列表块（指令 05 的短代码 2 与归档页共用）
 *
 * 数据：wp_astro_events 的已发布行（前端只读，Tab 切换为纯 CSS/JS，无实时请求）。
 * 变量（由 kcj_astro_render_template 提供）：
 *   $types  array( event_type => 中文名 )   —— 本次要渲染的 Tab（顺序即展示顺序）
 *   $groups array( event_type => 行数组 )   —— 每类的数据
 *   $active string                          —— 指定单一类型时该类型高亮（留空则首个 Tab 高亮）
 *
 * ★ v1.2.0 变更：
 *   - Tab 由 5 类改为 **6 类**（日食 / 月食 / 行星天象 / 流星雨 / 传统天象 / 历史天象），
 *     与指令 05 的 type 取值一一对应；「日月食」作为父类仍在分类法里（指令 04 的 5 类口径）。
 *   - 事件链接改走 kcj_astro_event_permalink()（尊重站点固定链接），
 *     不再硬编码 '/sky/forecast/' 路径 —— 那是 v1.1.0 的旧前缀。
 *   - 结构化数据由 includes/rankmath.php 统一输出（head 或 Rank Math 的 @graph），
 *     本模板不再自出 JSON-LD，避免同一页面两份同类型数据。
 */
if (!defined('ABSPATH')) { exit; }

$types  = isset($types)  && is_array($types)  ? $types  : array();
$groups = isset($groups) && is_array($groups) ? $groups : array();
$active = isset($active) ? (string) $active : '';
if ($active === '' && $types) {
    $active = (string) key($types);
}
?>
<div class="kcj-astro-list">
  <p class="kcj-astro-intro">
    天象预告按类型浏览。点击卡片进入详情。
    数据为离线预计算，前端不发起实时计算请求；近未来预报时刻精度 ±1 分钟。
    星历覆盖区间（默认 DE421：1899-07-28 至 2053-10-08）之外的历史条目改用解析式近似，
    并在详情页如实标注方法与不确定度区间。仅作天文参考，不涉及星占、谶纬、吉凶解读。
  </p>

  <?php if (!$types): ?>
    <?php echo kcj_astro_notice('暂无可展示的天象类型。'); ?>
  <?php else: ?>
  <nav class="kcj-astro-tabs" role="tablist">
    <?php foreach ($types as $t => $label): ?>
      <button type="button" role="tab"
              class="kcj-astro-tab<?php echo ($active === (string) $t) ? ' is-active' : ''; ?>"
              aria-selected="<?php echo ($active === (string) $t) ? 'true' : 'false'; ?>"
              data-tab="<?php echo esc_attr($t); ?>"><?php echo esc_html($label); ?></button>
    <?php endforeach; ?>
  </nav>

  <?php foreach ($types as $t => $label): ?>
    <section class="kcj-astro-panel" data-panel="<?php echo esc_attr($t); ?>"
             <?php echo ($active && $active !== (string) $t) ? 'hidden' : ''; ?>>
      <h3><?php echo esc_html($label); ?></h3>
      <?php if (empty($groups[$t])): ?>
        <p class="kcj-astro-nodata">该类型暂无已发布事件。</p>
      <?php else: ?>
        <ul class="kcj-astro-cards">
        <?php foreach ($groups[$t] as $row): ?>
          <li class="kcj-astro-card">
            <a href="<?php echo esc_url(kcj_astro_event_permalink($row)); ?>">
              <strong><?php echo esc_html($row['title']); ?></strong>
            </a>
            <span class="kcj-astro-time"><?php echo esc_html(!empty($row['event_time_bj']) ? $row['event_time_bj'] : '时间待定'); ?></span>
            <p><?php echo esc_html(wp_strip_all_tags(isset($row['summary']) ? (string) $row['summary'] : '')); ?></p>
          </li>
        <?php endforeach; ?>
        </ul>
      <?php endif; ?>
    </section>
  <?php endforeach; ?>
  <?php endif; ?>
</div>

<script>
(function () {
  var root = document.currentScript ? document.currentScript.closest('.kcj-astro-list') : null;
  root = root || document.querySelector('.kcj-astro-list');
  if (!root) { return; }
  var tabs = root.querySelectorAll('.kcj-astro-tab');
  var panels = root.querySelectorAll('.kcj-astro-panel');
  Array.prototype.forEach.call(tabs, function (b) {
    b.addEventListener('click', function () {
      var t = b.getAttribute('data-tab');
      Array.prototype.forEach.call(tabs, function (x) {
        x.classList.remove('is-active');
        x.setAttribute('aria-selected', 'false');
      });
      b.classList.add('is-active');
      b.setAttribute('aria-selected', 'true');
      Array.prototype.forEach.call(panels, function (p) {
        p.hidden = p.getAttribute('data-panel') !== t;
      });
    });
  });
})();
</script>
