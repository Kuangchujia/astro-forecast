#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
live_verify.py —— 线上验收（上传新版之后跑这一条）

为什么需要它
------------
`verify_package.py` 查的是「包内一致」，`php_selftest.py` 查的是「PHP 层逻辑」，
两者都**跑在本机**，都**碰不到线上**。于是「包对了 ≠ 线上对了」这一段长期没有判据：
2026-09-23 上一轮就出现过「面板里 Schema Type 选了 Event，前台却一条 JSON-LD 都不输出」
（F37，根因是 Rank Math 免费版 `get_default_schema_type()` 的白名单）。
本脚本补的就是这一段：**只看线上产物，不看本机文件**。

跑法
----
    python live_verify.py
    python live_verify.py --base https://kuangchujia.com --json live.json

需要凭据的那一项（插件版本号）走环境变量，没有就记 SKIP 并明说 —— 不假装通过：

    KCJ_WP_USER=<用户名> KCJ_WP_APP_PASSWORD='<应用程序密码>' python live_verify.py

判据（对外件报红即拦退）
------------------------
A 插件版本号        health 端点 `plugin` 是否等于 --expect-version（默认 1.3.0）
B sitemap 索引      **查询式** `?sitemap=1` 是否列出 `astro_event-sitemap.xml`（＝ 该类型是否已启用）
C 事件 sitemap      **查询式** `?sitemap=<CPT>` 是否生成且 `<loc>` 非空
B2 sitemap 路由     **路径式** `/sitemap_index.xml` 与 `/<CPT>-sitemap.xml` 是否 200
                    （★ 查询式通、路径式不通 ⇒ 重写规则没刷；两条都不通 ⇒ 模块／类型没开。
                     两条入口分开查，是因为**结论与修法完全不同**，合并成一条会指错方向）
D 事件页 Event      事件详情页是否都出 `Event` 节点
E startDate 时区    `startDate` 是否都以 `+08:00` 结尾
F 站点级实体        事件页是否都还有 `WebSite` + `WebPage`（F37 连带丢的那批）
G 坏 Dataset       全站（sitemap 全页 + 已知关键页）是否都不出现空日期 Dataset
H 正向 Dataset      含短代码的页面是否**仍**出完好的 Dataset（防守卫过度抑制）
I 归档页类型        事件归档页是否为 `CollectionPage`

两条硬规矩
----------
1. **空集守卫**：任一扫描面取到 0 条，一律报红。取不到 ≠ 通过。
   （本库踩过：备份件挪了目录 ⇒ 扫描根失效 ⇒ 扫到 0 件却报「全达标」。）
