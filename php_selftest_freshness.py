#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
严律二「全站时间戳」专测桩（v2.3.25 · 2026-09-25 立）

为什么单独成一件，而不并进 php_selftest.py：
  ① 那个桩的职责是「哪一个上下文该出哪个 @type」，加载面只到 rankmath.php；
     本件测的是**正文过滤器**（the_content），加载面是 compliance.php，两者
     共用桩会互相污染 `the_content` 钩子队列。
  ② 它已 54/54 稳定，改它有回归风险；本件用例全新增，零触碰既有断言。

用法：
  python php_selftest_freshness.py
  python php_selftest_freshness.py --json

★ 本件的自咬点（写之前先想清楚，避免「判据把文档自己算了进去」）：
  · 判据不得用「输出里含某字符串」来判「该不该加」——
    因为**时间戳行本身**就含「最后修订时间」，会让「不加」的用例假红。
    ⇒ 一律用 `substr_count($out, '最后修订时间：')` 的**计数**判，0 = 未加、1 = 加了一份。
  · 「全站默认开」的负控制必须是**能报红**的：一个既无标记、也不在名单、
    也不是 classic-book 的普通页 → 期望**加**。若把源码改回 `return false`，
    这条必红 —— 这就是全站改造的验收点。
★ v2.3.26 增补（2026-09-26）：新增 B6—B8 三例 —— **索引页**（父索引
  `/classic-book/` 与语言索引 `/classic-book/en|zh/`）必须**加**时间戳。
  三例在改源码**之前**先跑一遍，确认**报红** —— 证明本判据抓得住
  「索引页被误排」这一缺陷，不是事后补一条永远绿的断言。
  （原文子页 `/classic-book/<slug>/` 仍应排除，见 B3／B5；那条是负控制。）

"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.join(HERE, "wp-astro-forecast")

# ── 最小 WP 桩：只实现 compliance.php 真正调用到的 API ─────────────────────────
HARNESS = r"""<?php
define('ABSPATH', __DIR__);
define('KCJ_ASTRO_CPT', 'astro_event');
define('KCJ_ASTRO_TAX', 'event_type');
define('KCJ_ASTRO_SLUG', 'sky-forecast');
define('KCJ_ASTRO_PATH', getenv('KCJ_PLUGIN_DIR') . '/');

$GLOBALS['kcj_hooks'] = ['the_content' => []];
$GLOBALS['kcj_opts']  = json_decode(getenv('KCJ_OPTS') ?: '{}', true);
$GLOBALS['kcj_case']  = getenv('KCJ_CASE');
$GLOBALS['kcj_id']    = (int) (getenv('KCJ_ID') ?: 0);
$GLOBALS['kcj_link']  = getenv('KCJ_LINK') ?: '';
$GLOBALS['kcj_isadm'] = (getenv('KCJ_ISADMIN') === '1');

function add_filter($tag, $cb, $prio = 10, $args = 1) {
    $GLOBALS['kcj_hooks'][$tag][] = ['cb' => $cb, 'prio' => $prio, 'args' => $args];
}
function add_action($tag, $cb, $prio = 10, $args = 1) {
    add_filter($tag, $cb, $prio, $args);
}
function is_admin() { return $GLOBALS['kcj_isadm']; }
function is_feed() { return false; }
function is_embed() { return false; }
function get_the_ID() { return $GLOBALS['kcj_id'] ?: false; }
function get_permalink($id = 0) { return $GLOBALS['kcj_link']; }
function home_url($p = '') { return 'https://kuangchujia.com' . $p; }
function esc_html($s) { return htmlspecialchars((string) $s, ENT_QUOTES, 'UTF-8'); }
function esc_attr($s) { return htmlspecialchars((string) $s, ENT_QUOTES, 'UTF-8'); }
function sanitize_text_field($s) { return is_string($s) ? trim($s) : ''; }
function get_post_field($f, $id) { return ''; }
function has_shortcode($c, $t) { return strpos((string) $c, '[' . $t) !== false; }
function is_singular($t = '') { return false; }
function is_post_type_archive($t = '') { return false; }
function is_tax($t = '') { return false; }
/* 选项层：把 env 传进来的 JSON 当作 get_option 的返回值。
   ★ 必须**真的**从 $GLOBALS 取，不得直接返回默认值 —— 否则「名单列入」用例
     永远测不到（会变成恒真的假绿）。 */
function get_option($k, $d = false) {
    /* ★ v2.3.25 修桩（第一次跑 B1 报红的真因）：
       真实链路是 kcj_astro_opt($key, $default) → get_option('kcj_astro_options', array())[$key]。
       原桩把 env 里的**裸键**直接当 get_option 的键 ⇒ 排除名单压根读不到，
       B1「排除名单命中」必然假红 —— 报红的是桩，不是代码。
       ⇒ 这里把 env 的裸键包一层，还原成真实的选项数组形态。 */
    if ($k === 'kcj_astro_options') {
        $o = isset($GLOBALS['kcj_opts']) && is_array($GLOBALS['kcj_opts'])
           ? $GLOBALS['kcj_opts'] : array();
        return array_merge((array) $d, $o);
    }
    return array_key_exists($k, $GLOBALS['kcj_opts']) ? $GLOBALS['kcj_opts'][$k] : $d;
}
/* ⚠ 此处**不得**定义 kcj_astro_opt() —— compliance.php 自己就定义了它
   （v2.3.25 实测：桩里重复定义 ⇒ 直接 Fatal error，15 例全挂）。
   真实环境里它由本文件定义，桩只需提供它依赖的 get_option()。
   教训：桩要把「前提」摆齐，但**不能替插件实现它自己的函数**。 */

require getenv('KCJ_PLUGIN_DIR') . '/includes/compliance.php';

/* 依优先级稳排后，逐个跑 the_content 过滤器 —— 与真实 WP 同序 */
$hooks = $GLOBALS['kcj_hooks']['the_content'];
usort($hooks, function ($a, $b) { return $a['prio'] <=> $b['prio']; });

$content = getenv('KCJ_CONTENT');
$content = str_replace('\n', "\n", $content);
foreach ($hooks as $h) {
    $content = call_user_func($h['cb'], $content);
}

$sig = '最后修订时间：';
echo json_encode([
    'case'      => $GLOBALS['kcj_case'],
    'out'       => $content,
    'count'     => substr_count($content, $sig),
    'at_head'   => (strpos($content, $sig) === 0) || (strpos($content, $sig) !== false && strpos($content, $sig) < 40),
    'marker_kept' => (strpos($content, '<!-- kcj-fresh -->') !== false),
    'len'       => strlen($content),
], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES), "\n";
"""

