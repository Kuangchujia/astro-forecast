<?php
/**
 * 模板 C：历史上今日天象（v2.0.0）
 *
 * 变量（由 kcj_astro_render_template 提供）：
 *   $mmdd      'MM-DD'
 *   $mon $day  月、日（数字）
 *   $types     本次要展示的 event_type 数组
 *   $type_cn   规范类型 → 中文名
 *   $rows      同月同日的条目（按 jd_core 倒序 = 由近及远）。
 *              ★ 本栏**不按 publish_status 过滤**：历史数据是「数据集」（存 0、不建详情页），
 *              故空态文案里不得出现「已发布」二字（会误导成「没发布才看不到」）。
 *   $coverage  array( event_type => 该类型在回溯段内的总条目数 )  ← 用来区分「没录」与「没有」
 *   $from $before  回溯段 [from, before)
 *   $nav       「前后几天」跳转（array of array(md,label,url)）
 *   $report    是否给下载按钮
 *
 * ★ 口径纪律（本模块的红线）：
 *   本页展示的是**依星历回算的历史天象**，不是史料记载的抄录。二者不能混：
 *   页面上「现代回算」四个字必须出现，且不得写成「史载」「古书云」（那属史料型条目，
 *   走 event_type='historical' 的另一条线，须逐字核录出处后才上前台）。
 */
if (!defined('ABSPATH')) { exit; }
$rows     = (isset($rows) && is_array($rows)) ? $rows : array();
$coverage = (isset($coverage) && is_array($coverage)) ? $coverage : array();
$type_cn  = (isset($type_cn) && is_array($type_cn)) ? $type_cn : array();
$types    = (isset($types) && is_array($types)) ? $types : array();
$from     = isset($from) ? (int) $from : 1900;
$before   = isset($before) ? (int) $before : 0;
$report   = !empty($report);
$mmdd     = isset($mmdd) ? (string) $mmdd : '';
$mon      = isset($mon) ? (int) $mon : 0;
$day      = isset($day) ? (int) $day : 0;
$nav      = (isset($nav) && is_array($nav)) ? $nav : array();

