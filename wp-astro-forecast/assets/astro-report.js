/**
 * 报告与历史天象的「下载留档」（v2.0.0）
 *
 * 为什么放在**外部资源**里而不是模板内联
 * ──────────────────────────────────────
 * 本站正文会经平台后处理：正文里的空行会被换成块级标签、某些窗口内的**裸与号字符**
 * 会被换成实体引用，而 <script> 内容不做实体解码 ⇒ 内联脚本的字符串被拆断、整块失效
 * （本项目 v1.3.0 的「老黄历线上失效」就是这个原因）。放进 assets/ 由浏览器按静态资源
 * 取用，完全不经正文后处理 —— 从根上避开这一类坑。
 *
 * 纪律：本文件**不出现裸与号字符**（逻辑一律用嵌套 if），取 JSON 用 textContent + JSON.parse。
 *
 * 处理两类节点：
 *   .kcj-astro-report[data-kcj-period]  → script.kcj-astro-report-json
 *   .kcj-astro-history                  → script.kcj-astro-history-json
 * 按钮： data-kcj-dl="md|csv|print"
 */
(function () {
  'use strict';

  function escCell(s) {
    if (!s) { return ''; }
    return String(s).replace(/\|/g, '\\|').replace(/\r?\n/g, ' ');
  }

  function csvCell(s) {
    var v = (s === null || s === undefined) ? '' : String(s);
    v = v.replace(/"/g, '""');
    return '"' + v + '"';
  }

  function csvBlock(header, items, mapper) {
    var L = [header.map(csvCell).join(',')];
    for (var i = 0; i < items.length; i += 1) {
      L.push(mapper(items[i]).map(csvCell).join(','));
    }
    return '\ufeff' + L.join('\r\n');
  }

  function save(name, text, mime) {
    var blob = new Blob([text], { type: mime });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
  }

  function safeName(s) {
    return String(s).replace(/[\\/:*?"<>|\s]+/g, '_').slice(0, 80);
  }

  /* ------------------------------ 报告 ------------------------------ */

  function reportMd(d) {
    var L = [];
    L.push('# ' + d.title);
    L.push('');
    L.push('- 期间：' + d.start + ' 起，至 ' + d.end + ' 止（含首不含尾）');
    L.push('- 条目数：' + d.items.length);
    L.push('- 生成时间：' + d.generated + '（北京时）');
    L.push('- 口径：星历 DE421 预计算；时刻为北京时间（UTC+8）与地心量，与观测地无关');
    if (d.site) { L.push('- 出处：' + d.site); }
    L.push('');
    L.push('| 时间（北京时） | 类型 | 天象 | 说明 |');
    L.push('| --- | --- | --- | --- |');
    for (var i = 0; i < d.items.length; i += 1) {
      var it = d.items[i];
      L.push('| ' + it.time + ' | ' + it.tcn + ' | ' + escCell(it.title) + ' | ' + escCell(it.sum) + ' |');
    }
    L.push('');
    L.push('> 本报告由程序依星历预计算结果汇总生成，非人工观测记录，不构成观测保证，');
    L.push('> 不涉及星占、谶纬、吉凶解读。');
    L.push('');
    return L.join('\n');
  }

  function reportCsv(d) {
    return csvBlock(['时间（北京时）', '类型', '天象', '说明', '方法'], d.items, function (it) {
      return [it.time, it.tcn, it.title, it.sum, it.meth];
    });
  }

  /* -------------------------- 历史上今日天象 -------------------------- */

  function historyMd(d) {
    var L = [];
    L.push('# 历史上 ' + d.mmdd + ' 的天象');
    L.push('');
    L.push('- 回溯段：' + d.from + ' — ' + d.before + ' 年');
    L.push('- 条目数：' + d.items.length);
    L.push('- 口径：**星历回算**（非史料抄录）；月食为自算，日食照录 NASA GSFC 目录');
    L.push('');
    L.push('| 年份 | 类型 | 时刻（北京时） | 天象 | 说明 |');
    L.push('| --- | --- | --- | --- | --- |');
    for (var i = 0; i < d.items.length; i += 1) {
      var it = d.items[i];
      L.push('| ' + it.y + ' | ' + it.tcn + ' | ' + it.time + ' | ' + escCell(it.title)
        + ' | ' + escCell(it.sum) + ' |');
    }
    L.push('');
    L.push('> 史料记载与星历回算不是一回事：本表是后者。凡逐字核录过出处的史料条目，');
    L.push('> 另见站内「历史天象」类目下的专条。');
    L.push('');
    return L.join('\n');
  }

  function historyCsv(d) {
    return csvBlock(['年份', '类型', '时刻（北京时）', '天象', '说明', '时刻不确定度', '方法'],
      d.items, function (it) {
        return [it.y, it.tcn, it.time, it.title, it.sum, it.unc, it.meth];
      });
  }

  /* ------------------------------ 装配 ------------------------------ */

  function wire(root, scriptSel, base, md, csv) {
    var el = root.querySelector(scriptSel);
    if (!el) { return; }
    var d = null;
    try { d = JSON.parse(el.textContent); } catch (e) { return; }
    if (!d) { return; }
    var btns = root.querySelectorAll('[data-kcj-dl]');
    Array.prototype.forEach.call(btns, function (b) {
      b.addEventListener('click', function () {
        var k = b.getAttribute('data-kcj-dl');
        if (k === 'md') { save(base + '.md', md(d), 'text/markdown;charset=utf-8'); return; }
        if (k === 'csv') { save(base + '.csv', csv(d), 'text/csv;charset=utf-8'); return; }
        if (k === 'print') { window.print(); return; }
      });
    });
  }

  function init() {
    var reps = document.querySelectorAll('.kcj-astro-report[data-kcj-period]');
    Array.prototype.forEach.call(reps, function (root) {
      var el = root.querySelector('script.kcj-astro-report-json');
      if (!el) { return; }
      var name = '天象报告';
      try {
        var d = JSON.parse(el.textContent);
        if (d) {
          if (d.title) { name = safeName(d.title); }
        }
      } catch (e2) { /* 取不到标题时用兜底文件名 */ }
      wire(root, 'script.kcj-astro-report-json', name, reportMd, reportCsv);
    });

    var hists = document.querySelectorAll('.kcj-astro-history');
    Array.prototype.forEach.call(hists, function (root) {
      wire(root, 'script.kcj-astro-history-json',
        '历史上今日天象', historyMd, historyCsv);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
    return;
  }
  init();
})();