# ── 用例：(名称, ID, permalink, opts, content, 期望加?, 说明) ──────────────────
CASES = [
    # ---- ① 全站默认开（本次改造的核心验收点） ----
    ("A1 普通页 /about/ 无声明", 13, "https://kuangchujia.com/about/", {},
     "<p>正文</p>", True,
     "★ 改造点：未命中任何声明 ⇒ 默认加"),

    ("A2 首页", 36, "https://kuangchujia.com/", {},
     "<p>正文</p>", True,
     "首页属全站面"),

    ("A3 栏目父页", 74, "https://kuangchujia.com/calendar-reform/", {},
     "<p>正文</p>", True,
     "栏目页属全站面"),

    # ---- ② 两维排除 ----
    ("B1 排除名单命中（ID=74）", 74, "https://kuangchujia.com/calendar-reform/",
     {"freshness_exclude_ids": "74,99"},
     "<p>正文</p>", False,
     "★ 排除优先：即便默认全开，名单命中即不加"),

    ("B2 排除名单未命中（ID=75）", 75, "https://kuangchujia.com/calendar-reform/",
     {"freshness_exclude_ids": "74,99"},
     "<p>正文</p>", True,
     "负控制：排除名单不得误伤同路径的其他 ID"),

    ("B3 古籍原文子页", 1200, "https://kuangchujia.com/classic-book/yaodian/", {},
     "<p>古籍原文</p>", False,
     "★ classic-book 默认排除：原文未被「修订」，加时间戳属失真"),

    ("B4 负控制：路径含 classic-book 但非顶层段", 1300,
     "https://kuangchujia.com/papers/classic-book-notes/", {},
     "<p>正文</p>", True,
     "★ 判据只认顶层段 = classic-book，用「子串即可」会误伤（负控制）"),

    ("B5 classic-book 子页但在排除名单外仍排除", 1400,
     "https://kuangchujia.com/classic-book/shangshu/", {},
     "<p>古籍原文</p>", False,
     "两条排除路径并存"),

    # ---- ②b v2.3.26：索引页必须「加」（原判据把它们与原文子页混为一谈） ----
    ("B6 索引父页 /classic-book/", 700, "https://kuangchujia.com/classic-book/", {},
     "<p>索引</p>", True,
     "★ v2.3.26：顶层段命中 ≠ 原文子页 —— 一段路径是父索引页，要带时间戳"),

    ("B7 索引语言页 /classic-book/zh/", 702, "https://kuangchujia.com/classic-book/zh/", {},
     "<p>索引</p>", True,
     "★ v2.3.26：语言索引页要带时间戳（第二段 = zh）"),

    ("B8 索引语言页 /classic-book/en/", 701, "https://kuangchujia.com/classic-book/en/", {},
     "<p>索引</p>", True,
     "★ v2.3.26：语言索引页要带时间戳（第二段 = en）"),

    # ---- ③ 向后兼容（v2.3.24 行为不得丢） ----
    ("C1 页面自我声明标记", 500, "https://kuangchujia.com/somewhere/", {},
     "<p>正文</p>\n<!-- kcj-fresh -->\n<p>更多</p>", True,
     "A 路标记仍生效"),

    ("C2 标记必须被抹掉（不留在读者可见 HTML）", 500, "https://kuangchujia.com/somewhere/", {},
     "<p>正文</p>\n<!-- kcj-fresh -->\n<p>更多</p>", True,
     "输出不得含 kcj-fresh 注释（判据见 marker_kept）"),

    ("C3 名单列入（freshness_page_ids）", 600, "https://kuangchujia.com/p/", 
     {"freshness_page_ids": "600"},
     "<p>正文</p>", True,
     "B 路名单仍生效"),

    # ---- ④ 幂等 ----
    ("D1 正文已含时间戳 ⇒ 不重复", 700, "https://kuangchujia.com/p/", {},
     "<p class=\"kcj-astro-freshness\">最后修订时间：2026年9月25日</p>\n<p>正文</p>", True,
     "★ 幂等：计数须为 1"),

    # ---- ⑤ 负控制：与时间戳无关的注入面不得被带进来 ----
    ("E1 后台不注入", 13, "https://kuangchujia.com/about/", {},
     "<p>正文</p>", False,
     "is_admin ⇒ 让位"),
]

