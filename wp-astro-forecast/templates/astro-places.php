<?php
/**
 * 模板 B：观测地总览页（v2.3.6）
 *
 * 用途：把原先挤在首页里的「省份 Tab ＋ 城市网格」整块搬到这里。
 * 变量（由 kcj_astro_render_template extract 提供）：
 *   $groups $covered $places $cur $cur_cn $cur_prov $flat_fallback
 *   $hub_url $store_key $anchor_count $date_str
 *
 * ★ 本模板**零脚本**（除一个 inert 的 JSON 载荷）：
 *   省份 Tab 切省是纯 CSS（radio + label），与 [astro_hub] 三栏目同一套纪律 ——
 *   平台对正文的后处理会拆断内联脚本（v1.3.0「老黄历线上失效」的真因），不可破例。
 *   网格点击由 assets/astro-place.js 绑定（外置资源，不经正文后处理）。
 *
 * ★ 无 JS 降级：下面的 <select> **平铺可见**（不带 .kcj-astro-sr），
 *   选中后点「查看」按钮提交 —— 纯原生表单。故本页在无脚本环境下**依然完整可用**。
 *
 * ★ 换城不换 URL：城市选择不进地址栏（与 v2.3.3 同纪律）。选择结果写 localStorage，
 *   由首页脚本在「定位之前」读取 —— 手动选择优先于自动定位（既有的第③条硬约束）。
 */
if (!defined('ABSPATH')) { exit; }
$groups  = (isset($groups) && is_array($groups)) ? $groups : array();
$covered = (isset($covered) && is_array($covered)) ? $covered : array();
$places  = (isset($places) && is_array($places)) ? $places : array();
$cur     = isset($cur) ? (string) $cur : '';
$cur_cn  = isset($cur_cn) ? (string) $cur_cn : '';
$cur_prov = isset($cur_prov) ? (string) $cur_prov : '';
$flat_fallback = !empty($flat_fallback);
$hub_url = isset($hub_url) ? (string) $hub_url : '';
$store_key = isset($store_key) ? (string) $store_key : 'kcj_astro_place';
$anchor_count = isset($anchor_count) ? (int) $anchor_count : 0;
$grid_id = preg_replace('/[^a-z0-9]/i', '', (string) (isset($date_str) ? $date_str : ''));

