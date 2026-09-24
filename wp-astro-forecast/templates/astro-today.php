<?php
/**
 * 模板 A：老黄历内嵌「今日天象」板块（v2.0.0：加观测地选择）
 * 数据源：wp_astro_daily.data_json（地心量）＋ wp_astro_daily_site（升落与晨昏，按观测地）
 * 前端只读，零实时计算。
 * 硬性约束：不含任何占星/吉凶解读；观测难度分级仅描述观测条件。
 *
 * 变量（由 kcj_astro_render_template extract 提供）：
 *   $date_str $observer $method $ephemeris $delta_t_sec $sun $moon $planets $xiu $special_event
 *   $places      array( city_key => 该城当日升落与晨昏 )   ← v2.0.0
 *   $place_mode  'off' | 'auto' | 'fixed'                 ← v2.0.0
 *   $place_fixed 固定城市键（place_mode == 'fixed' 时有值）
 *   （v2.3.6：切换链接由 kcj_astro_place_switch_link() 现算，不经变量传入）
 *   （免责声明不再从数据里取，统一调用 kcj_astro_disclaimer_text()，避免两处文案漂移）
 *
 * ★ 观测地口径（v2.0.0）：
 *   页面上与观测地有关的**只有**：日出/日落/昼长/民用·航海·天文三种晨昏/月出/月落。
 *   其余（黄经、赤纬、视星等、入宿、月相、地月距离）都是**地心量**，换观测地不会变 ——
 *   所以「切换观测地」只换那 8 组值，不做任何天文计算。
 *   切换所需的全部 38 城数据在**服务端一次查好**、序列化进本页（单行 JSON），
 *   前端切换时零请求、零计算。
 *
 * ★ v2.3.6 变更：**「省份 Tab ＋ 城市网格」整块移出本模板**（用户令：「这个界面太长了，不行！」）。
 *   本模板只留：当前观测地标签 ＋ 视觉隐藏的 <select> ＋「按我的位置」＋「切换观测地」小链接。
 *   网格改由 [astro_places_hub]（templates/astro-places.php）渲染，落在观测地总览页。
 *   ★ 为什么 <select> 仍留在这里、且必须留着：它是 apply()/describe()/无 JS 降级的公共支点
 *     （详见下方原注释），网格只是它的一个视觉面。移走它 = 移走数据支点，不动。
 *
 * ★ v1.1.0 变更：删除「值日星宿」。该字段既非太阳所在宿（二十八宿轮值另有独立周期），
 *   又属择日吉凶体系，触本模块「禁吉凶谶纬」红线，故不再输出（见 feasibility-review F8）。
 */
if (!defined('ABSPATH')) { exit; }
$sun     = isset($sun)     ? $sun     : array();
$moon    = isset($moon)    ? $moon    : array();
$planets = isset($planets) ? $planets : array();
$xiu     = isset($xiu)     ? $xiu     : array();
$obs     = isset($observer) ? $observer : array();
$method  = isset($method)  ? $method  : '';
$ephem   = isset($ephemeris) ? $ephemeris : '';
$dts     = isset($delta_t_sec) ? $delta_t_sec : '';
$places  = (isset($places) && is_array($places)) ? $places : array();
$pmode   = isset($place_mode) ? (string) $place_mode : 'off';
$pfixed  = isset($place_fixed) ? (string) $place_fixed : '';
// 默认观测地键由短代码经 kcj_astro_default_place() 传入（**不写死在这里**）
$pdef    = isset($place_default) && $place_default !== '' ? (string) $place_default : 'jieyang';
$cn      = array('mercury' => '水星', 'venus' => '金星', 'mars' => '火星',
                 'jupiter' => '木星', 'saturn' => '土星');

// 当前生效的观测地（服务端先按默认/固定值渲染；auto 模式下由脚本按 IP 改选）
$cur      = $pdef;
$cur_cn   = isset($obs['city']) ? (string) $obs['city'] : '揭阳';
if ($pmode === 'fixed' && isset($places[$pfixed])) {
    $cur    = $pfixed;
    $cur_cn = $places[$pfixed]['cn'];
} elseif ($pmode === 'auto' && $places) {
    // auto 模式的**服务端**起步值仍是默认城（揭阳）；若默认城不在数据里，
    // 取排序后的第一座，保证渲染出的数字与下面写的城市名一定是同一座。
    if (!isset($places[$cur])) {
        $keys = array_keys($places);
        $cur  = (string) $keys[0];
    }
    $cur_cn = $places[$cur]['cn'];
}
$P = isset($places[$cur]) ? $places[$cur] : null;

