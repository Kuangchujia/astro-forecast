/**
 * 观测地选择（v2.0.0 建；v2.3.0 扩到全国；v2.3.3 加省份 Tab ＋ 城市网格；v2.3.5 加定位双守卫；
 *           v2.3.6 网格移出首页 ＋ localStorage 承接）
 *
 * 做什么
 * ──────
 * 1. 读出本页已由服务端嵌好的「本日全部预置观测地的升落与晨昏」JSON（**紧凑数组载荷**）；
 * 2. auto 模式：向公开的 IP 归属地接口问一次经纬度，取**页面里已嵌的锚点坐标中最近的一个**
 *    —— 「按访问位置选**最近的预置观测地**」就是这一步，纯几何，与天文计算无关；
 * 3. 把该锚点的日出/日落/昼长/三种晨昏/月出/月落换上去（纯替换文本，**不做任何天文计算**）；
 * 4. 允许用户从下拉里改选，改选后不再自动覆盖。
 *
 * v2.3.0 新增：**增量升级到「省 → 市 → 县/区」三级可选**
 * ─────────────────────────────────────────────────
 * 服务端只渲染**锚点**（340 个，预计算过升落的那些）⇒ 基础页面小、且**无 JS 也能用**。
 * 本脚本再取一次 `assets/places-cn.json`（全站共享、可缓存的静态资源），
 * 把 **2,870 个县级可选点**并入下拉（按省分组）。
 *
 * v2.3.5 新增：**自动定位双守卫**（改的是「判据」，不是就近算法本身）
 * ──────────────────────────────────────────────────────────
 * 症状：① 开代理／在境外网络访问 → 观测地自动跳到「吉林延边朝鲜族州」等边城；
 *       ② 关代理但仍跳错（如人在揭阳、跳到深圳）。
 * 根因：定位接口给的是**访问者出口 IP**，不是本人位置。而旧代码
 *       (a) 不问国别，(b) 不问省份，(c) 不比距离 ⇒ 把「最近的锚点」直接当本地结果上报。
 * 取证：ipwho.is 实测返回 country_code=CN / city=Shenzhen / 22.5445,114.0545；
 *       出口 IP 登记在深圳而人在揭阳，是运营商常见现象（宽带出口在省网节点）。
 *       ★ 纯距离阈值**救不了**这一个：340 锚点真实稀疏区下界是阿里 512.6 km，
 *         而揭阳→深圳只有 261.7 km —— 想挡住深圳就得压到 250 km 以下，
 *         那阿里的正常用户会被误拦。**一个数字没法两头兼顾**，故改用省份校验。
 * 修法：两道守卫 ＋ 一键采用 ——
 *   ① **境外守卫**：country 非 'CN'（或未知）⇒ 不套用，只提示；
 *   ② **跨省守卫**：IP 报的省 ≠ 命中锚点所在省 ⇒ **不自动改城**，只提示 ＋ 给「采用」按钮；
 *   ③ 同省 ⇒ 正常套用（「同省内最近」在语义上是站得住的）。
 * ★ 为什么跨省只提示、不硬拦：出口 IP 与本机不同省既可能是运营商常态、也可能是真异地，
 *   代码分不清 ⇒ 不该替读者决定。**判据不足时，把决定权交回读者，而不是猜。**
 *
 * v2.3.6 新增：**网格移出首页 ＋ 选择结果跨页承接**
 * ────────────────────────────────────────────────
 * 背景（用户令）：「这个界面太长了，不行！…… 首页首屏仅保留『当前选中城市』以及
 *   『按我的位置』按钮。将『两级联动省份标签+城市网格面板』完全移出首页。」
 * 实测：线上首页 HTML 205,161 字符，城市相关（340 option / 34 radio / 34 tab / 35 pane /
 *   41,007 字符载荷）约 100 KB、占 49%。
 *
 * 改法（**不新增数据路径**）：
 *   ① 首页 astro-today.php 里那整块网格删掉，只留 select（视觉隐藏）＋ 按我的位置 ＋
 *      「切换观测地」小链接；
 *   ② 网格改由 templates/astro-places.php（挂 [astro_places_hub] 的独立页）渲染，
 *      仍由本文件的 buildGrid() 绑定、仍只做「替读者动 select」；
 *   ③ 两页不在同一 DOM ⇒ 独立页选完后把选择写进 localStorage（键 KCJ_STORE），
 *      **跳回来源页**；首页在 init() 里、**定位之前**先读它。
 *
 * ★ 为什么用 localStorage 而不是 URL 参数：
 *   换城不换 URL 是本项目既定纪律（v2.3.3）。走 ?place= 会把观测地永久留在地址栏，
 *   被收藏与转发 —— 那正是「把居住地结构化公开」的一种形式，与用户意见④被拦下同理。
 * ★ 为什么读在「定位之前」：手动选择优先于自动定位是第③条硬约束。
 *   读者专程去独立页选了一次城，回来却被 IP 定位覆盖掉，等于白选。
 *
 * v2.3.3 新增：**省份 Tab ＋ 城市网格**（只为好点，不改数据路径）
 * ──────────────────────────────────────────────────────────
 * 340 个锚点在一个原生下拉里，手机上要滚很久才找得到自己那一省。
 * 网格给出「一眼看到同省全部城」的形状，省份 Tab 切省**纯 CSS**（radio + label）。
 *
 * ★ 关键约束（改回即坏，别动）：
 *   · **网格不自己算，只替读者去动那个 <select>**（value ＋ 派发 change）。
 *     换城、状态行、手册优先于自动定位…… 全部复用既有一套，零新代码路径。
 *   · **<select> 不得从 DOM 移除**，只做视觉隐藏（.kcj-astro-sr）——
 *     它是 apply()／describe()／无 JS 降级的公共支点。
 *   · **格子用 <button> 不用 <a href>**：换城不换 URL。
 *     走 <a href="?place=…"> 既换不出内容（服务端只认 kcj_* 参数），
 *     又要 preventDefault 才能避免重载 —— 而无 JS 降级会随之失效。
 *   · **一律 root.querySelectorAll**，绝不 document.querySelector：
 *     同一页可能放多个 [astro_today]（见 collect()），全页取第一个会串台。
 *   · **select 一动，网格必须跟着动**（syncGrid）—— 否则格子亮在原城、
 *     上面却写着定位结果，界面自相矛盾（v2.3.0 修过同一类错）。
 *
 * ★ 这样分工的理由（不是随手拆的）：
 *   · 县级点**没有各自预计算的升落**，选中后用的仍是它绑定的那个**锚点**的数据
 *     ⇒ 页面必须如实说明「按 <锚点> 计算、直线距离约 N 千米」，否则就是把近似说成精确。
 *   · 3,210 个 <option> 内联进每页 HTML 会让每页多出百余 KB；做成静态资源则只下一次。
 *
 * 四条硬约束（都是本项目踩过的坑，不要改回去）
 * ─────────────────────────────────────────────
 * ① **整份脚本里不出现裸与号字符**：平台后处理会把正文某些窗口内的裸与号换成实体引用，
 *    而 script 标签里的内容不做实体解码 ⇒ 逻辑与会变成两个实体串 ⇒ JS 语法错、整块失效。
 *    故一律用嵌套 if 代替逻辑与运算，绝不写连续两个与号。
 *    （本文件是**外部资源**，本不经正文后处理；这里仍照此纪律写，避免将来被内联进正文时踩坑。）
 * ② **导航/接口失败一律静默回落**：定位不到、目录取不到，都保持当前渲染结果，
 *    页面照样完整可读（不弹窗、不报错、不阻塞）。但**状态行必须如实说**
 *    —— 「回落」可以，「假装成功」不行。
 * ③ **手动选择优先于自动定位**：用户一旦动过下拉，后续的定位结果不再改写它。
 * ④ **载荷字段顺序与模板一一对应**：见下 F_* 常量。改一处必须改两处
 *    （templates/astro-today.php 组数组的那一段）。
 */