EXPECT = {}  # name -> (加?, marker_kept?)

for name, _id, _link, _opt, _c, want, _note in CASES:
    pass


def run_case(php, case):
    name, pid, link, opts, content, want, note = case
    env = dict(os.environ)
    env.update({
        "KCJ_CASE": name,
        "KCJ_ID": str(pid),
        "KCJ_LINK": link,
        "KCJ_OPTS": json.dumps(opts, ensure_ascii=False),
        "KCJ_CONTENT": content,
        "KCJ_PLUGIN_DIR": PLUGIN_DIR,
        "KCJ_ISADMIN": "1" if name.startswith("E1") else "0",
    })
    with tempfile.NamedTemporaryFile("w", suffix=".php", delete=False,
                                     encoding="utf-8", newline="") as f:
        f.write(HARNESS)
        hp = f.name
    try:
        p = subprocess.run([php, hp], capture_output=True, text=True,
                           env=env, encoding="utf-8", errors="replace")
        if p.returncode != 0:
            return None, (p.stdout or "") + (p.stderr or "")
        # 取最后一行 JSON（PHP 警告可能先于它）
        line = ""
        for ln in reversed((p.stdout or "").splitlines()):
            if ln.strip().startswith("{"):
                line = ln.strip()
                break
        if not line:
            return None, (p.stdout or "") + (p.stderr or "")
        return json.loads(line), ""
    finally:
        try:
            os.unlink(hp)
        except OSError:
            pass


def find_php(explicit=None):
    if explicit and os.path.isfile(explicit):
        return explicit
    if os.environ.get("PHP_BIN") and os.path.isfile(os.environ["PHP_BIN"]):
        return os.environ["PHP_BIN"]
    import glob as _g
    for pat in ("~/.workbuddy/binaries/php/*/php.exe",
                "~/.workbuddy/binaries/php/*/bin/php"):
        for c in sorted(_g.glob(os.path.expanduser(pat))):
            if os.path.isfile(c):
                return c
    import shutil as _s
    return _s.which("php")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--php")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    php = find_php(a.php)
    if not php:
        print("!! 未找到 php 可执行文件")
        return 2

    checks = []

    def chk(label, ok, detail=""):
        checks.append({"label": label, "ok": bool(ok), "detail": detail})

    # 语法闸（本品两文件）
    for f in ("includes/compliance.php", "wp-astro-forecast.php"):
        p = os.path.join(PLUGIN_DIR, f)
        r = subprocess.run([php, "-l", p], capture_output=True, text=True)
        chk("语法闸 %s" % f, r.returncode == 0, (r.stdout or "").strip())

    results = []
    for case in CASES:
        name, pid, link, opts, content, want, note = case
        data, err = run_case(php, case)
        if data is None:
            chk(name, False, "PHP 执行失败: " + err[:300])
            continue
        got = data["count"] > 0
        if name.startswith("C2"):
            # 该例判「标记被抹掉」
            chk(name, data["marker_kept"] is False,
                "marker_kept=%s" % data["marker_kept"])
        elif name.startswith("D1"):
            # 幂等：计数须恰为 1
            chk(name, data["count"] == 1, "count=%d（须为 1）" % data["count"])
        elif name.startswith("E1"):
            chk(name, not got, "count=%d" % data["count"])
        else:
            chk(name, got == want,
                "期望%s、实得 count=%d" % ("加" if want else "不加", data["count"]))
        results.append({"case": name, "want": want, "count": data["count"], "note": note})
        # 位置闸：凡「加」的用例，时间戳须在最顶部
        if want and got and not name.startswith("D1"):
            chk(name + " · 时间戳在最顶部", data["at_head"],
                "位置偏移=%s" % data["out"][:60].replace("\n", "\\n"))

    if a.json:
        print(json.dumps({"checks": checks}, ensure_ascii=False, indent=2))
    else:
        for c in checks:
            print("%s %s%s" % ("PASS" if c["ok"] else "FAIL", c["label"],
                               ("  [" + c["detail"] + "]") if (not c["ok"] and c["detail"]) else ""))
        good = sum(1 for c in checks if c["ok"])
        print("-" * 72)
        print("通过 %d / %d" % (good, len(checks)))
    return 0 if all(c["ok"] for c in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