/** 取值助手：观测地表有值就用它，否则回落 data_json 里的地心测算值（并在页面注明口径） */
if (!function_exists('kcj_today_field')) {
    function kcj_today_field($P, $k, $fallback) {
        if (is_array($P)) {
            if ($k === 'tw_c' || $k === 'tw_n' || $k === 'tw_a') {
                return $P[$k];
            }
            if (array_key_exists($k, $P) && $P[$k] !== null && $P[$k] !== '') {
                return $P[$k];
            }
        }
        return $fallback;
    }
}
$f_sunrise = kcj_today_field($P, 'sunrise', $sun['sunrise_bj'] ?? null);
$f_sunset  = kcj_today_field($P, 'sunset',  $sun['sunset_bj'] ?? null);
$f_daylen  = kcj_today_field($P, 'daylen',  $sun['day_length_min'] ?? null);
$f_moonr   = kcj_today_field($P, 'moonrise', $moon['moonrise_bj'] ?? null);
$f_moons   = kcj_today_field($P, 'moonset',  $moon['moonset_bj'] ?? null);
$f_twc     = is_array($P) ? $P['tw_c'] : array($sun['twilight_civil']['begin'] ?? null,
                                               $sun['twilight_civil']['end'] ?? null);
$f_twn     = is_array($P) ? $P['tw_n'] : array($sun['twilight_nautical']['begin'] ?? null,
                                               $sun['twilight_nautical']['end'] ?? null);
$f_twa     = is_array($P) ? $P['tw_a'] : array($sun['twilight_astronomical']['begin'] ?? null,
                                               $sun['twilight_astronomical']['end'] ?? null);

/** 观测地表里「这一天的记录整片缺席」时，页面要如实说，而不是把空值当没有日出 */
$places_covered = ($P !== null);
?>
<?php
// ★ v2.3.0：标题去重（用户报「重复的内容过多」）。
//   同一页面里「今日天象」原本出现**三次**：页面自身的 H1/H2（在页面内容里，不归本插件管）、
//   [astro_hub] 的栏目标头、以及本模板这一行 `<h3>`。三次说的是同一件事。
//   ⇒ 本行**不再占用可见标题**：改成一个紧凑的「日期 ＋ 观测地」信息条；
//     同时保留一个**视觉隐藏**的 h3（`.kcj-astro-sr`）—— 它不进视觉，但保住
//     文档大纲与读屏语义（「这段内容叫什么」不能因为好看就丢掉）。
$hidden_title = '今日天象 · ' . (string) ($date_str ?? '') . ' · ' . $cur_cn;

