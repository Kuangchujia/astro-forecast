/**
 * 观测地选择（v2.0.0 建；v2.3.0 扩到全国；v2.3.3 加省份 Tab ＋ 城市网格）
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

  var EPS_KM = 111.2;   // 平面近似：纬度方向每度约 111.2 km（与 Python 侧 nearest_city 同一常数）

  // 紧凑载荷的列序（与 templates/astro-today.php 的 $rows_out 一一对应）
  var F_KEY = 0, F_CN = 1, F_LAT = 2, F_LON = 3;
  var F_SUNRISE = 4, F_SUNSET = 5, F_DAYLEN = 6;
  var F_TC0 = 7, F_TC1 = 8, F_TN0 = 9, F_TN1 = 10, F_TA0 = 11, F_TA1 = 12;
  var F_MOONRISE = 13, F_MOONSET = 14;

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

  /** 最近锚点 → { key, km }；坐标不全或表为空返回 null */
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
    return { key: best, km: Math.round(bestD) };
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

  function setStatus(root, text) {
    var s = root.querySelector('.kcj-astro-place-status');
    if (s) { s.textContent = text; }
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

  /** 依序问两个公开接口。两者都返回 latitude/longitude。全失败回调 null（调用方静默回落）。 */
  function locate(cb) {
    var urls = [
      'https://ipwho.is/?fields=latitude,longitude,city',
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
        cb({ lat: lat, lon: lon, city: j.city || '' });
      }).catch(function () {
        if (timer) { clearTimeout(timer); }
        step();
      });
    }
    step();
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
            setStatus(root, describe(root, island, sel));
            // ★ v2.3.2：网格是 select 的视觉面，select 一动网格必须跟着动。
            //   （网格点击 → 派发 change → 到这里 → 再同步回网格，是闭环且幂等的。）
            syncGrid(root, island, anchor);
          }
        });
        // ★ v2.3.2：把省份 Tab ＋ 城市网格接到 select 上（在升级之前绑定即可 ——
        //   格子是服务端渲染的，不随 upgradeSelect 变化）。
        buildGrid(root, sel);

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
          locate(function (hit) {
            if (!hit) {
              setStatus(root, '定位失败（接口不可达或被浏览器拦截），已保持当前观测地。');
              return;
            }
            var n = nearest(island, hit.lat, hit.lon);
            if (!n) { setStatus(root, '定位失败，已保持当前观测地。'); return; }
            manual = true;   // 用户主动点过，视为显式选择
            if (!apply(root, island, n.key)) { return; }
            if (sel) {
              if (sel.querySelector('option[value="' + n.key + '"]')) { sel.value = n.key; }
            }
            // v2.3.2：定位结果也要回写网格（否则格子还亮在原城，界面自相矛盾）
            syncGrid(root, island, n.key);
            setStatus(root, '已按访问位置选最近的预置观测地：'
              + island.index[n.key][F_CN] + '（直线距离约 ' + n.km + ' 千米）。');
          });
        });
      }

      if (island.mode === 'auto') { autoRoots.push(root); }
    });

    if (!autoRoots.length) { return; }
    locate(function (hit) {
      if (!hit) {
        Array.prototype.forEach.call(autoRoots, function (root) {
          setStatus(root, '未能自动定位，已按默认观测地显示；可在上方下拉里改选。');
        });
        return;
      }
      Array.prototype.forEach.call(autoRoots, function (root) {
        var island = parseIsland(root);
        if (!island) { return; }
        var n = nearest(island, hit.lat, hit.lon);
        if (!n) { return; }
        var sel = root.querySelector('.kcj-astro-place-select');
        var opted = false;
        if (sel) {
          opted = sel.getAttribute('data-kcj-upgraded') === '1';
        }
        if (!apply(root, island, n.key)) { return; }
        if (sel) {
          if (sel.querySelector('option[value="' + n.key + '"]')) { sel.value = n.key; }
        }
        // v2.3.2：自动定位结果回写网格（同上）
        syncGrid(root, island, n.key);
        // 说明句要区分「下拉已升级为全国县级」与「只有锚点」两种情况，
        // 否则读者会以为「我所在的区县没被收录」。
        var tail = opted
          ? '；可展开下拉改选到市/县/区。'
          : '；可手动改选。';
        setStatus(root, '已按访问位置选最近的预置观测地：'
          + island.index[n.key][F_CN] + '（直线距离约 ' + n.km + ' 千米）' + tail);
      });
    });
  }

  ready(init);
})();