// 分类计数
$by_type = array();
foreach ($rows as $r) {
    $t = isset($r['event_type']) ? (string) $r['event_type'] : '';
    $by_type[$t] = (isset($by_type[$t]) ? $by_type[$t] : 0) + 1;
}
?>
<div class="kcj-astro-history">
  <p class="kcj-astro-intro">
    历史上 <?php echo esc_html($mmdd); ?> 这一天（<?php echo esc_html($mon); ?> 月 <?php echo esc_html($day); ?> 日）
    发生过的天象，由<strong>星历回算</strong>（非史料抄录），按时间由近及远排列。
    回溯段：<?php echo esc_html($from); ?> — <?php echo esc_html($before); ?> 年。
    星历 DE421 覆盖 1899-07-28 至 2053-10-08；段内<strong>月食、流星雨极大、行星天象
    均为自算</strong>（月食＝几何求根；流星雨＝太阳 J2000 黄经达该群约定 λ☉ 之时，λ☉ 照录
    IMO／RASC；行星天象＝黄经求根），<strong>日食照录</strong> NASA GSFC 目录。
  </p>

  <?php if (!empty($nav)): ?>
    <p class="kcj-astro-history-nav">
      <span class="kcj-astro-nav-label">换个日子看：</span>
      <?php foreach ($nav as $n): ?>
        <?php if (empty($n['url']) || empty($n['label'])) { continue; } ?>
        <a class="kcj-astro-nav-a"
           href="<?php echo esc_url($n['url']); ?>"><?php echo esc_html($n['label']); ?></a>
      <?php endforeach; ?>
    </p>
  <?php endif; ?>

  <?php if (!$rows): ?>
    <p class="kcj-astro-nodata"><?php
      // ★ v2.2.1：措辞改准。本栏自 v2.2.0 起**不按 publish_status 过滤**（历史数据以
      //   publish_status=0 入库，见 make_datasets.py 的分层裁定），所以原文案里那句
      //   「暂无**已发布**的天象条目」会把人带偏 —— 读者会以为「是没发布才看不到」，
      //   而真实原因只有两种：**数据未导入** 或 **这一天确实没有**（下面用覆盖度逐族区分）。
      echo esc_html('回溯段（' . $from . '—' . $before . ' 年）内，'
        . $mmdd . ' 这一天暂无天象条目。');
    ?></p>
    <ul class="kcj-astro-nodata kcj-astro-coverage">
      <?php foreach ($types as $t): ?>
        <?php $n = isset($coverage[$t]) ? (int) $coverage[$t] : 0; ?>
        <li>
          <?php echo esc_html(isset($type_cn[$t]) ? $type_cn[$t] : $t); ?>：
          <?php if ($n > 0): ?>
            回溯段内共收录 <strong><?php echo esc_html($n); ?></strong> 条，但都不在这一天
            ⇒ 这一天确实没有。
          <?php else: ?>
            回溯段内<strong>一条都没收录</strong> ⇒ 属<strong>未录入</strong>，不能据此说这一天没有。
          <?php endif; ?>
        </li>
      <?php endforeach; ?>
    </ul>
  <?php else: ?>
    <?php
    // ── 成组：**同一天里同名条目过多时，折成「年份清单」** ──────────────────
    // 日期锚定型天象（流星雨极大、行星合/冲）在同一「月-日」上**历年都会重现**，
    // 一次就是几十甚至上百条（英仙座极大落在 8/12，回溯段内 126 年 126 条）。
    // 逐条列卡片会把页面刷爆；而这类条目的信息量恰恰集中在两处：
    //   「哪些年出现过」与「最近一次什么样」。
    // ⇒ 规则（**数据驱动、与族无关**，免得以后加族又要改这一段）：
    //     组名 = 把标题末尾的**日期形括号**「（YYYY-MM-DD）」剥掉（实现见
    //            `kcj_astro_history_group_key()`，抽成函数是为了可单测）；
    //     组内 ≥ GROUP_MIN 条 ⇒ 折行，否则逐条。
    //     月食一天最多 4 条（实测 288 条 / 133 天），因此永远走「逐条」这一支，明细不丢。
    $GROUP_MIN = 6;
    $groups    = array();
    foreach ($rows as $r) {
        $key = kcj_astro_history_group_key(isset($r['title']) ? $r['title'] : '');
        if (!isset($groups[$key])) { $groups[$key] = array(); }
        $groups[$key][] = $r;
    }

    // 年份清单的**紧凑化**：连续 ≥4 年折成「A—B」，免得 126 个年份铺满三屏。
    $years_txt = function ($g) {
        $ys = array();
        foreach ($g as $r) {
            $t = isset($r['event_time_bj']) ? (string) $r['event_time_bj'] : '';
            if ($t !== '') { $ys[] = (int) substr($t, 0, 4); }
        }
        sort($ys);
        $out = array();
        $i   = 0;
        $n   = count($ys);
        while ($i < $n) {
            $j = $i;
            while ($j + 1 < $n && $ys[$j + 1] === $ys[$j] + 1) { $j++; }
            if ($j - $i + 1 >= 4) {
                $out[] = $ys[$i] . '—' . $ys[$j];
            } else {
                for ($k = $i; $k <= $j; $k++) { $out[] = (string) $ys[$k]; }
            }
            $i = $j + 1;
        }
        return implode('、', $out);
    };

    // 单条条目的**内容体**（不含 <li>；调用处负责包 <li>）。
    // $with_title=false 用于「折行组里最近一次」—— 组名已经在上一行显示了，不重复。
    $item_body = function ($r, $with_title = true) use ($type_cn) {
        $t    = isset($r['event_type']) ? (string) $r['event_type'] : '';
        $time = isset($r['event_time_bj']) ? (string) $r['event_time_bj'] : '';
        $year = ($time !== '') ? substr($time, 0, 4) : '';
        $rest = ($time !== '') ? substr($time, 5, 11) : '';
        $tit  = isset($r['title']) ? (string) $r['title'] : '';
        $summ = isset($r['summary']) ? (string) $r['summary'] : '';
        $unc  = isset($r['time_uncertainty']) ? (string) $r['time_uncertainty'] : '';
        $meth = isset($r['method']) ? (string) $r['method'] : '';
        $lit  = isset($r['literature']) ? trim((string) $r['literature']) : '';
        $disc = isset($r['discussion']) ? trim((string) $r['discussion']) : '';
        $h    = '<span class="kcj-astro-history-year">' . esc_html($year) . '</span>';
        $h   .= '<span class="kcj-astro-history-type">'
              . esc_html(isset($type_cn[$t]) ? $type_cn[$t] : $t) . '</span>';
        if ($with_title && $tit !== '') {
            $h .= '<strong class="kcj-astro-history-title">' . esc_html($tit) . '</strong>';
        }
        if ($rest !== '') {
            $h .= '<span class="kcj-astro-time">' . esc_html($rest) . '（北京时）</span>';
        }
        if ($summ !== '') {
            $h .= '<p class="kcj-astro-history-sum">' . esc_html(wp_strip_all_tags($summ)) . '</p>';
        }
        if ($unc !== '') {
            $h .= '<p class="kcj-astro-note">时刻不确定度：' . esc_html($unc) . '</p>';
        }
        if ($lit !== '') {
            $h .= '<p class="kcj-astro-history-lit"><span class="kcj-astro-tag">文献记载</span>'
                . esc_html(wp_strip_all_tags($lit)) . '</p>';
        }
        if ($disc !== '') {
            $h .= '<p class="kcj-astro-history-disc"><span class="kcj-astro-tag">史料辨析</span>'
                . esc_html(wp_strip_all_tags($disc)) . '</p>';
        }
        $h .= '<p class="kcj-astro-note">口径：现代回算（'
            . esc_html($meth !== '' ? $meth : '—') . '）</p>';
        return $h;
    };

    $n_group = 0;
    foreach ($groups as $g) {
        if (count($g) >= $GROUP_MIN) { $n_group++; }
    }
    ?>
    <p class="kcj-astro-meta">
      共 <strong><?php echo esc_html(count($rows)); ?></strong> 条
      <?php
      $bits = array();
      foreach ($by_type as $t => $n) {
          $bits[] = (isset($type_cn[$t]) ? $type_cn[$t] : $t) . ' ' . $n . ' 条';
      }
      if ($bits) { echo '（' . esc_html(implode('，', $bits)) . '）'; }
      ?>
    </p>
    <?php if ($n_group > 0): ?>
      <p class="kcj-astro-note">其中 <strong><?php echo esc_html($n_group); ?></strong>
        组是<strong>历年重现</strong>的同名天象（如流星雨极大），已折成「年份清单」：
        年份行为该组在回溯段内出现过的全部年份（连续 4 年以上折成区间），
        另附<strong>最近一次</strong>的完整明细；其余年份的逐条数据见下方下载。</p>
    <?php endif; ?>

    <ol class="kcj-astro-history-list">
      <?php foreach ($groups as $gname => $g): ?>
        <?php if (count($g) >= $GROUP_MIN): ?>
          <?php $g0 = $g[0]; ?>
          <?php $gt = isset($g0['event_type']) ? (string) $g0['event_type'] : ''; ?>
          <li class="kcj-astro-history-item kcj-astro-history-group">
            <div class="kcj-astro-group-head">
              <span class="kcj-astro-history-type"><?php
                echo esc_html(isset($type_cn[$gt]) ? $type_cn[$gt] : $gt); ?></span>
              <strong class="kcj-astro-history-title"><?php echo esc_html($gname); ?></strong>
              <span class="kcj-astro-count">共 <?php echo esc_html(count($g)); ?> 次</span>
            </div>
            <p class="kcj-astro-years"><?php echo esc_html($years_txt($g)); ?></p>
            <div class="kcj-astro-group-latest">
              <p class="kcj-astro-note"><span class="kcj-astro-tag">最近一次</span>
                <?php echo esc_html('（该组 ' . count($g) . ' 条中的最新一条）'); ?></p>
              <?php echo $item_body($g0, false); // phpcs:ignore WordPress.Security.EscapeOutput -- 闭包内已逐字段转义 ?>
            </div>
          </li>
        <?php else: ?>
          <?php foreach ($g as $r): ?>
            <li class="kcj-astro-history-item"><?php
              echo $item_body($r); // phpcs:ignore WordPress.Security.EscapeOutput -- 闭包内已逐字段转义
            ?></li>
          <?php endforeach; ?>
        <?php endif; ?>
      <?php endforeach; ?>
    </ol>


    <?php if ($report): ?>
    <?php
    // 下载数据：只喂必要字段，且 JSON 单行、& 与尖括号全部转成 \uXXXX（见 astro-today.php 的说明）
    $dump = array();
    foreach ($rows as $r) {
        $t = isset($r['event_type']) ? (string) $r['event_type'] : '';
        $dump[] = array(
            'y'     => (isset($r['event_time_bj']) ? substr((string) $r['event_time_bj'], 0, 4) : ''),
            't'     => $t,
            'tcn'   => (isset($type_cn[$t]) ? $type_cn[$t] : $t),
            'time'  => (isset($r['event_time_bj']) ? (string) $r['event_time_bj'] : ''),
            'title' => (isset($r['title']) ? (string) $r['title'] : ''),
            'sum'   => (isset($r['summary']) ? wp_strip_all_tags((string) $r['summary']) : ''),
            'unc'   => (isset($r['time_uncertainty']) ? (string) $r['time_uncertainty'] : ''),
            'meth'  => (isset($r['method']) ? (string) $r['method'] : ''),
        );
    }
    $json = wp_json_encode(array(
        'mmdd'   => $mmdd,
        'from'   => $from,
        'before' => $before,
        'items'  => $dump,
    ), JSON_UNESCAPED_UNICODE | JSON_HEX_AMP | JSON_HEX_TAG | JSON_HEX_APOS | JSON_HEX_QUOT);
    if ($json === false) { $json = '{}'; }
    ?>
    <div class="kcj-astro-dl">
      <span class="kcj-astro-dl-label">本页数据可留档：</span>
      <button type="button" class="kcj-astro-dl-md" data-kcj-dl="md">下载 Markdown</button>
      <button type="button" class="kcj-astro-dl-pr" data-kcj-dl="print">打印 / 存为 PDF</button>
    </div>
    <script type="application/json" class="kcj-astro-history-json"><?php echo $json; // phpcs:ignore WordPress.Security.EscapeOutput -- 已 JSON 转义 ?></script>
    <?php endif; ?>
  <?php endif; ?>

  <p class="kcj-astro-disclaimer"><?php
    echo esc_html(function_exists('kcj_astro_disclaimer_text')
        ? kcj_astro_disclaimer_text()
        : '天象数据基于 NASA JPL DE421 星历计算；仅作天文参考，不涉及星占、谶纬、吉凶解读。');
  ?></p>
</div>