// 观测地下拉：按「省 → 该省锚点」分组，服务端渲染 ⇒ **无 JS 也能选到任一预置观测地**。
//   目录读不到时回落成「库里当天有的锚点」平铺列表 —— 仍然完整可用，只是没有省市分组。
$groups = function_exists('kcj_astro_place_groups') ? kcj_astro_place_groups() : array();
$flat_fallback = false;
$covered = array();
foreach ($groups as $g) {
    foreach ($g['items'] as $k => $cn2) {
        if (isset($places[$k])) {
            $covered[$k] = true;
        }
    }
}
if (!$groups || !$covered) {
    $flat_fallback = true;
}
// ★ v2.3.3：当前城属于哪一省 —— 决定「城市网格默认打开哪一省的格子」。
//   不先算出来的话，网格会默认展开第一省（北京），而当前生效的却是揭阳/其它城
//   ⇒ 读者一进页面看到的格子里**没有**正在生效的那一格，等于「界面在说谎」。
//   这与 v2.3.0 修「下拉默认项与生效城不一致」是同一类错，故此处同办。
//   反查成本 O(省数) 且是纯内存遍历，不查库。
$cur_prov = '';
if (!$flat_fallback) {
    foreach ($groups as $pad => $g) {
        if (isset($g['items'][$cur])) {
            $cur_prov = (string) $pad;
            break;
        }
    }
}
?>
<div class="kcj-astro-today" itemscope itemtype="https://schema.org/WebPage"
     data-kcj-place-mode="<?php echo esc_attr($pmode); ?>"
     data-kcj-place-cur="<?php echo esc_attr($cur); ?>"
     data-kcj-catalog="<?php echo esc_url(KCJ_ASTRO_URL . 'assets/places-cn.json'); ?>"
     data-kcj-expect="<?php echo (int) (function_exists('kcj_astro_places_expected') ? kcj_astro_places_expected() : 0); ?>">
  <h3 class="kcj-astro-h3 kcj-astro-sr"><?php echo esc_html($hidden_title); ?></h3>

  <div class="kcj-astro-today-head">
    <span class="kcj-astro-today-date"><?php echo esc_html($date_str ?? ''); ?></span>
    <span class="kcj-astro-today-place" data-kcj-city-label><?php echo esc_html($cur_cn); ?></span>
  </div>

  <?php if ($pmode !== 'off'): ?>
  <div class="kcj-astro-place-bar">
    <div class="kcj-astro-place-row">
      <label class="kcj-astro-place-label" for="kcj-astro-place-<?php echo esc_attr($date_str ?? ''); ?>">观测地</label>
      <?php if (count($places) > 1): ?>
      <?php
      // ★★ v2.3.6：观测地从「省份 Tab ＋ 城市网格」**收回**成一个原生 <select>。
      //
      //   为什么收回（用户令，原话）：「这个界面太长了，不行！…… 首页首屏仅保留
      //     『当前选中城市』以及『按我的位置』按钮。将『两级联动省份标签+城市网格面板』
      //     完全移出首页，单独做成一个独立的 WordPress 页面。」
      //   实测依据：线上首页 HTML 205,161 字符，其中城市相关（340 个 <option>、
      //     34 个 radio、34 个 tab、35 个 pane、41,007 字符载荷 JSON）约 100 KB、占 49%
      //     ⇒ 首屏被这团「城市文本」压满，正文与学术关键词全被推到下面。
      //   网格与省份 Tab 未删，只是搬去了 templates/astro-places.php（[astro_places_hub]）。
      //
      //   为什么**不删** <select>（关键）：
      //     ① 它是 assets/astro-place.js 里 apply() 的唯一驱动（`sel.options[sel.selectedIndex]`）；
      //     ② 它是 describe() 的唯一输入（「按哪算的」那句话从它读）；
      //     ③ 它是**无 JS 时唯一的可用选择器** —— 服务端已渲染全部选项。
      //   ⇒ 网格点击（**在观测地总览页**）也不自己算，只替读者去动那边的 select，
      //     从而**复用全部既有逻辑、零新代码路径**，也不会出现「两套机制并存」。
      //   ⇒ 故此处 select 只做**视觉隐藏**（.kcj-astro-sr），**不得从 DOM 移除**。
      //
      //   为什么格子用 <button> 而不是 <a href>：
      //     换城**不换 URL**（数据已全部嵌在本页，换城纯改 DOM）。
      //     用 <a> 会把「切视图」误报成「导航」，且必须 preventDefault 才能避免重载
      //     —— 而一旦 preventDefault，无 JS 降级就同时失效。用 <button> 两个问题一起消失。
      ?>
      <select class="kcj-astro-place-select<?php echo $flat_fallback ? '' : ' kcj-astro-sr'; ?>"
              id="kcj-astro-place-<?php echo esc_attr($date_str ?? ''); ?>">
        <?php if ($flat_fallback): ?>
          <?php foreach ($places as $k => $v): ?>
          <option value="<?php echo esc_attr($k); ?>" data-anchor="<?php echo esc_attr($k); ?>"<?php echo ($k === $cur) ? ' selected' : ''; ?>><?php echo esc_html($v['cn']); ?></option>
          <?php endforeach; ?>
        <?php else: ?>
          <?php foreach ($groups as $pad => $g): ?>
            <?php
            // 只列「当天真的查到了数据」的锚点 —— 列了没数据的会让读者选到空值
            $opts = array();
            foreach ($g['items'] as $k => $cn2) {
                if (isset($covered[$k])) {
                    $opts[$k] = $cn2;
                }
            }
            if (!$opts) {
                continue;
            }
            ?>
          <optgroup label="<?php echo esc_attr($g['name']); ?>">
            <?php foreach ($opts as $k => $cn2): ?>
            <option value="<?php echo esc_attr($k); ?>" data-anchor="<?php echo esc_attr($k); ?>"<?php echo ($k === $cur) ? ' selected' : ''; ?>><?php echo esc_html($cn2); ?></option>
            <?php endforeach; ?>
          </optgroup>
          <?php endforeach; ?>
        <?php endif; ?>
      </select>
      <?php endif; ?>
      <button type="button" class="kcj-astro-place-auto">按我的位置</button>
      <?php
      // ★ v2.3.6：「切换观测地」小链接 —— 用户令原话「在首页的城市名字旁，放一个优雅的小链接：
      //   [切换观测地] 链接到该独立页」。放在「按我的位置」**之后**（同一 flex 行末），
      //   它才不会把默认拿焦点的 select/按钮挤开，视线顺序也是「就地选 → 换地」。
      //   目标 URL 由 kcj_astro_places_hub_url() 现算：先看选项、再找真挂了
      //   [astro_places_hub] 的页面，最后才退回 /observatories/。
      $switch = function_exists('kcj_astro_place_switch_link') ? kcj_astro_place_switch_link() : '';
      if ($switch !== '') {
          echo $switch;   // phpcs:ignore WordPress.Security.EscapeOutput -- 函数内已 esc_url
      }
      ?>