2. **破缓存**：每条 URL 都带随机查询串 + `Cache-Control: no-cache`，取页失败重试 3 次。
"""

import argparse
import base64
import json
import os
import random
import re
import ssl
import sys
import time
import urllib.error
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LD_PAT = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S
)
LOC_PAT = re.compile(r"<loc>\s*([^<]+?)\s*</loc>")
UA = "Mozilla/5.0 (compatible; kcj-live-verify/1.0)"

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


# ---------------------------------------------------------------- HTTP

def _bust(url):
    """随机查询串破缓存。★ 必须按有无 ? 分别拼，否则会把路径拼坏（本轮踩过，79 条假红）。"""
    sep = "&" if "?" in url else "?"
    return "%s%s_=%d" % (url, sep, random.randint(1, 10 ** 9))


def fetch(url, auth=None, tries=3, timeout=60):
    """取页。返回 (body_text, status, err)。取到就返回，取不到也把最后一次的原因带回。"""
    last = None
    for i in range(tries):
        req = urllib.request.Request(_bust(url), headers={
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": UA,
        })
        if auth:
            req.add_header("Authorization", "Basic " + auth)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
                return r.read().decode("utf-8", "replace"), r.getcode(), None
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")
            except Exception:
                pass
            if e.code in (401, 403, 404):
                return body, e.code, None          # 确定性状态码，不重试
            last = "HTTP %s" % e.code
        except Exception as e:                      # noqa: BLE001
            last = "%s: %s" % (type(e).__name__, e)
        if i < tries - 1:
            time.sleep(1.2)
    return None, None, last


def graph_of(html):
    """把一页里所有 ld+json 块摊平成节点列表。解析不了的块不静默丢，单独计数。"""
    nodes, broken = [], 0
    for raw in LD_PAT.findall(html):
        try:
            data = json.loads(raw.strip())
        except Exception:                           # noqa: BLE001
            broken += 1
            continue
        g = data.get("@graph") if isinstance(data, dict) else data
        if g is None:
            g = [data]
        if isinstance(g, dict):
            g = [g]
        for n in g:
            if isinstance(n, dict):
                nodes.append(n)
    return nodes, broken


def type_of(node):
    t = node.get("@type")
    if isinstance(t, list):
        return "/".join(str(x) for x in t)
    return str(t) if t else ""


def is_bad_dataset(node):
    """空日期数据集的特征：名字里出现空括号，或 temporalCoverage 缺失/为空。"""
    name = str(node.get("name") or "")
    tc = node.get("temporalCoverage")
    return ("（）" in name) or (not tc)


# ---------------------------------------------------------------- 报告

class Report(object):
    def __init__(self, as_json=False):
        self.rows = []
        self.as_json = as_json

    def chk(self, cid, title, ok, detail="", skipped=False):
        self.rows.append({
            "id": cid, "title": title,
            "status": "SKIP" if skipped else ("PASS" if ok else "FAIL"),
            "detail": detail,
        })
        if not self.as_json:
            mark = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭"}[
                "SKIP" if skipped else ("PASS" if ok else "FAIL")
            ]
            print("%s [%s] %s" % (mark, cid, title))
            for line in (detail or "").splitlines():
                if line.strip():
                    print("        " + line)

    @property
    def failed(self):
        return [r for r in self.rows if r["status"] == "FAIL"]


# ---------------------------------------------------------------- 各面

def check_health(base, rep, expect_version, auth):
    url = base + "/wp-json/kcj-astro/v1/health"
    body, code, err = fetch(url, auth=auth, tries=2)
    if body is None:
        rep.chk("A", "插件版本号（health 端点）", False, "取不到：%s" % err)
        return
    if code in (401, 403) or not auth:
        rep.chk(
            "A", "插件版本号（health 端点）", False,
            "未带凭据 ⇒ HTTP %s。这一项需要应用程序密码，请用：\n"
            "  KCJ_WP_USER=<用户名> KCJ_WP_APP_PASSWORD='<应用程序密码>' python live_verify.py\n"
            "★ 拿不到版本号时，其余各项仍可判定「行为对不对」，但分不清「包没生效」与「改了没用」。" % code,
            skipped=True,
        )
        return
    try:
        d = json.loads(body)
    except Exception as e:                          # noqa: BLE001
        rep.chk("A", "插件版本号（health 端点）", False, "JSON 解析失败：%s" % e)
        return
    got = str(d.get("plugin") or "")
    rep.chk("A", "插件版本号（health 端点）", got == expect_version,
            "线上 %r ／ 预期 %r%s" % (got, expect_version,
                                    "" if got == expect_version else "  ⇒ 新包没生效，别对旧包排查"))


def check_sitemaps(base, rep, rest_base):
    """生成侧（查询式）与路由侧（路径式）**分开查** —— 两者的结论与修法完全不同。

    判别法（2026-09-23 实测得出）：
      · 查询式通、路径式不通 ⇒ **重写规则没进 `rewrite_rules`**（Rank Math 的 sitemap 路由丢了）；
        内容与模块都正常，缺的是一次 flush。修法：`设置 → 固定链接` 直接点「保存更改」。
      · 两条都不通 ⇒ 生成侧有问题（Sitemap 模块没开 / 该类型未启用）。
      · 两条都通 ⇒ ✅。
    Google 抓的是**路径式**（robots.txt 里写的就是 `/sitemap_index.xml`），所以路径式必须通。
    """
    # —— 生成侧：查询式（不受重写规则影响） ——
    q_index, _, err_i = fetch(base + "/?sitemap=1")
    listed = LOC_PAT.findall(q_index) if q_index else []
    rep.chk("B", "sitemap 索引·查询式 `?sitemap=1` 列出事件 sitemap",
            any("astro_event-sitemap" in l for l in listed),
            "索引 %d 条：%s" % (len(listed), ", ".join(l.rsplit("/", 1)[-1] for l in listed))
            if listed else "取不到或为空（%s）" % (err_i or "空文档"))

    q_ev, code_e, _ = fetch(base + "/?sitemap=" + rest_base)
    n_ev = len(LOC_PAT.findall(q_ev)) if q_ev else 0
    rep.chk("C", "事件 sitemap·查询式可生成且非空", n_ev > 0,
            "`?sitemap=%s` → HTTP %s，%d 条 <loc>" % (rest_base, code_e, n_ev))

    # —— 路由侧：路径式（搜索引擎真正抓的形态） ——
    _, cpi, _ = fetch(base + "/sitemap_index.xml")
    _, cpe, _ = fetch(base + "/" + rest_base + "-sitemap.xml")
    ok_path = (cpi == 200 and cpe == 200)
    if ok_path:
        why = ""
    elif n_ev > 0:
        why = ("\n★ 判别：**查询式通、路径式不通** ⇒ 模块与生成都正常，缺的是 **WordPress 重写规则**"
               "（Rank Math 的 sitemap 路由没进 `rewrite_rules`）。\n"
               "   修法（按顺序）：① `设置 → 固定链接` 页面**直接点「保存更改」**（什么都不改，就是 flush 重写规则）；\n"
               "   ② 仍不通 → `Rank Math → Dashboard → Database Tools` 清一次 **sitemap 缓存**；③ 复跑本脚本。\n"
               "   ⚠ 这一步不做，搜索引擎拿不到**任何** sitemap（robots.txt 里写的就是这两个路径）。")
    else:
        why = ("\n★ 判别：**查询式也不通** ⇒ 问题在生成侧 —— 看 `Rank Math → Dashboard → Modules` 的 "
               "Sitemap 模块是否开启；或该类型未启用。")
    rep.chk("B2", "sitemap 漂亮路径可达（路由侧）", ok_path,
            "`/sitemap_index.xml` → %s ／ `/%s-sitemap.xml` → %s%s" % (cpi, rest_base, cpe, why))


def event_links(base, rest_base, rep):
    links, page = [], 1
    while True:
        url = "%s/wp-json/wp/v2/%s?per_page=100&page=%d&_fields=link" % (base, rest_base, page)
        body, code, err = fetch(url, tries=2)
        if body is None:
            if page == 1:
                rep.chk("D0", "取事件页清单（REST）", False,
                        "取不到：%s\n（REST 面不通时，本脚本无法全量验收 ⇒ 报红，不静默跳过）" % err)
            break
        try:
            batch = json.loads(body)
        except Exception:                           # noqa: BLE001
            break
        if not isinstance(batch, list) or not batch:
            break
        links += [b["link"] for b in batch if isinstance(b, dict) and b.get("link")]
        if len(batch) < 100:
            break
        page += 1
    return links


def check_event_pages(links, rep):
    if not links:
        rep.chk("D", "事件详情页都出 Event", False,
                "清单为空 ⇒ 空集守卫报红（取不到 ≠ 通过）")
        rep.chk("E", "startDate 都带 +08:00", False, "同上，空集")
        rep.chk("F", "事件页都有站点级实体", False, "同上，空集")
        return
    no_ev, no_tz, no_glob, broken_blocks, errs = [], [], [], 0, []
    for u in links:
        html, code, err = fetch(u, tries=3)
        if html is None:
            errs.append("%s（%s）" % (u, err))
            continue
        nodes, broken = graph_of(html)
        broken_blocks += broken
        types = [type_of(n) for n in nodes]
        ev = next((n for n in nodes if type_of(n) == "Event"), None)
        if ev is None:
            no_ev.append("%s（节点：%s）" % (u, ", ".join(t for t in types if t) or "无"))
            continue
        sd = str(ev.get("startDate") or "")
        if not sd.endswith("+08:00"):
            no_tz.append("%s（startDate=%r）" % (u, sd))
        if "WebSite" not in types or "WebPage" not in types:
            no_glob.append("%s（%s）" % (u, ", ".join(t for t in types if t)))
        time.sleep(0.2)
    n = len(links)
    rep.chk("D", "事件详情页都出 Event", not no_ev and not errs and n > 0,
            "通过 %d/%d%s%s" % (n - len(no_ev) - len(errs), n,
                                "" if not errs else "\n取页失败 %d：%s" % (len(errs), "; ".join(errs[:5])),
                                "" if not no_ev else "\n无 Event %d：%s" % (len(no_ev), "; ".join(no_ev[:5]))))
    rep.chk("E", "startDate 都带 +08:00", not no_tz and n > 0,
            "异常 %d：%s" % (len(no_tz), "; ".join(no_tz[:5]) or "无"))
    rep.chk("F", "事件页都有站点级实体（WebSite+WebPage）", not no_glob and n > 0,
            "缺失 %d：%s" % (len(no_glob), "; ".join(no_glob[:5]) or "无"))
    if broken_blocks:
        rep.chk("F2", "所有 ld+json 块都能解析", False,
                "有 %d 个块 JSON 解析失败（多半是平台后处理拆断了字符串）" % broken_blocks)


def sitemap_urls(base):
    """取 sitemap 索引 → 展开子 sitemap 的全部 URL。返回 (urls, 来源说明)。

    ★ 两条入口都要试：路径式（Google 抓的形态）不通时回落**查询式**，
    并把子 sitemap 的文件名翻译成 `?sitemap=<name>` —— 否则索引里那些漂亮 URL 同样 404，
    清单会**无声缩水**，后面的「全站无坏 Dataset」就变成「2 页无坏 Dataset」的假绿。
    """
    for label, idx in (("路径式 `/sitemap_index.xml`", base + "/sitemap_index.xml"),
                       ("查询式 `/?sitemap=1`", base + "/?sitemap=1")):
        body, code, _ = fetch(idx)
        if code != 200 or not body:
            continue
        subs = LOC_PAT.findall(body)
        if not subs:
            continue
        urls = []
        for s in subs:
            name = s.rsplit("/", 1)[-1]
            if name.endswith("-sitemap.xml"):
                name = name[:-len("-sitemap.xml")]
            sub, c2, _ = fetch(s)
            if c2 != 200 or not sub:
                sub, c2, _ = fetch("%s/?sitemap=%s" % (base, name))
            if c2 == 200 and sub:
                urls += LOC_PAT.findall(sub)
        if urls:
            return list(dict.fromkeys(urls)), "%s｜%d 个子 sitemap" % (label, len(subs))
    return [], "两条索引入口都取不到（扫描面为 0）"


# ★ 扫描面下限：2026-09-23 实测正常面约 21 页（4 个子 sitemap 展开）。
#   低于此数说明索引拿不到、清单缩水 ⇒ 必须报红。**缩水的扫描面比没有扫描面更危险**：
#   它会给出一片「全绿」，而那片绿只是「没扫到」。
MIN_SCAN_PAGES = 15


def check_datasets(base, rep, extra_pages, expect_good_pages):
    urls, src = sitemap_urls(base)
    urls += [base + p for p in extra_pages]
    urls = list(dict.fromkeys(urls))
    surface_ok = len(urls) >= MIN_SCAN_PAGES
    if not urls:
        rep.chk("G", "全站无空日期 Dataset", False,
                "URL 清单为空 ⇒ 空集守卫报红（取不到 ≠ 通过）；%s" % src)
        rep.chk("H", "含短代码的页面仍出完好 Dataset", False, "同上，空集")
        return
    bad, good_found, errs = [], [], []
    for u in urls:
        html, code, err = fetch(u, tries=2)
        if html is None:
            errs.append("%s（%s）" % (u, err))
            continue
        nodes, _ = graph_of(html)
        ds = [n for n in nodes if type_of(n) == "Dataset"]
        for n in ds:
            if is_bad_dataset(n):
                bad.append("%s（name=%r temporalCoverage=%r）" % (u, n.get("name"), n.get("temporalCoverage")))
        if ds and not any(is_bad_dataset(n) for n in ds):
            good_found.append(u)
        time.sleep(0.2)
    detail = "扫描面 %d 页（%s）；坏 Dataset %d%s" % (
        len(urls), src, len(bad),
        "" if not errs else "；取页失败 %d" % len(errs),
    )
    if not surface_ok:
        detail += ("\n★ **扫描面缩水守卫报红**：本次只拿到 %d 页（下限 %d）—— "
                   "「没扫到」不等于「干净」，此判据不成立。" % (len(urls), MIN_SCAN_PAGES))
    if bad:
        detail += "\n" + "\n".join(bad[:5])
    rep.chk("G", "全站无空日期 Dataset", (not bad) and (not errs) and surface_ok, detail)
    hit = [p for p in expect_good_pages if any(p in u for u in good_found)]
    rep.chk("H", "含短代码的页面仍出完好 Dataset", len(hit) == len(expect_good_pages),
            "期望出完好 Dataset 的页：%s ／ 实际命中 %d 个" % (", ".join(expect_good_pages), len(hit)))


def check_archive(base, rep, path):
    html, code, err = fetch(base + path)
    if html is None:
        rep.chk("I", "事件归档页为 CollectionPage", False, "取不到：%s" % err)
        return
    nodes, _ = graph_of(html)
    types = [type_of(n) for n in nodes]
    rep.chk("I", "事件归档页为 CollectionPage", "CollectionPage" in types,
            "节点：%s" % (", ".join(t for t in types if t) or "无"))


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="线上验收：只看线上产物，不看本机文件")
    ap.add_argument("--base", default="", help="WordPress 站点地址，如 https://example.com")
    ap.add_argument("--rest-base", default="astro_event", help="事件 CPT 的 REST base")
    ap.add_argument("--expect-version", default="1.3.0")
    ap.add_argument("--archive", default="/sky-forecast/", help="事件归档页路径")
    ap.add_argument("--shortcode-page", default="/tianxiang-yugao/,/",
                    help="含「今日天象」短代码的页面路径，**逗号分隔**；每一页都必须出完好 Dataset。"
                         "★ v2.3.2：默认面从 1 页扩到 2 页，因为「今日天象」有两种承载方式 —— "
                         "/tianxiang-yugao/ 用 [astro_hub]（其「今日天象」栏默认开启），/ 用 [astro_today]。"
                         "只测其中一处，另一条路径失守时判据会静默放过（F62 就是这么漏掉的）。")
    ap.add_argument("--json", default="", help="把结果写一份 JSON")
    a = ap.parse_args()
    a.base = a.base.rstrip("/")
    a.shortcode_pages = [p.strip() for p in a.shortcode_page.split(",") if p.strip()]
    if not a.shortcode_pages:
        raise SystemExit("[FAIL] --shortcode-page 解析后为空集 ⇒ 按空集守卫直接拦退，不得静默通过")

    auth = None
    u, p = os.environ.get("KCJ_WP_USER"), os.environ.get("KCJ_WP_APP_PASSWORD")
    if u and p:
        auth = base64.b64encode(("%s:%s" % (u, p)).encode()).decode()

    rep = Report()
    print("线上验收 %s   （本机时间 %s）" % (a.base, time.strftime("%Y-%m-%d %H:%M:%S")))
    print("-" * 68)

    check_health(a.base, rep, a.expect_version, auth)
    check_sitemaps(a.base, rep, a.rest_base)
    links = event_links(a.base, a.rest_base, rep)
    if links:
        print("        （事件页清单 %d 条，逐页取源码）" % len(links))
    check_event_pages(links, rep)
    check_datasets(a.base, rep, [a.archive] + a.shortcode_pages, a.shortcode_pages)
    check_archive(a.base, rep, a.archive)

    print("-" * 68)
    npass = sum(1 for r in rep.rows if r["status"] == "PASS")
    nskip = sum(1 for r in rep.rows if r["status"] == "SKIP")
    nfail = len(rep.failed)
    print("通过 %d ／ 跳过 %d ／ 不通过 %d" % (npass, nskip, nfail))
    if nfail:
        print("不通过项：" + ", ".join(r["id"] for r in rep.failed))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"base": a.base, "rows": rep.rows}, f, ensure_ascii=False, indent=2)
        print("已写出 " + a.json)
    return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())
