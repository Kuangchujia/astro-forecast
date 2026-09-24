<?php
/**
 * 天象预告「三栏目」外壳（v2.0.0；v2.2.7 加激活态）
 *
 * 变量（由 includes/shortcodes.php 的 [astro_hub] 传入）
 *   $sections  array  每项 ['key','title','sub','html']；html 是子短代码渲染好的**安全 HTML**
 *   $tabs      bool   true = 页内切换；false = 三栏目纵向平铺
 *   $active_i  int    **重载后该打开哪一栏**的下标（v2.2.7 / F52）；缺省 0
 *   $uniq      string 页面内唯一后缀（同一页放两个 [astro_hub] 时防止 radio 串扰）
 *
 * ★ 本模板**不含任何脚本** —— 切换全靠 CSS（radio + label）。
 *   理由见 shortcodes.php 里 [astro_hub] 的注释：平台对正文的后处理会拆断内联脚本。
 *   ⚠ 这一条**不要因为「想省掉一次整页重载」而破例**：本页每一栏的内容都是
 *     **服务端按 URL 参数渲染**的（换期间要重查表、换日子要重查表），
 *     用脚本拦掉跳转并不能换出内容，只会让地址栏与页面内容不一致。
 *     真正的修法是**让重载后停在原栏**（本文件的 $active_i），不是不重载。
 * ★ 三个栏目的内容**全部在 DOM 里**，只以 CSS 隐藏 ⇒ 搜索引擎抓得到每个分区。
 */
if (!defined('ABSPATH')) {
    exit;
}
$hid = 'kcj-astro-hub-' . preg_replace('/[^a-z0-9]/i', '', (string) $uniq);
if ($hid === 'kcj-astro-hub-') {
    $hid = 'kcj-astro-hub-x';
}
// ★ v2.2.7（F52）：把「打开哪一栏」从**写死的第 0 栏**改为**由 URL 决定**。
//   此前是 `($i === 0) ? ' checked="checked"' : ''` ⇒ 栏内任何 <a href>
//   （未来栏换期间、历史栏换日子）都会整页重载，重载后 radio 复位到第 0 栏，
//   读者刚点的那一下看起来「没生效」（数据其实已换，只是被藏起来了）。
//   缺省与越界一律落回 0：越界时宁可开第一栏，也不能一个都不 checked
//   —— 那样**三个栏目会同时显示**（CSS 靠 :checked 选栏），比跳回第一栏更难看。
$active_i = isset($active_i) ? (int) $active_i : 0;
if ($active_i < 0 || $active_i >= count($sections)) {
    $active_i = 0;
}

// ★ v2.3.0（F52 收口）：「清除视图参数」规范链接。
//   第十八轮定谳：用户报的「一打开就是历史上今天天象」**不是渲染缺陷**，而是
//   **URL 污染** —— 栏内跳转链接按设计自带 `kcj_md` / `kcj_tab`，于是「曾进过历史栏」
//   被写进地址栏；那个 URL 被收藏/分享后再打开，必然落历史栏（设计使然）。
//   真正缺的是：**读者没有一条「回到干净视图」的路**。本链接补上它。
//   ⚠ 为什么不做 fragment（`#tab-past`）重设计：三栏内容**本来就全在 DOM 里**、
//     `:checked ~` 已能在重载后停回原栏（v2.2.7 的 $active_i）。改 fragment 只是让地址栏
//     好看一点，却要动「纯 CSS 切换 + 零脚本」这条被平台逼出来的纪律（内联脚本会被拆断），
//     收益远小于风险。轻量补一条规范链接即可。
//   ⚠ 不用 add_query_arg() 反向构造：那会带上当前请求的全部参数（含第三方 utm 等）。
//     从**永久链接**出发、只摘掉 kcj_* 参数，才是干净的。
$kcj_clean_url = '';
$kcj_stale     = array();
foreach (array_keys($_GET) as $k) {   // phpcs:ignore WordPress.Security.NonceVerification.Recommended
    if (strpos((string) $k, 'kcj_') === 0) {
        $kcj_stale[] = (string) $k;
    }
}
if ($kcj_stale && function_exists('is_singular') && is_singular()) {
    $kcj_perm = get_permalink(get_queried_object_id());
    if ($kcj_perm) {
        $kcj_clean_url = remove_query_arg($kcj_stale, $kcj_perm);
    }
}
?>
<div class="kcj-astro-hub"<?php echo $tabs ? ' data-tabs="1"' : ''; ?>
     data-kcj-active="<?php echo (int) $active_i; ?>">