<?php /* 上面 ?><?php 之间的换行会被 PHP 吃掉，故换行写在注释后面 */ ?>

    </div>
    <p class="kcj-astro-place-status" role="status" aria-live="polite"><?php
      if ($pmode === 'auto') {
          echo esc_html('正在按访问位置选择最近的预置观测地…');
      } else {
          echo esc_html('已固定为' . $cur_cn);
      }
    ?></p>
  </div>
  <?php endif; ?>

  <?php if ($pmode !== 'off' && !$places_covered): ?>
  <p class="kcj-astro-nodata"><?php
    echo esc_html('观测地维度数据未覆盖 ' . ($date_str ?? '') . '（需导入 wp_astro_daily_site）。'
      . '下方日出/日落等仍按 data_json 的测算值显示，口径与观测地不一致，请以「未指定观测地」理解。');
  ?></p>
  <?php endif; ?>

  <?php
  // 口径行折进 <details>：这些是**溯源信息**（方法/星历/ΔT），应当可查、但不该在
  // 读者看天象时挤在最上面（用户报的「重复／杂乱」里有它一份）。
  // ★ 折起来不等于藏起来 —— 内容仍在 DOM 里，搜索与打印都拿得到，且默认展开态可被 CSS 改。
  ?>
  <details class="kcj-astro-spec">
    <summary>口径与方法</summary>
    <ul>
      <li>坐标口径：地心视位置（当日黄道/赤道）；升落与晨昏为<strong>站心</strong>（随观测地变化）。</li>
      <li>与观测地无关的量：黄经、赤纬、视星等、入宿、月相、地月距离 —— 均为地心量。</li>
      <li>方法：<?php echo esc_html($method ?: '—'); ?></li>
      <li>星历：<?php echo esc_html($ephem ?: '—'); ?></li>
      <?php if ($dts !== ''): ?><li>ΔT：<?php echo esc_html($dts); ?> s</li><?php endif; ?>
    </ul>
  </details>

  <div class="kcj-astro-grid">
    <!-- 太阳 -->
    <section class="kcj-astro-card">
      <h4>太阳</h4>
      <ul>
        <li>日出（北京时）：<span class="kcj-astro-v" data-kcj-f="sunrise"><?php echo esc_html($f_sunrise ?? '—'); ?></span></li>
        <li>日落（北京时）：<span class="kcj-astro-v" data-kcj-f="sunset"><?php echo esc_html($f_sunset ?? '—'); ?></span></li>
        <li>昼长：<span class="kcj-astro-v" data-kcj-f="daylen"><?php echo esc_html($f_daylen ?? '—'); ?></span> 分</li>
        <li>直射点纬度：<?php echo esc_html($sun['sub_solar_lat_deg'] ?? '—'); ?>°</li>
        <li>民用晨昏：<span class="kcj-astro-v" data-kcj-f="tw_c"><?php echo esc_html(($f_twc[0] ?? '—') . ' ~ ' . ($f_twc[1] ?? '—')); ?></span></li>
        <li>航海晨昏：<span class="kcj-astro-v" data-kcj-f="tw_n"><?php echo esc_html(($f_twn[0] ?? '—') . ' ~ ' . ($f_twn[1] ?? '—')); ?></span></li>
        <li>天文晨昏：<span class="kcj-astro-v" data-kcj-f="tw_a"><?php echo esc_html(($f_twa[0] ?? '—') . ' ~ ' . ($f_twa[1] ?? '—')); ?></span></li>
        <li>黄经（当日）：<?php echo esc_html($sun['ecl_lon_deg'] ?? '—'); ?>°</li>
      </ul>
    </section>

    <!-- 月球 -->
    <section class="kcj-astro-card">
      <h4>月球</h4>
      <ul>
        <li>月相：<?php echo esc_html($moon['phase_name'] ?? '—'); ?></li>
        <li>月龄：<?php echo esc_html($moon['moon_age_days'] ?? '—'); ?> 天</li>
        <li>月出：<span class="kcj-astro-v" data-kcj-f="moonrise"><?php echo esc_html($f_moonr ?? '—'); ?></span></li>
        <li>月落：<span class="kcj-astro-v" data-kcj-f="moonset"><?php echo esc_html($f_moons ?? '—'); ?></span></li>
        <li>地月距离：<?php echo esc_html($moon['distance_km'] ?? '—'); ?> km（误差千米量级）</li>
        <li>黄经（当日）：<?php echo esc_html($moon['ecl_lon_deg'] ?? '—'); ?>°</li>
      </ul>
    </section>

    <!-- 五大行星 -->
    <section class="kcj-astro-card kcj-astro-planets">
      <h4>五大行星</h4>
      <table>
        <thead><tr><th>行星</th><th>所在宿</th><th>视星等</th><th>观测难度</th></tr></thead>
        <tbody>
        <?php foreach ($cn as $k => $label): ?>
          <?php if (isset($planets[$k])): $p = $planets[$k]; ?>
          <tr>
            <td><?php echo esc_html($label); ?></td>
            <td><?php echo esc_html($p['xiu'] ?? '—'); ?></td>
            <td><?php echo esc_html($p['apparent_mag'] ?? '—'); ?><?php if (!empty($p['mag_note'])): ?><sup>*</sup><?php endif; ?></td>
            <td><?php echo esc_html($p['visibility'] ?? '—'); ?></td>
          </tr>
          <?php endif; ?>
        <?php endforeach; ?>
        </tbody>
      </table>
      <p class="kcj-astro-note">* 土星星等未计环的贡献，为近似值。观测难度仅描述观测条件。</p>
    </section>

    <!-- 二十八宿（黄道宿度） -->
    <section class="kcj-astro-card">
      <h4>二十八宿（黄道宿度）</h4>
      <ul>
        <li>日所在宿：<?php echo esc_html($xiu['sun_xiu'] ?? '—'); ?></li>
        <li>月所在宿：<?php echo esc_html($xiu['moon_xiu'] ?? '—'); ?></li>
        <?php if (!empty($xiu['planets_xiu']) && is_array($xiu['planets_xiu'])): ?>
        <li>行星入宿：<?php
          $bits = array();
          foreach ($xiu['planets_xiu'] as $pk => $pv) {
              $bits[] = (isset($cn[$pk]) ? $cn[$pk] : $pk) . '·' . $pv;
          }
          echo esc_html(implode('　', $bits));
        ?></li>
        <?php endif; ?>
      </ul>
      <p class="kcj-astro-note">口径：<?php echo esc_html($xiu['frame'] ?? '黄道宿度'); ?></p>
    </section>
  </div>

  <?php if ($pmode !== 'off' && $places): ?>
  <?php
  // ★ 把「本日全部预置观测地」的升落与晨昏交给前端。
  //   两条硬约束（都是本项目实际踩过的坑）：
  //   ① JSON **必须单行** —— 平台会对正文跑 wpautop，空行会被换成 </p><p>，
  //      多行 JSON 会被插进 HTML 标签而整块报废；
  //   ② 内容里**一个裸 & 都不能有** —— 平台后处理会把某些窗口内的裸 & 换成实体引用，
  //      而 <script> 内的内容不做实体解码 ⇒ 字符串被拆断、整块脚本语法错。
  //      故用 JSON_HEX_AMP / JSON_HEX_TAG 把 & 与 < > 全部转成 \uXXXX。
  //
  // ★ v2.3.0：**改成数组化的紧凑载荷**。观测地由 38 扩到 340 个锚点后，沿用
  //   「对象 + 具名键」的形状会让每页多出约 100 KB（键名重复 340 遍）。
  //   数组形状：每项 [key, cn, lat, lon, sunrise, sunset, daylen,
  //                    民用起, 民用止, 航海起, 航海止, 天文起, 天文止, 月出, 月落, 省码]
  //   ⇒ 约 34 KB。索引与下面的 JS 常量一一对应，**改一处必须改两处**。
  //   ★ v2.3.5 新增第 16 项「省码」：前端据此做**跨省守卫**（IP 报的省 ≠ 锚点所在省
  //     时不下自动结论）。每项多一个 6 位码 ⇒ 340×7 字节，约 +2.4 KB。
  // ★ v2.3.5：省码映射。$places 来自库表（无省市归属），省码只能从目录取。
  $prov_map = function_exists('kcj_astro_place_prov_map') ? kcj_astro_place_prov_map() : array();
  $rows_out = array();
  foreach ($places as $k => $v) {
      $pk = (string) $k;
      $prow = isset($prov_map[$pk]) ? $prov_map[$pk] : array();
      $rows_out[] = array(
          (string) $k,
          (string) (isset($v['cn']) ? $v['cn'] : $k),
          isset($v['lat']) ? (float) $v['lat'] : null,
          isset($v['lon']) ? (float) $v['lon'] : null,
          isset($v['sunrise']) ? $v['sunrise'] : null,
          isset($v['sunset']) ? $v['sunset'] : null,
          isset($v['daylen']) ? $v['daylen'] : null,
          isset($v['tw_c'][0]) ? $v['tw_c'][0] : null,
          isset($v['tw_c'][1]) ? $v['tw_c'][1] : null,
          isset($v['tw_n'][0]) ? $v['tw_n'][0] : null,
          isset($v['tw_n'][1]) ? $v['tw_n'][1] : null,
          isset($v['tw_a'][0]) ? $v['tw_a'][0] : null,
          isset($v['tw_a'][1]) ? $v['tw_a'][1] : null,
          isset($v['moonrise']) ? $v['moonrise'] : null,
          isset($v['moonset']) ? $v['moonset'] : null,
          isset($prow['p']) ? (string) $prow['p'] : '',
          isset($prow['n']) ? (string) $prow['n'] : '',
      );
  }
  $payload = array('cur' => $cur, 'mode' => $pmode, 'n' => count($rows_out), 'rows' => $rows_out);
  $json = wp_json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_HEX_AMP | JSON_HEX_TAG | JSON_HEX_APOS | JSON_HEX_QUOT);
  if ($json === false) { $json = '{}'; }
  ?>
  <script type="application/json" class="kcj-astro-places"><?php echo $json; // phpcs:ignore WordPress.Security.EscapeOutput -- 已 JSON 转义 ?></script>
  <?php endif; ?>

  <?php if (!empty($special_event)): ?>
  <div class="kcj-astro-special">
    <strong>特殊天象</strong>
    <ul>
    <?php foreach ((array) $special_event as $se): ?>
      <li>
        <?php if (!empty($se['url'])): ?>
          <a href="<?php echo esc_url($se['url']); ?>"><?php echo esc_html(isset($se['title']) ? $se['title'] : (string) $se); ?></a>
        <?php else: ?>
          <?php echo esc_html(isset($se['title']) ? $se['title'] : (string) $se); ?>
        <?php endif; ?>
        <?php if (!empty($se['time_bj'])): ?><span class="kcj-astro-time"><?php echo esc_html($se['time_bj']); ?></span><?php endif; ?>
        <?php if (!empty($se['note'])): ?><span class="kcj-astro-note">（<?php echo esc_html($se['note']); ?>）</span><?php endif; ?>
      </li>
    <?php endforeach; ?>
    </ul>
  </div>
  <?php endif; ?>

  <?php // 声明文本单一真值源在 includes/compliance.php，此处只取用，不另写一份 ?>
  <p class="kcj-astro-disclaimer"><?php
    echo esc_html(function_exists('kcj_astro_disclaimer_text')
        ? kcj_astro_disclaimer_text()
        : '天象数据基于 NASA JPL DE421 星历计算；近未来预报时刻精度 ±1 分钟。仅作天文参考，不涉及星占、谶纬、吉凶解读。');
  ?></p>
</div>