(function () {
  'use strict';

  // 跨页承接的存储键（与 includes/shortcodes.php 的 kcj_astro_place_store_key() 必须一致）
  var KCJ_STORE = 'kcj_astro_place';
  // 本次会话里是否「读者在独立页明确选过城」—— 选过就不再自动覆盖（手动优先）
  var stored_once = false;

  var EPS_KM = 111.2;   // 平面近似：纬度方向每度约 111.2 km（与 Python 侧 nearest_city 同一常数）

  // 紧凑载荷的列序（与 templates/astro-today.php 的 $rows_out 一一对应）
  var F_KEY = 0, F_CN = 1, F_LAT = 2, F_LON = 3;
  var F_SUNRISE = 4, F_SUNSET = 5, F_DAYLEN = 6;
  var F_TC0 = 7, F_TC1 = 8, F_TN0 = 9, F_TN1 = 10, F_TA0 = 11, F_TA1 = 12;
  var F_MOONRISE = 13, F_MOONSET = 14;
  // ★ v2.3.5：第 16、17 项 —— 命中锚点所属省的 adcode 与省名（跨省守卫用）
  var F_PROV = 15, F_PROVN = 16;

  // data-kcj-f 属性 → 载荷列（成对的晨昏列各自展开）
  var SLOT = {
    sunrise: F_SUNRISE, sunset: F_SUNSET, daylen: F_DAYLEN,
    moonrise: F_MOONRISE, moonset: F_MOONSET
  };
  var SLOT_PAIR = { tw_c: [F_TC0, F_TC1], tw_n: [F_TN0, F_TN1], tw_a: [F_TA0, F_TA1] };

  function ready(fn) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', fn);
      return;
    }
    fn();
  }

  /** 取「本页所有未初始化过的」今日天象板块（同一页可能放多个短代码） */
  function collect() {
    var nodes = document.querySelectorAll('.kcj-astro-today[data-kcj-place-mode]');
    var out = [];
    Array.prototype.forEach.call(nodes, function (n) {
      if (n.getAttribute('data-kcj-init') === '1') { return; }
      n.setAttribute('data-kcj-init', '1');
      out.push(n);
    });
    return out;
  }

  /** 读紧凑载荷 → { cur, mode, index:{key:row}, order:[key,...] }；读不出返回 null */
  function parseIsland(root) {
    var el = root.querySelector('script.kcj-astro-places');
    if (!el) { return null; }
    var data = null;
    try { data = JSON.parse(el.textContent); } catch (e) { return null; }
    if (!data) { return null; }
    if (!data.rows) { return null; }
    if (!data.rows.length) { return null; }
    var index = {};
    var order = [];
    for (var i = 0; i < data.rows.length; i++) {
      var r = data.rows[i];
      if (!r) { continue; }
      var k = r[F_KEY];
      if (!k) { continue; }
      index[k] = r;
      order.push(k);
    }
    if (!order.length) { return null; }
    return { cur: data.cur || '', mode: data.mode || 'off', index: index, order: order };
  }

  /** 平面近似距离（km）。只用于「选最近的一个预置观测地」，与对外数值无关。 */
  function distKm(lat1, lon1, lat2, lon2) {
    var dy = (lat1 - lat2) * EPS_KM;
    var mid = (lat1 + lat2) / 2 * Math.PI / 180;
    var dx = (lon1 - lon2) * EPS_KM * Math.cos(mid);
    return Math.sqrt(dx * dx + dy * dy);
  }

  /** 最近锚点 → { key, km, prov, provCn }；坐标不全或表为空返回 null。
   *  ★ v2.3.5：一并带出该锚点**所属省的 adcode 与省名**，供跨省守卫比对。 */
  function nearest(island, lat, lon) {
    var best = null;
    var bestD = null;
    for (var i = 0; i < island.order.length; i++) {
      var k = island.order[i];
      var r = island.index[k];
      if (typeof r[F_LAT] !== 'number') { continue; }
      if (typeof r[F_LON] !== 'number') { continue; }
      var d = distKm(lat, lon, r[F_LAT], r[F_LON]);
      if (bestD === null) { best = k; bestD = d; continue; }
      if (d < bestD) { best = k; bestD = d; }
    }
    if (best === null) { return null; }
    var row = island.index[best];
    return { key: best, km: Math.round(bestD),
             prov: row[F_PROV] || '', provCn: row[F_PROVN] || '' };
  }


  /* ── v2.3.6：跨页承接 ──────────────────────────────────────────────
   * 独立页（[astro_places_hub]）与首页不在同一 DOM，故选择结果经 localStorage 过渡。
   * ★ 一律 try/catch：隐私模式／被策略禁用时 localStorage 会抛异常，
   *   此时**静默回落**（定位照旧、页面照旧），绝不因为存储不可用而让整块脚本失效。
   */
  function readStore() {
    try {
      var v = window.localStorage.getItem(KCJ_STORE);
      if (!v) { return ''; }
      return String(v);
    } catch (e) { return ''; }
  }

  function writeStore(key) {
    try { window.localStorage.setItem(KCJ_STORE, String(key)); } catch (e) {}
  }

  function txt(v) {
    if (v === null) { return '—'; }
    if (v === undefined) { return '—'; }
    if (v === '') { return '—'; }
    return String(v);
  }

  /** 把某一行的升落与晨昏写到页面上（纯文本替换，零计算） */
  function apply(root, island, key) {
    var r = island.index[key];
    if (!r) { return false; }
    var slots = root.querySelectorAll('[data-kcj-f]');
    Array.prototype.forEach.call(slots, function (s) {
      var f = s.getAttribute('data-kcj-f');
      if (SLOT.hasOwnProperty(f)) {
        s.textContent = txt(r[SLOT[f]]);
        return;
      }
      if (SLOT_PAIR.hasOwnProperty(f)) {
        var pair = SLOT_PAIR[f];
        s.textContent = txt(r[pair[0]]) + ' ~ ' + txt(r[pair[1]]);
      }
    });
    var label = root.querySelector('[data-kcj-city-label]');
    if (label) { label.textContent = txt(r[F_CN]); }
    root.setAttribute('data-kcj-place-cur', key);
    return true;
  }

  /**
   * 写状态行。text 为 null 时只清按钮、不动文字（供「先清后设」用）。
   *
   * ★ v2.3.5 加第 3、4 个参数：跨省时给一个「仍改用 X」按钮 ——
   *   **提示不等于挡路**：读了提示仍想用得顺手，一步就能改。
   *   采用动作需要 apply/island/sel/syncGrid，故由调用方把**回调**传进来
   *   （onAdopt），本函数只管渲染，不反查全局状态。
   */
  function setStatus(root, text, adoptLabel, onAdopt) {
    var s = root.querySelector('.kcj-astro-place-status');
    if (!s) { return; }
    if (typeof text === 'string') { s.textContent = text; }
    var old = s.querySelector('.kcj-astro-place-adopt');
    if (old) { s.removeChild(old); }
    if (!adoptLabel || !onAdopt) { return; }
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'kcj-astro-place-adopt';
    b.textContent = adoptLabel;
    b.addEventListener('click', function () { onAdopt(); });
    s.appendChild(b);
  }

  /**
   * 取一次全国观测地目录（**全页只取一次**，多个板块共用）。
   * 失败即回调 null —— 调用方保持服务端已渲染好的锚点下拉（**完整可用，只是没有县级**）。
   */
  var catalogPromise = null;
  function loadCatalog(url, cb) {
    if (!url) { cb(null); return; }
    if (catalogPromise === null) {
      catalogPromise = fetch(url, { credentials: 'omit', mode: 'cors' })
        .then(function (r) {
          if (!r.ok) { return null; }
          return r.json();
        })
        .catch(function () { return null; });
    }
    catalogPromise.then(function (c) {
      if (!c) { cb(null); return; }
      if (!c.anchors) { cb(null); return; }
      if (!c.places) { cb(null); return; }
      cb(c);
    });
  }

  /** 目录 → 分组：省 → { name, anchors:[key], places:[[adcode,cn,anchor,km],...] } */
  function groupCatalog(cat) {
    var provName = {};
    var i;
    for (i = 0; i < cat.provinces.length; i++) {
      provName[cat.provinces[i][0]] = cat.provinces[i][1];
    }
    var anchorProv = {};
    var groups = {};
    var order = [];
    for (i = 0; i < cat.anchors.length; i++) {
      var a = cat.anchors[i];
      var key = a[0];
      var prov = a[2];
      anchorProv[key] = prov;
      if (!groups[prov]) {
        groups[prov] = { name: provName[prov] || prov, anchors: [], places: [] };
        order.push(prov);
      }
      groups[prov].anchors.push(key);
    }
    for (i = 0; i < cat.places.length; i++) {
      var p = cat.places[i];
      var prov2 = anchorProv[p[2]];
      if (!prov2) { continue; }
      if (!groups[prov2]) {
        groups[prov2] = { name: provName[prov2] || prov2, anchors: [], places: [] };
        order.push(prov2);
      }
      groups[prov2].places.push(p);
    }
    return { order: order, groups: groups };
  }

  function makeOption(value, label, anchorKey, km, selected) {
    var o = document.createElement('option');
    o.value = value;
    o.textContent = label;
    o.setAttribute('data-anchor', anchorKey);
    if (typeof km === 'number') { o.setAttribute('data-km', String(km)); }
    if (selected) { o.selected = true; }
    return o;
  }

  /**
   * 把服务端渲染的「仅锚点」下拉**升级**为「省 → 市 → 县/区」。
   * 只并入「其锚点当天真的有数据」的项 —— 列了没数据的会让读者选到一片「—」。
   */
  function upgradeSelect(root, island, cat) {
    var sel = root.querySelector('.kcj-astro-place-select');
    if (!sel) { return false; }
    if (sel.getAttribute('data-kcj-upgraded') === '1') { return false; }
    var g = groupCatalog(cat);
    var cur = root.getAttribute('data-kcj-place-cur') || island.cur;
    var frag = document.createDocumentFragment();
    for (var i = 0; i < g.order.length; i++) {
      var prov = g.order[i];
      var grp = g.groups[prov];
      var og = document.createElement('optgroup');
      og.label = grp.name;
      var n_ok = 0;
      var j;
      for (j = 0; j < grp.anchors.length; j++) {
        var key = grp.anchors[j];
        if (!island.index[key]) { continue; }
        og.appendChild(makeOption(key, island.index[key][F_CN], key, null, key === cur));
        n_ok += 1;
      }
      for (j = 0; j < grp.places.length; j++) {
        var p = grp.places[j];
        if (!island.index[p[2]]) { continue; }
        // 县级点的 value 前缀 "p:" 与锚点键区分开；真正的数据键永远在 data-anchor 上
        og.appendChild(makeOption('p:' + p[0], p[1], p[2], p[3], false));
        n_ok += 1;
      }
      if (!n_ok) { continue; }
      frag.appendChild(og);
    }
    if (!frag.childNodes.length) { return false; }
    while (sel.firstChild) { sel.removeChild(sel.firstChild); }
    sel.appendChild(frag);
    sel.setAttribute('data-kcj-upgraded', '1');
    return true;
  }

  /**
   * v2.3.3：把「省份 Tab ＋ 城市网格」的点击接到那个**视觉隐藏的 <select>** 上。
   *
   * ★ 本函数**不做任何自己的选择逻辑** —— 它只替读者去动 select：
   *     sel.value = 锚点键;  sel.dispatchEvent(new Event('change'))
   *   于是换城、状态行、手册优先于自动定位…… 全部复用 init() 里既有的那一套，
   *   零新代码路径。（这也正是「不删 select」的理由：它才是数据支点。）
   *
   * ★ 为什么不用 <a href="?place="> 那一路：换城**不换 URL**。
   *   数据早已全嵌在本页（parseIsland 的紧凑载荷），换城纯改 DOM。
   *   跳 URL 既不会换出内容（服务端只认 kcj_* 参数，不认 place），
   *   又会把参数永久留在地址栏、被收藏与分享（第十八轮「URL 污染」的教训）。
   *
   * ⚠ 只认**本 root 内**的格子（root.querySelectorAll），绝不 document.querySelector
   *   —— 同一页可能放多个 [astro_today]（见 collect()），全页取第一个会串台。
   */
  function buildGrid(root, sel) {
    var grid = root.querySelector('.kcj-astro-place-grid');
    if (!grid) { return false; }
    if (grid.getAttribute('data-kcj-bound') === '1') { return false; }
    var cells = grid.querySelectorAll('.kcj-astro-place-city');
    if (!cells.length) { return false; }

    Array.prototype.forEach.call(cells, function (btn) {
      btn.addEventListener('click', function () {
        var key = btn.getAttribute('data-anchor') || '';
        if (!key) { return; }
        // 只为「替读者动 select」—— 若该锚点不在 select 里（当天无数据），什么也不做，
        // 因为做了也没有数据可换（模板侧已按 $covered 过滤，正常不会发生）。
        if (!sel.querySelector('option[value="' + key + '"]')) { return; }
        sel.value = key;
        sel.dispatchEvent(new Event('change'));
      });
    });
    grid.setAttribute('data-kcj-bound', '1');
    return true;
  }

  /**
   * v2.3.3：把「当前生效的城」同步回网格 —— 只是把 aria-pressed 标好、把所在省的 Tab 打开。
   *
   * 为什么必须有这个同步：网格与 select 是**同一件事的两个面**。
   * 自动定位（locate）与手册改选都会动 select；若网格不跟着动，
   * 读者会看到「格子还亮在揭阳、上面却写着北京」—— 界面自相矛盾。
   * ⚠ 这与 v2.3.0 修「下拉默认项与生效城不一致」是同一类错，不能重犯。
   */
  function syncGrid(root, island, key) {
    var grid = root.querySelector('.kcj-astro-place-grid');
    if (!grid) { return; }
    var row = island.index[key];
    if (!row) { return; }
    var cn = row[F_CN];
    var cells = grid.querySelectorAll('.kcj-astro-place-city');
    var hit = null;
    Array.prototype.forEach.call(cells, function (btn) {
      var isMe = btn.textContent === cn;
      btn.setAttribute('aria-pressed', isMe ? 'true' : 'false');
      if (isMe) { hit = btn; }
    });
    // 当前城不在已渲染的格子里（目录里没有它，或当天它没数据）⇒ 不擅自开别的省的 Tab，
    // 保持服务端算好的默认省（否则读者刚点的地方会被莫名切走）。
    if (!hit) { return; }
    var pane = hit.parentNode;
    if (!pane) { return; }
    var gi = pane.getAttribute('data-gi');
    var radio = grid.querySelector('.kcj-astro-place-pradio[data-gi="' + gi + '"]');
    if (radio) { radio.checked = true; }
  }


  /**
   * v2.3.6：绑定**观测地总览页**的网格（[astro_places_hub]）。
   *
   * 与 buildGrid() 的分工：
   *   · buildGrid(root, sel)   —— root = .kcj-astro-today，sel 是**本页**的隐藏 select
   *                               （首页：点完就地换数据，不跳页）
   *   · bindHubGrid(root, sel) —— root = .kcj-astro-places-hub，sel 是**本页**的平铺 select
   *                               （独立页：点完落盘 ＋ 跳回来源页，因为数据不在这页）
   *
   * ★ 两者都**不做自己的选择逻辑** —— 只做「替读者动 select」＋ 派发 change。
   *   独立页的 change 监听器负责落盘与跳转，故这里派发的事件会被它接住，闭环且幂等。
   */
  function bindHubGrid(root, sel) {
    var grid = root.querySelector('.kcj-astro-place-grid');
    if (!grid) { return false; }
    if (grid.getAttribute('data-kcj-bound') === '1') { return false; }
    var cells = grid.querySelectorAll('.kcj-astro-place-city');
    if (!cells.length) { return false; }
    Array.prototype.forEach.call(cells, function (btn) {
      btn.addEventListener('click', function () {
        var key = btn.getAttribute('data-anchor') || '';
        if (!key) { return; }
        if (!sel.querySelector('option[value="' + key + '"]')) { return; }
        sel.value = key;
        sel.dispatchEvent(new Event('change'));
      });
    });
    grid.setAttribute('data-kcj-bound', '1');
    return true;
  }

  /** 独立页自己的同步：只标 aria-pressed、开对应省的 Tab（没有 select 可动） */
  function syncHubGrid(root, cn) {
    var grid = root.querySelector('.kcj-astro-place-grid');
    if (!grid) { return; }
    var cells = grid.querySelectorAll('.kcj-astro-place-city');
    var hit = null;
    Array.prototype.forEach.call(cells, function (btn) {
      var isMe = btn.textContent === cn;
      btn.setAttribute('aria-pressed', isMe ? 'true' : 'false');
      if (isMe) { hit = btn; }
    });
    if (!hit) { return; }
    var pane = hit.parentNode;
    if (!pane) { return; }
    var gi = pane.getAttribute('data-gi');
    var radio = grid.querySelector('.kcj-astro-place-pradio[data-gi="' + gi + '"]');
    if (radio) { radio.checked = true; }
  }

  /**
   * v2.3.6：观测地总览页的初始化（独立于 init()，因为那一套全程围绕 .kcj-astro-today）。
   * 该页**没有**今日天象数据，故不 apply、不定位 —— 只做：读存档、点格落盘、跳回。
   */
  function initHub() {
    var hubs = document.querySelectorAll('.kcj-astro-places-hub');
    if (!hubs.length) { return; }
    Array.prototype.forEach.call(hubs, function (root) {
      if (root.getAttribute('data-kcj-init') === '1') { return; }
      root.setAttribute('data-kcj-init', '1');
      var sel = root.querySelector('.kcj-astro-place-select');
      if (!sel) { return; }
      var storeKey = root.getAttribute('data-kcj-store') || KCJ_STORE;
      var backUrl = root.getAttribute('data-kcj-hub-url') || '';
      // 来源页：优先 referrer（读者从哪来就回哪去），取不到退回站点首页
      var from = '';
      try { from = document.referrer || ''; } catch (e) { from = ''; }
      if (!from) { from = root.getAttribute('data-kcj-home') || '/'; }

      // 存档回填：读者上次选的城，本页也要亮着（否则「当前观测地」与格子自相矛盾）
      var saved = readStore();
      if (saved) {
        if (sel.querySelector('option[value="' + saved + '"]')) { sel.value = saved; }
        var opt = sel.options[sel.selectedIndex];
        if (opt) { syncHubGrid(root, opt.textContent); }
      }

      function commit(key, cn, go) {
        writeStore(key);
        var st = root.querySelector('.kcj-astro-place-status');
        if (st) { st.textContent = '已记下观测地：「' + cn + '」' + (go ? '，正在返回…' : '。'); }
        if (go) {
          try { window.location.assign(from); } catch (e2) {}
        }
      }

      sel.addEventListener('change', function () {
        var opt = sel.options[sel.selectedIndex];
        if (!opt) { return; }
        var key = opt.getAttribute('data-anchor') || '';
        if (!key) { return; }
        syncHubGrid(root, opt.textContent);
        commit(key, opt.textContent, true);
      });

      bindHubGrid(root, sel);
      // 无 JS 时 <form method="get"> 会把 ?<select name> 提交回本页 —— 服务端读它即可生效。
      //   ★ 但本页的 select **没有 name**（不给地址栏留观测地），故无 JS 时点「查看」
      //     只是刷新 + 保留选择，属**已知降级**，页面上已如实说明。此处补一条：
      //     有 JS 时把 form 的提交拦下，改为落盘＋跳回（避免无意义刷新）。
      var form = root.querySelector('.kcj-astro-places-form');
      if (form) {
        form.addEventListener('submit', function (ev) {
          var opt = sel.options[sel.selectedIndex];
          if (!opt) { return; }
          var key = opt.getAttribute('data-anchor') || '';
          if (!key) { return; }
          ev.preventDefault();
          commit(key, opt.textContent, true);
        });
      }
    });
  }

  /** 依序问两个公开接口。两者都返回 latitude/longitude。全失败回调 null（调用方静默回落）。
   *  ★ v2.3.5：**必须同时问国别**（country_code）—— 不问国别时，代理／境外网络的出口 IP
   *    会被当成本地起点，去和 340 个中国锚点比近，结果落在一个境内边城（如延边）。
   *    ipwho.is 走 `fields`（`country_code` 与 `region` 均可指定）；
   *    ipapi.co/json/ 原生带 `country_code` 与 `region_code`，无需额外参数。
   *  ★ `region` 用作跨省守卫的第二重证据：IP 报的省名与命中锚点所在省名比对。
   *    实测 ipwho.is 的 region 给中文省名（如「广东」），与本目录省名「广东省」可互含匹配。 */
  function locate(cb) {
    var urls = [
      'https://ipwho.is/?fields=latitude,longitude,city,country_code,region',
      'https://ipapi.co/json/'
    ];
    var i = 0;
    function step() {
      if (i >= urls.length) { cb(null); return; }
      var url = urls[i];
      i += 1;
      var ctrl = null;
      var timer = null;
      try { ctrl = new AbortController(); } catch (e) { ctrl = null; }
      var opts = { credentials: 'omit', mode: 'cors' };
      if (ctrl) { opts.signal = ctrl.signal; }
      if (ctrl) {
        timer = setTimeout(function () {
          try { ctrl.abort(); } catch (e2) {}
        }, 2500);
      }
      fetch(url, opts).then(function (r) {
        if (timer) { clearTimeout(timer); }
        if (!r.ok) { step(); return null; }
        return r.json();
      }).then(function (j) {
        if (j === null) { return; }
        var lat = parseFloat(j.latitude);
        var lon = parseFloat(j.longitude);
        if (isNaN(lat)) { step(); return; }
        if (isNaN(lon)) { step(); return; }
        // 国别：取不到就留空串 —— 空串按「未知」处理，**不当作中国**（宁可不套用）。
        var cc = '';
        if (j.country_code) { cc = String(j.country_code).toUpperCase(); }
        // 省：ipwho.is 给 region（中文省名）；ipapi.co 给 region（英文）与 region_code（数字串）。
        var rg = '';
        if (j.region) { rg = String(j.region); }
        // ★ 铁律：整份脚本不出现裸与号（平台后处理会替换成实体、拆断脚本）
        //   ⇒ 一律用嵌套 if，绝不写连续两个与号。
        if (!rg) {
          if (j.region_code) { rg = String(j.region_code); }
        }
        cb({ lat: lat, lon: lon, city: j.city || '', country: cc, region: rg });
      }).catch(function () {
        if (timer) { clearTimeout(timer); }
        step();
      });
    }
    step();
  }

  /** 省名归一：去掉「省／市／自治区／特别行政区／壮族／回族／维吾尔／自治州」等后缀，
   *  取前两字做粗比对（「广东」vs「广东省」→ 同；「内蒙古」vs「内蒙古自治区」→ 同）。
   *  ★ 取前两字是**有意从宽**：这里只用来判「是不是明显不同省」，
   *    宁可漏拦（同省被当不同省 → 多一次提示，无害），不可误拦（不同省被当同省 → 悄悄改城，有害）。
   *    等等 —— 方向反了：从宽会**漏拦**。故再叠一层「互含」判据：
   *    两串任一方含另一方的前两字即算同省；都不含 ⇒ 判为不同省。 */
  function sameRegion(a, b) {
    if (!a || !b) { return true; }   // 缺省 ⇒ 不拦（缺证据时不制造提示）
    var x = String(a), y = String(b);
    var x2 = x.substring(0, 2), y2 = y.substring(0, 2);
    if (x.indexOf(y2) >= 0) { return true; }
    if (y.indexOf(x2) >= 0) { return true; }
    return false;
  }

  /**
   * 自动定位的**唯一**文案出口（v2.3.5）。三个调用点共用，免得三处文案各改各的。
   *
   * 返回一个对象：{ applied: 是否已改城, key: 建议的锚点, km, anchorCn }
   *   · applied true  ⇒ 已套用（调用方回写网格）
   *   · applied false ⇒ 仅提示；若 key 有值，另给「采用」按钮（一键改用该地）
   *
   * 三态（★ 一律如实，不假装成功）：
   *   ① country 非 CN ／ 未知  ⇒ 「未能识别为国内位置」＋接口报的城市，**不套用**
   *   ② 境内但跨省           ⇒ 「据 IP 判断你在 X 省，与当前观测地 Y 省不一致」，
   *                              **不套用**，给「采用该地」按钮
   *   ③ 同省命中             ⇒ 套用，并写出接口报的城市与直线距离
   */
  function autoApply(root, island, sel, hit, tail, adoptNow) {
    var n = nearest(island, hit.lat, hit.lon);
    if (!n) {
      setStatus(root, '未能取得可用坐标，已保持当前观测地。');
      return { applied: false };
    }
    var anchorCn = island.index[n.key][F_CN];
    var curKey = island.cur;
    var curCn = island.index[curKey] ? island.index[curKey][F_CN] : '默认观测地';
    var from = hit.city ? ('（IP 报城市：' + hit.city + '）') : '';

    // 态一：不在中国境内（或拿不到国别 —— 缺证据时同样不套用）
    if (hit.country !== 'CN') {
      var w = hit.country ? ('IP 报所在国家／地区代码：' + hit.country) : 'IP 未给出国家／地区';
      setStatus(root, '未能识别为国内位置' + from + '，' + w
        + '，已保持当前观测地（' + curCn + '）。如需改用他地，请在上方手动选择。');
      return { applied: false };
    }

    // 态二：境内，但 IP 报的省与命中锚点所在省不一致
    var ipRegion = hit.region || '';
    if (!sameRegion(ipRegion, n.provCn)) {
      setStatus(root, '据 IP 判断你在「' + (ipRegion || '未知')
        + '」，与最近的预置观测地「' + anchorCn + '」（' + n.provCn
        + '）不在同一省，直线距离约 ' + n.km
        + ' 千米。为免误判，已保持当前观测地（' + curCn + '）。',
        '仍改用「' + anchorCn + '」', adoptNow);
      return { applied: false, key: n.key, km: n.km, anchorCn: anchorCn };
    }

    // 态三：同省 ⇒ 正常命中
    if (!apply(root, island, n.key)) { return { applied: false }; }
    setStatus(root, '已按访问位置选最近的预置观测地：' + anchorCn
      + from + '（直线距离约 ' + n.km + ' 千米）' + (tail || ''));
    return { applied: true, key: n.key, km: n.km, anchorCn: anchorCn };
  }

  /** 把「当前选中的是哪一项」写成一句如实的话（含锚点与距离） */
  function describe(root, island, sel) {
    var opt = sel.options[sel.selectedIndex];
    if (!opt) { return ''; }
    var anchor = opt.getAttribute('data-anchor') || '';
    var row = island.index[anchor];
    var anchorCn = row ? row[F_CN] : anchor;
    var km = opt.getAttribute('data-km');
    var isCounty = opt.value.indexOf('p:') === 0;
    if (!isCounty) {
      return '观测地：' + anchorCn + '（预置观测地，已按你所在位置就近选择）。';
    }
    var s = '观测地：' + anchorCn + '（按「' + opt.textContent + '」就近匹配）';
    if (km) { s += '，直线距离约 ' + km + ' 千米'; }
    return s + '。升落与晨昏依该预置观测地计算。';
  }

  function init() {
    var roots = collect();
    if (!roots.length) { return; }

    var autoRoots = [];

    Array.prototype.forEach.call(roots, function (root) {
      var island = parseIsland(root);
      if (!island) { return; }
      if (island.mode === 'off') { return; }

      var manual = false;
      var sel = root.querySelector('.kcj-astro-place-select');
      var catUrl = root.getAttribute('data-kcj-catalog') || '';

      if (sel) {
        sel.addEventListener('change', function () {
          manual = true;
          var opt = sel.options[sel.selectedIndex];
          var anchor = opt ? opt.getAttribute('data-anchor') : '';
          if (!anchor) { return; }
          if (apply(root, island, anchor)) {
            // ★ v2.3.6：手动改选即落盘 —— 独立页/本页选过，后续自动定位不再覆盖（手动优先）
            writeStore(anchor);
            stored_once = true;
            setStatus(root, describe(root, island, sel));
            // ★ v2.3.3：网格是 select 的视觉面，select 一动网格必须跟着动。
            //   （网格点击 → 派发 change → 到这里 → 再同步回网格，是闭环且幂等的。）
            syncGrid(root, island, anchor);
          }
        });
        // ★ v2.3.3：把省份 Tab ＋ 城市网格接到 select 上（在升级之前绑定即可 ——
        //   格子是服务端渲染的，不随 upgradeSelect 变化）。
        buildGrid(root, sel);
        // 增量升级为「省 → 市 → 县/区」；取不到目录就保持锚点下拉（完整可用）
        loadCatalog(catUrl, function (cat) {
          if (!cat) { return; }
          if (!upgradeSelect(root, island, cat)) { return; }
          // 升级会重建选项 ⇒ 把界面重置回「当前生效的观测地」，免得不一致
          var cur = root.getAttribute('data-kcj-place-cur') || island.cur;
          if (sel.querySelector('option[value="' + cur + '"]')) {
            sel.value = cur;
          }
          setStatus(root, describe(root, island, sel));
        });
      }

      var btn = root.querySelector('.kcj-astro-place-auto');
      if (btn) {
        btn.addEventListener('click', function () {
          manual = false;
          setStatus(root, '正在按访问位置选择最近的预置观测地…');
          // ★ v2.3.5：跨省时的「仍改用 X」按钮动作 = 套用 ＋ 回写下拉与网格。
          //   与态三走的是同一条落点，只是在读者确认后才执行。
          function adoptTarget(key) {
            if (!apply(root, island, key)) { return; }
            manual = true;
            if (sel) {
              if (sel.querySelector('option[value="' + key + '"]')) { sel.value = key; }
            }
            syncGrid(root, island, key);
            setStatus(root, '已改用「' + island.index[key][F_CN] + '」。');
          }
          locate(function (hit) {
            if (!hit) {
              setStatus(root, '定位失败（接口不可达或被浏览器拦截），已保持当前观测地。');
              return;
            }
            // ★ v2.3.5：manual 只在**真的改了城**时才置位 ——
            //   否则一次「仅提示」的点击会把后续自动定位永久挡掉（读者只是想知道自己在哪）。
            var res = autoApply(root, island, sel, hit, '。',
              function () { adoptTarget(res.key); });
          });
        });
      }

      if (island.mode === 'auto') { autoRoots.push(root); }
    });

    // ★ v2.3.6：**定位之前**先把「独立页选过的城」应用上 ——
    //   手动选择优先于自动定位（第③条硬约束）。读者专程去独立页选了一次，
    //   回来若被 IP 定位覆盖，等于白选（且会让「已在深圳」这类误判反复出现）。
    //   ⇒ 有存档就应用 ＋ 把 autoRoots 清空（不再跑自动定位）。
    var saved = readStore();
    if (saved) {
      var used = false;
      Array.prototype.forEach.call(autoRoots, function (root) {
        var isl = parseIsland(root);
        if (!isl) { return; }
        if (!isl.index[saved]) { return; }
        if (!apply(root, isl, saved)) { return; }
        var sl = root.querySelector('.kcj-astro-place-select');
        if (sl) {
          if (sl.querySelector('option[value="' + saved + '"]')) { sl.value = saved; }
        }
        syncGrid(root, isl, saved);
        setStatus(root, describe(root, isl, sl));
        used = true;
      });
      if (used) {
        stored_once = true;
        autoRoots = [];
      }
    }

    if (!autoRoots.length) { return; }
    locate(function (hit) {
      if (!hit) {
        Array.prototype.forEach.call(autoRoots, function (root) {
          setStatus(root, '未能自动定位（接口不可达或被浏览器拦截），'
            + '已按当前观测地显示；可在上方下拉里改选。');
        });
        return;
      }
      Array.prototype.forEach.call(autoRoots, function (root) {
        var island = parseIsland(root);
        if (!island) { return; }
        // ★ v2.3.6：以「此刻页面上真正生效的城」为准（archived 或服务端默认），
        //   而不是载荷里的 island.cur —— 前者可能已被 localStorage 改过。
        var liveCur = root.getAttribute('data-kcj-place-cur') || '';
        if (liveCur) { island.cur = liveCur; }
        var sel = root.querySelector('.kcj-astro-place-select');
        var opted = false;
        if (sel) {
          opted = sel.getAttribute('data-kcj-upgraded') === '1';
        }
        // 说明句要区分「下拉已升级为全国县级」与「只有锚点」两种情况，
        // 否则读者会以为「我所在的区县没被收录」。
        var tail = opted
          ? '；可展开下拉改选到市/县/区。'
          : '；可手动改选。';
        // ★ v2.3.5：套用与文案全部交给 autoApply（三态集中一处）；
        //   跨省时只提示 ＋ 给按钮，不静默改城。
        function adoptAuto(key) {
          if (!apply(root, island, key)) { return; }
          if (sel) {
            if (sel.querySelector('option[value="' + key + '"]')) { sel.value = key; }
          }
          syncGrid(root, island, key);
          setStatus(root, '已改用「' + island.index[key][F_CN] + '」' + tail);
        }
        var res = autoApply(root, island, sel, hit, tail,
          function () { adoptAuto(res.key); });
      });
    });
  }

  ready(function () {
    init();      // 今日天象板块（首页/栏目页）
    initHub();   // 观测地总览页（v2.3.6 独立页）
  });
})();