// 只保留「当天真有数据」的省
$live = array();
foreach ($groups as $pad => $g) {
    $opts = array();
    foreach ($g['items'] as $k => $cn2) {
        if (isset($covered[$k])) {
            $opts[$k] = $cn2;
        }
    }
    if ($opts) {
        $live[(string) $pad] = array('name' => (string) $g['name'], 'items' => $opts);
    }
}
$open_pad = '';
if ($cur_prov !== '' && isset($live[$cur_prov])) {
    $open_pad = $cur_prov;
} elseif ($live) {
    $keys_live = array_keys($live);
    $open_pad  = (string) $keys_live[0];
}
$n_live = 0;
foreach ($live as $g2) {
    $n_live += count($g2['items']);
}
?>
<div class="kcj-astro-places-hub"
     data-kcj-place-cur="<?php echo esc_attr($cur); ?>"
     data-kcj-store="<?php echo esc_attr($store_key); ?>"
     data-kcj-hub-url="<?php echo esc_url($hub_url); ?>">

  <p class="kcj-astro-places-lead"><?php
    echo esc_html('下面列出全部预置观测地（共 ' . (int) $anchor_count . ' 个锚点），'
      . '按省分组。选中哪个，全站的日出日落、晨昏与月出月落就按哪个观测地显示。');
  ?></p>
  <p class="kcj-astro-places-now"><?php
    echo esc_html('当前观测地：' . $cur_cn);
  ?></p>

  <?php if ($flat_fallback): ?>
    <p class="kcj-astro-nodata"><?php
      echo esc_html('观测地目录或当天观测地数据暂不可读，只能以平铺列表列出当天可用的观测地。');
    ?></p>
  <?php else: ?>

  <div class="kcj-astro-place-grid">
    <?php $gi = 0; foreach ($live as $pad => $g): ?>
    <input class="kcj-astro-place-pradio" type="radio"
           name="kcj-place-p-<?php echo esc_attr($grid_id); ?>"
           id="kcj-place-p-<?php echo esc_attr($grid_id . '-' . $gi); ?>"
           data-gi="<?php echo (int) $gi; ?>"<?php echo ((string) $pad === $open_pad) ? ' checked="checked"' : ''; ?>>
    <?php $gi++; endforeach; ?>

    <div class="kcj-astro-place-tabs">
      <?php $gi = 0; foreach ($live as $pad => $g): ?>
      <label class="kcj-astro-place-tab" data-gi="<?php echo (int) $gi; ?>"
             for="kcj-place-p-<?php echo esc_attr($grid_id . '-' . $gi); ?>"><?php echo esc_html($g['name']); ?></label>
      <?php $gi++; endforeach; ?>
    </div>

    <div class="kcj-astro-place-panels">
      <?php $gi = 0; foreach ($live as $pad => $g): ?>
      <div class="kcj-astro-place-pane" data-gi="<?php echo (int) $gi; ?>">
        <?php foreach ($g['items'] as $k => $cn2): ?>
        <button type="button" class="kcj-astro-place-city"
                data-anchor="<?php echo esc_attr($k); ?>"
                aria-pressed="<?php echo ($k === $cur) ? 'true' : 'false'; ?>"><?php echo esc_html($cn2); ?></button>
        <?php endforeach; ?>
      </div>
      <?php $gi++; endforeach; ?>
    </div>
  </div>
  <?php endif; ?>

  <?php
  // ★ 平铺可见的 <select>：本页**无 JS 时的唯一选择器**，也是 JS 版「读者点的哪一格」的承载。
  //   它**不**承载数据渲染（那在首页），故不与 astro-today.php 的那只共享 —— 两只各司其职。
  ?>
  <form class="kcj-astro-places-form" method="get" action="<?php echo esc_url($hub_url); ?>">
    <label class="kcj-astro-place-label" for="kcj-hub-select-<?php echo esc_attr($grid_id); ?>">选择观测地</label>
    <select class="kcj-astro-place-select" id="kcj-hub-select-<?php echo esc_attr($grid_id); ?>"
            data-kcj-hub-select="1">
      <?php if ($flat_fallback): ?>
        <?php foreach ($places as $k => $v): ?>
        <option value="<?php echo esc_attr($k); ?>" data-anchor="<?php echo esc_attr($k); ?>"<?php echo ($k === $cur) ? ' selected' : ''; ?>><?php echo esc_html($v['cn']); ?></option>
        <?php endforeach; ?>
      <?php else: ?>
        <?php foreach ($live as $pad => $g): ?>
        <optgroup label="<?php echo esc_attr($g['name']); ?>">
          <?php foreach ($g['items'] as $k => $cn2): ?>
          <option value="<?php echo esc_attr($k); ?>" data-anchor="<?php echo esc_attr($k); ?>"<?php echo ($k === $cur) ? ' selected' : ''; ?>><?php echo esc_html($cn2); ?></option>
          <?php endforeach; ?>
        </optgroup>
        <?php endforeach; ?>
      <?php endif; ?>
    </select>
    <button type="submit" class="kcj-astro-place-view">查看</button>
    <?php if ($hub_url !== ''): ?>
    <a class="kcj-astro-places-back" href="<?php echo esc_url(home_url('/')); ?>">返回首页</a>
    <?php endif; ?>
  </form>

  <p class="kcj-astro-place-status" role="status" aria-live="polite"><?php
    echo esc_html('共 ' . (int) $n_live . ' 个观测地今日有数据。选中后本页会记下你的选择，'
      . '回首页即按它显示。');
  ?></p>
</div>