<?php if ($tabs) : ?>
<?php foreach ($sections as $i => $s) : ?>
  <input class="kcj-astro-hub-radio" type="radio"
         name="<?php echo esc_attr($hid); ?>-tab"
         id="<?php echo esc_attr($hid . '-t' . $i); ?>"
         data-i="<?php echo (int) $i; ?>"<?php echo ($i === $active_i) ? ' checked="checked"' : ''; ?>>
<?php endforeach; ?>
<?php endif; ?>

  <div class="kcj-astro-hub-bar">
<?php foreach ($sections as $i => $s) : ?>
<?php if ($tabs) : ?>
    <label class="kcj-astro-hub-tab" data-i="<?php echo (int) $i; ?>"
           for="<?php echo esc_attr($hid . '-t' . $i); ?>">
      <span class="kcj-astro-hub-tab-n"><?php echo (int) ($i + 1); ?></span>
      <span class="kcj-astro-hub-tab-t"><?php echo esc_html($s['title']); ?></span>
      <span class="kcj-astro-hub-tab-s"><?php echo esc_html($s['sub']); ?></span>
    </label>
<?php else : ?>
    <span class="kcj-astro-hub-tab kcj-astro-hub-tab-static" data-i="<?php echo (int) $i; ?>">
      <span class="kcj-astro-hub-tab-n"><?php echo (int) ($i + 1); ?></span>
      <span class="kcj-astro-hub-tab-t"><?php echo esc_html($s['title']); ?></span>
      <span class="kcj-astro-hub-tab-s"><?php echo esc_html($s['sub']); ?></span>
    </span>
<?php endif; ?>
<?php endforeach; ?>
  </div>

  <div class="kcj-astro-hub-panes">
<?php foreach ($sections as $i => $s) : ?>
    <section class="kcj-astro-hub-pane kcj-astro-hub-pane-<?php echo esc_attr($s['key']); ?>"
             id="<?php echo esc_attr($hid . '-p' . $i); ?>"
             data-i="<?php echo (int) $i; ?>"
             data-kcj-section="<?php echo esc_attr($s['key']); ?>">
      <?php
      // ★ v2.3.0：这一行原本是**可见**的 <h3>，于是「今日天象」在页面上出现三次
      //   （页面自身的标题、本外壳的栏目标头、以及这里）—— 用户报的「重复的内容过多」。
      //   栏目标头已经把栏名写在读者眼前了，这里再写一遍纯属重复。
      //   ⇒ 改成**视觉隐藏**（`.kcj-astro-sr`）：不进视觉，但保住文档大纲与读屏语义
      //     —— 「这一段内容叫什么」不能因为好看就丢掉。
      ?>
      <h3 class="kcj-astro-hub-pane-h kcj-astro-sr"><?php echo esc_html($s['title']); ?></h3>
      <?php
      // $s['html'] 由各子短代码的模板产出，其中每一处输出都已转义（见各模板）。
      // 此处不再二次转义，否则会把子模板的标签显示成文本。
      echo $s['html'];
      ?>
    </section>
<?php endforeach; ?>
  </div>

<?php if ($kcj_clean_url !== '') : ?>
  <p class="kcj-astro-hub-clean">
    <a href="<?php echo esc_url($kcj_clean_url); ?>">回到「今日天象」（清除地址栏里的视图参数）</a>
    <span class="kcj-astro-note">当前地址带有视图参数（<?php echo esc_html(implode('、', $kcj_stale)); ?>），
      所以打开时停在你上次看的栏目。这条链接回到不带参数的干净视图。</span>
  </p>
<?php endif; ?>

</div>
