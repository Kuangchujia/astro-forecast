<?php
/**
 * 模板 C：天象事件详情块（未来 / 历史共用，分支渲染）
 *
 * 分支依据：event_type === 'historical' → 历史分支（文献记载/现代回推/史料辨析三层 + 时间不确定度）
 *          否则 → 未来分支（观测指南 + 参数总表）
 * 被两处复用：single-astro_event.php（CPT 单页）与旧短代码 [astro_event_detail]。
 * 变量：$ev（事件行）$related（关联行数组）$params（params_json 解码结果）
 *
 * ★ v1.2.0 变更：
 *   - 修掉 v1.1.0 的一处字面量缺陷：解析降级说明里写了 Markdown 的 `**未使用**`，
 *     在 HTML 里不会变成粗体，用户会看到两个星号。改为 <strong>。
 *   - 事件链接改走 kcj_astro_event_permalink()（不再硬编码 /sky/forecast/ 旧前缀）。
 *   - 补 obs_site（观测地）与 measurementTechnique（计算方法）两项如实展示。
 *   - 免责声明统一取 kcj_astro_disclaimer_text()，不再在此另写一份文案。
 *   - 结构化数据（Event / ScholarlyArticle）由 includes/rankmath.php 统一输出。
 *
 * 硬性约束：历史三层不下绝对定论；全站禁吉凶谶纬；**按 method 如实表述**（解析路径不得写「星历回推」）。
 */
if (!defined('ABSPATH')) { exit; }

$ev      = isset($ev)      && is_array($ev)      ? $ev      : array();
$related = isset($related) && is_array($related) ? $related : array();
$params  = isset($params)  && is_array($params)  ? $params  : array();

$is_history  = ((string) ($ev['event_type'] ?? '') === 'historical');
$method      = (string) ($ev['method'] ?? '');
$ephem       = (string) ($ev['ephemeris'] ?? '');
$is_analytic = ($method === 'analytic_meeus');
$types       = function_exists('kcj_astro_event_types') ? kcj_astro_event_types() : array();
$type_label  = isset($types[$ev['event_type'] ?? '']) ? $types[$ev['event_type']] : (string) ($ev['event_type'] ?? '');
?>
<div class="kcj-astro-detail">
  <h1 class="kcj-astro-title"><?php echo esc_html($ev['title'] ?? ''); ?></h1>

  <p class="kcj-astro-meta">
    类型：<?php echo esc_html($type_label); ?>
    <?php if (!empty($ev['event_time_bj'])): ?> ｜ 北京时间：<?php echo esc_html($ev['event_time_bj']); ?><?php endif; ?>
    <?php if (!empty($ev['time_uncertainty'])): ?> ｜ 时间不确定度：<?php echo esc_html($ev['time_uncertainty']); ?><?php endif; ?>
    <?php if (!empty($ev['obs_site'])): ?> ｜ 观测地：<?php echo esc_html($ev['obs_site']); ?><?php endif; ?>
  </p>

  <?php if ($method !== '' || !empty($ev['dt_model'])): ?>
  <p class="kcj-astro-meta kcj-astro-provenance">
    计算口径：<?php echo esc_html($is_analytic ? 'Meeus 解析式（截断级数，近似；未使用行星历表）' : ($method ?: '—')); ?>
    <?php if ($ephem !== ''): ?> ｜ 星历：<?php echo esc_html($ephem); ?><?php endif; ?>
    <?php if (!empty($ev['dt_model'])): ?> ｜ ΔT 模型：<?php echo esc_html($ev['dt_model']); ?><?php endif; ?>
  </p>
  <?php endif; ?>

  <!-- 天文参数总表 -->
  <?php if ($params): ?>
  <section class="kcj-astro-block">
    <h2>天文参数</h2>
    <table class="kcj-astro-params">
      <tbody>
      <?php foreach ($params as $k => $v): ?>
        <tr>
          <th><?php echo esc_html($k); ?></th>
          <td><?php echo esc_html(is_array($v) ? wp_json_encode($v, JSON_UNESCAPED_UNICODE) : (string) $v); ?></td>
        </tr>
      <?php endforeach; ?>
      </tbody>
    </table>
  </section>
  <?php endif; ?>

  <?php if (!$is_history): ?>
    <!-- 观测指南（仅未来天象） -->
    <?php if (!empty($ev['obs_guide'])): ?>
    <section class="kcj-astro-block">
      <h2>观测指南</h2>
      <p><?php echo esc_html(wp_strip_all_tags($ev['obs_guide'])); ?></p>
    </section>
    <?php endif; ?>
  <?php else: ?>
    <!-- 历史分支：三层区分（文献记载 / 现代回推 / 史料辨析） -->
    <?php if (!empty($ev['literature'])): ?>
    <section class="kcj-astro-block">
      <h2>一、文献记载</h2>
      <blockquote><?php echo esc_html(wp_strip_all_tags($ev['literature'])); ?></blockquote>
      <?php if (!empty($ev['source_ref'])): ?>
        <p class="kcj-astro-ref">出处：<?php echo esc_html($ev['source_ref']); ?></p>
      <?php endif; ?>
    </section>
    <?php endif; ?>

    <section class="kcj-astro-block">
      <h2>二、现代回推</h2>
      <?php if (!empty($ev['time_uncertainty'])): ?>
        <p>时间不确定度：<?php echo esc_html($ev['time_uncertainty']); ?>（仅标注区间，不给唯一时刻）</p>
      <?php endif; ?>
      <?php if (!empty($ev['dt_model'])): ?>
        <p>ΔT 模型：<?php echo esc_html($ev['dt_model']); ?></p>
      <?php endif; ?>
      <p class="kcj-astro-note">
        <?php if ($is_analytic): ?>
          本事件早于所选星历的覆盖区间，故<strong>未使用</strong>行星历表，改以 Meeus《Astronomical Algorithms》
          的截断级数（ch.25 太阳 / ch.47 月球 / ch.49 月相）作近似回推；
          结果受地球自转长期变化（ΔT）影响，已按不确定度区间交付，不作唯一结论。
        <?php else: ?>
          回推结果以现代星历反演（<?php echo esc_html($ephem !== '' ? $ephem : 'DE421'); ?>），
          受地球自转长期变化（ΔT）影响，时刻仅标注区间，不作唯一结论。
        <?php endif; ?>
      </p>
    </section>

    <?php if (!empty($ev['discussion'])): ?>
    <section class="kcj-astro-block">
      <h2>三、史料辨析</h2>
      <p><?php echo esc_html(wp_strip_all_tags($ev['discussion'])); ?></p>
    </section>
    <?php endif; ?>
  <?php endif; ?>

  <!-- 古今对照：直接内嵌关联模块，与 [astro_related_events] 同一套渲染 -->
  <?php
  if ($related) {
      echo kcj_astro_render_template('astro-related-events', array(
          'src'   => $ev,
          'items' => $related,
          'mode'  => 'auto',
      ));
  }
  ?>

  <p class="kcj-astro-disclaimer"><?php
    echo esc_html(function_exists('kcj_astro_disclaimer_text')
        ? kcj_astro_disclaimer_text()
        : '本页天象数据仅作天文参考，不涉及星占、谶纬、吉凶解读。');
  ?></p>
</div>
