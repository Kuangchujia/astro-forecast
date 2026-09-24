<?php
/**
 * 模板 D：月 / 季 / 年度天象报告（v2.0.0）
 *
 * 变量：
 *   $period $period_cn $range(array start/end) $rows $type_cn $title $download $site $generated
 *
 * 两种出口：
 *   ① 页面表格（服务端渲染，无 JS 也完整可读）；
 *   ② **页面内即时生成并下载** Markdown，或直接打印成 PDF。
 *      期间条目由 PHP 序列化进本页，前端只做文本拼装 —— **不做任何天文计算**。
 *      （选这条路的原因：本站 REST 凭据不可用时无法上传文件到媒体库，
 *        页面内生成是唯一不依赖任何后端写权限的「可下载」实现。）
 *
 * 脚本纪律：**不出现裸与号字符**（逻辑与一律改嵌套 if），JSON 单行且 & < > 转 \uXXXX。
 */
if (!defined('ABSPATH')) { exit; }
$rows      = (isset($rows) && is_array($rows)) ? $rows : array();
$type_cn   = (isset($type_cn) && is_array($type_cn)) ? $type_cn : array();
$range     = (isset($range) && is_array($range)) ? $range : array('start' => '', 'end' => '');
$period_cn = isset($period_cn) ? (string) $period_cn : '';
$period    = isset($period) ? (string) $period : 'month';
$title     = isset($title) ? trim((string) $title) : '';
$download  = !empty($download);
$site      = isset($site) ? (string) $site : '';
$generated = isset($generated) ? (string) $generated : '';
if ($title === '') {
    $title = $period_cn . '天象报告';
}

// 按年月分组，便于阅读与打印（也便于读者按「哪个月有多少」快速定位）
$by_month = array();
foreach ($rows as $r) {
    $t = isset($r['event_time_bj']) ? substr((string) $r['event_time_bj'], 0, 7) : '—';
    if (!isset($by_month[$t])) { $by_month[$t] = array(); }
    $by_month[$t][] = $r;
}

// ── 期间切换条（v2.2.0 / F51）────────────────────────────────────────────
// 为什么必须加：本模板此前**没有任何期间切换 UI**，整栏锁死在短代码写死的那一个期间上，
//   而需求是「月 / 季 / 年度汇总，可下载」—— 实际只达 1/3。
// 成法：**纯链接、零脚本**，与历史栏的 `?kcj_md=` 完全一致。
//   平台会对正文跑 wpautop（空行换块级标签）并替换某些窗口内的裸与号 ⇒ 内联脚本随时被拆断
//   （v1.3.0「老黄历线上失效」的真因）。用 <a href> 就没有这个问题，且每个期间都有独立 URL，
//   可直接分享、可被搜索引擎各自收录。
// ★ URL 拼接纪律：**不用 add_query_arg()**。它会带上当前请求的全部参数（含 `?kcj_period=`
//   自身与分页/预览串），在平台重写规则下可能产出重复参数；此处显式只拼 kcj_period 一项，
//   并按「保留 kcj_md（若当前在看某个历史日）」处理，行为可预测。
$kcj_keep = array();
if (isset($_GET['kcj_md'])) {
    $keep_md = sanitize_text_field(wp_unslash($_GET['kcj_md']));
    if (preg_match('/^\d{2}-\d{2}$/', $keep_md)) {
        $kcj_keep['kcj_md'] = $keep_md;
    }
}
$kcj_base = get_queried_object_id() ? get_permalink(get_queried_object_id()) : home_url('/');
$kcj_base = strtok((string) $kcj_base, '?');
if (!$kcj_base) {
    $kcj_base = home_url('/');
}
$kcj_periods = array(
    'month'   => '本月',
    'quarter' => '本季',
    'year'    => '本年',
    'next12'  => '未来 12 个月',
);
?>
<div class="kcj-astro-report" data-kcj-period="<?php echo esc_attr($period); ?>">
  <h3 class="kcj-astro-report-h3"><?php echo esc_html($title); ?></h3>

  <p class="kcj-astro-period-nav">
    <span class="kcj-astro-nav-label">换个期间看：</span>
    <?php foreach ($kcj_periods as $pk => $plabel) : ?>
      <?php
      $q = array('kcj_period' => $pk);
      foreach ($kcj_keep as $kk => $vv) {
          $q[$kk] = $vv;
      }
      // ★ v2.2.7（F52）：显式写明「这些链接属于**未来栏**」。
      //   本模板是被 [astro_hub] 嵌在第二栏里渲染的，而这些链接是普通 <a href>
      //   ⇒ 点一下整页重载，而 hub 的 radio 状态不保留 ⇒ 读者被丢回第一栏
      //   （「点本月/本季/本年都跳回今日天象」）。带上 kcj_tab 后 hub 才能在
      //   重载后把他的栏目开回来。★ 为什么不让 hub 去「猜」：本模板会保留 kcj_md
      //   （见上方 $kcj_keep），于是 URL 里两个参数都在、先后无从判断。
      //   ⚠ 本模板**独立使用**时（不在 hub 里）该参数是惰性的，无副作用。
      $q['kcj_tab'] = 'future';
      $href = $kcj_base . '?' . http_build_query($q);
      ?>
      <?php if ($pk === $period) : ?>
        <strong class="kcj-astro-period-cur"><?php echo esc_html($plabel); ?></strong>
      <?php else : ?>
        <a class="kcj-astro-nav-a" href="<?php echo esc_url($href); ?>"><?php echo esc_html($plabel); ?></a>
      <?php endif; ?>
    <?php endforeach; ?>
  </p>

  <p class="kcj-astro-meta">
    期间：<strong><?php echo esc_html($range['start'] ?? ''); ?></strong> 起，至
    <strong><?php echo esc_html($range['end'] ?? ''); ?></strong> 止（含首不含尾）
    ｜ 生成时间：<?php echo esc_html($generated); ?>（北京时）
    ｜ 条目数：<strong><?php echo esc_html(count($rows)); ?></strong>
    ｜ 全部时刻为北京时间（UTC+8）
  </p>

  <?php if (!$rows): ?>
    <p class="kcj-astro-nodata"><?php
      echo esc_html('本期间（' . ($range['start'] ?? '') . ' — ' . ($range['end'] ?? '')
        . '）暂无已发布的天象条目。可能是该期间确实没有达到收录门槛的天象，'
        . '也可能是数据尚未刷新 —— 本站条目由流水线离线预计算后导入，不是实时生成。');
    ?></p>
  <?php else: ?>
    <?php foreach ($by_month as $ym => $mrows): ?>
      <section class="kcj-astro-report-month">
        <h4><?php echo esc_html($ym); ?>（<?php echo esc_html(count($mrows)); ?> 条）</h4>
        <?php
        // ★ v2.3.0 修「类型列被挤成一字一行」（用户截图：「行星天象」竖排成四行）：
        //   成因 ＝ 表格比容器宽，浏览器按内容比例压缩各列，而中文可在任意字间断行，
        //   于是最窄的「类型」列被压到十几个像素。三处一起改才治本：
        //     ① colgroup 显式给「时间/类型」定宽（它们是定长或短词，不该被压）；
        //     ② 这两列 nowrap（见 CSS 的 .kcj-astro-td-*）；
        //     ③ 表格给 min-width，外层容器 overflow-x:auto ⇒ 宁可横向滚动，也不压列。
        //   ③ 是关键：没有它，①② 会被「表格必须塞进容器」这条约束重新压回去。
        ?>
        <div class="kcj-astro-tablewrap">
        <table class="kcj-astro-report-table">
          <colgroup>
            <col class="kcj-astro-col-time"><col class="kcj-astro-col-type">
            <col class="kcj-astro-col-what"><col class="kcj-astro-col-sum">
          </colgroup>
          <thead>
            <tr><th>时间（北京时）</th><th>类型</th><th>天象</th><th>说明</th></tr>
          </thead>
          <tbody>
          <?php foreach ($mrows as $r): ?>
            <?php
            $t    = isset($r['event_type']) ? (string) $r['event_type'] : '';
            $time = isset($r['event_time_bj']) ? (string) $r['event_time_bj'] : '';
            $summ = isset($r['summary']) ? wp_strip_all_tags((string) $r['summary']) : '';
            $link = function_exists('kcj_astro_event_permalink') ? kcj_astro_event_permalink($r) : '';
            ?>
            <tr>
              <td class="kcj-astro-td-time"><?php echo esc_html($time); ?></td>
              <td class="kcj-astro-td-type"><?php echo esc_html(isset($type_cn[$t]) ? $type_cn[$t] : $t); ?></td>
              <td class="kcj-astro-td-what">
                <?php if (!empty($link)): ?>
                  <a href="<?php echo esc_url($link); ?>"><?php echo esc_html(isset($r['title']) ? (string) $r['title'] : ''); ?></a>
                <?php else: ?>
                  <?php echo esc_html(isset($r['title']) ? (string) $r['title'] : ''); ?>
                <?php endif; ?>
              </td>
              <td class="kcj-astro-td-sum"><?php echo esc_html($summ); ?></td>
            </tr>
          <?php endforeach; ?>
          </tbody>
        </table>
        </div>
      </section>
    <?php endforeach; ?>

    <p class="kcj-astro-note">
      口径：条目时刻为地心量（与观测地无关）；具体某地的可见情况（地平高度、初亏复圆时刻）
      须按观测地另算，本报告不作可见性判断。
    </p>

    <?php if ($download): ?>
    <?php
    $dump = array();
    foreach ($rows as $r) {
        $t = isset($r['event_type']) ? (string) $r['event_type'] : '';
        $dump[] = array(
            'time'  => (isset($r['event_time_bj']) ? (string) $r['event_time_bj'] : ''),
            't'     => $t,
            'tcn'   => (isset($type_cn[$t]) ? $type_cn[$t] : $t),
            'title' => (isset($r['title']) ? (string) $r['title'] : ''),
            'sum'   => (isset($r['summary']) ? wp_strip_all_tags((string) $r['summary']) : ''),
            'meth'  => (isset($r['method']) ? (string) $r['method'] : ''),
        );
    }
    $json = wp_json_encode(array(
        'title'     => $title,
        'period'    => $period,
        'start'     => $range['start'] ?? '',
        'end'       => $range['end'] ?? '',
        'site'      => $site,
        'generated' => $generated,
        'items'     => $dump,
    ), JSON_UNESCAPED_UNICODE | JSON_HEX_AMP | JSON_HEX_TAG | JSON_HEX_APOS | JSON_HEX_QUOT);
    if ($json === false) { $json = '{}'; }
    ?>
    <div class="kcj-astro-dl">
      <span class="kcj-astro-dl-label">本报告可下载留档：</span>
      <button type="button" class="kcj-astro-dl-md" data-kcj-dl="md">下载 Markdown</button>
      <button type="button" class="kcj-astro-dl-csv" data-kcj-dl="csv">下载 CSV</button>
      <button type="button" class="kcj-astro-dl-pr" data-kcj-dl="print">打印 / 存为 PDF</button>
    </div>
    <script type="application/json" class="kcj-astro-report-json"><?php echo $json; // phpcs:ignore WordPress.Security.EscapeOutput -- 已 JSON 转义 ?></script>
    <?php endif; ?>
  <?php endif; ?>

  <p class="kcj-astro-disclaimer"><?php
    echo esc_html(function_exists('kcj_astro_disclaimer_text')
        ? kcj_astro_disclaimer_text()
        : '天象数据基于 NASA JPL DE421 星历计算；仅作天文参考，不涉及星占、谶纬、吉凶解读。');
  ?></p>
</div>
