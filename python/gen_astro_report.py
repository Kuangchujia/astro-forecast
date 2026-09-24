#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""gen_astro_report.py —— 月 / 季 / 年度天象报告的离线生成（v2.0.0 新增）

与页面内下载的分工
──────────────────
· **页面内下载**（`[astro_forecast_report]` 的按钮）：访问者随手取一份，零后端、零凭据。
· **本脚本**：批量产出可长期留档、可打印成 PDF、可提交给第三方（GitHub Pages／OSF）的
  报告文件。同一套期间口径、同一套排序、同一套免责声明 —— 两处文案由**同一份常量**给出
  （见 DISCLAIMER / COLOPHON），避免「网页一份、文件一份」漂移。

产出
────
    reports/<标签>.md     Markdown（便于二次编辑、粘贴到公众号/文档）
    reports/<标签>.html   单文件 HTML（自带打印样式，浏览器 Ctrl+P 即得 PDF）

用法
────
    python gen_astro_report.py --period all                     # 本月/本季/本年/未来12个月
    python gen_astro_report.py --period year --data data/events_future.json
    python gen_astro_report.py --selftest
"""

import argparse
import calendar
import datetime as dt
import html
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(_HERE)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

SCRIPT_VERSION = "1.0.0"
DEFAULT_DATA = os.path.join(REPO_ROOT, "data", "events_future.json")
DEFAULT_OUTDIR = os.path.join(REPO_ROOT, "reports")

SITE = ""  # 站点地址；留空则报告内不写站点链接（部署时由调用方指定）

# ── 口径文案（**单一真值源**：页面模板与本脚本引用同一段意思，改动须同批）──
SCOPE_NOTE = ("口径：全部时刻为北京时间（UTC+8）；事件时刻为**地心量**，与观测地无关。"
              "具体某地的可见情况（地平高度、初初亏复圆时刻）须按观测地另算，本报告不作可见性判断。")
COLOPHON = ("数据来源：NASA JPL DE421 星历 + 本模块自算（月食／行星天象／流星雨）"
            "与照录目录（日食照录 NASA GSFC 目录）。构建流水线离线预计算，非实时生成。")
DISCLAIMER = ("本报告由程序依星历预计算结果汇总生成，非人工观测记录，不构成观测保证；"
              "仅作天文参考，不涉及星占、谶纬、吉凶解读。")


# ============================== 期间口径 ==============================
def period_range(period, today=None):
    """返回 (起, 止, 标签)。含首不含尾。与 PHP 侧 kcj_astro_report_range() 同一口径。"""
    today = today or dt.date.today()
    y, m = today.year, today.month
    if period == "quarter":
        qs = (m - 1) // 3 * 3 + 1
        start = dt.date(y, qs, 1)
        qe, ey = qs + 3, y
        if qe > 12:
            qe -= 12
            ey += 1
        end = dt.date(ey, qe, 1)
        label = "%d 年第 %d 季度" % (y, (qs - 1) // 3 + 1)
    elif period == "year":
        start, end = dt.date(y, 1, 1), dt.date(y + 1, 1, 1)
        label = "%d 年度" % y
    elif period == "next12":
        # ★ 「未来十二个月」＝从今天起**满十二个日历月**（含首不含尾）。
        #   两条错路都踩过，记在此处免得再走：
        #     ① timedelta(days=365) —— 闰年会少一天（2027-03-01 起算成 2028-02-29）；
        #     ② PHP 的 strtotime('+12 months') —— 对 2/29 会进位到下月 1 日。
        #   故按日历月算，并明确定义：目标月没有该日时取**该月最后一天**。
        #   改动此段必须同批改 shortcodes.php 的 kcj_astro_report_range()
        #   （verify_package.py 有跨语言对拍判据，两处不一致会当场报红）。
        start = today
        y2, m2, d2 = today.year + 1, today.month, today.day
        end = dt.date(y2, m2, min(d2, calendar.monthrange(y2, m2)[1]))
        label = "未来十二个月（%s 起）" % start.isoformat()
    else:
        start = dt.date(y, m, 1)
        end = dt.date(y + 1, 1, 1) if m == 12 else dt.date(y, m + 1, 1)
        label = "%d 年 %d 月" % (y, m)
    return start, end, label


PERIOD_ORDER = ("month", "quarter", "year", "next12")
PERIOD_CN = {"month": "月报", "quarter": "季报", "year": "年报", "next12": "未来十二个月"}


# ============================== 取数 ==============================
def load_events(path):
    """读事件行（两种形态都认：list，或 {"events":[...]}）。"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    for k in ("events", "rows", "data"):
        if isinstance(data.get(k), list):
            return data[k]
    raise ValueError("无法从 %s 里认出事件数组" % path)


def pick(rows, start, end, only_published=True):
    """按 [start, end) 过滤（认 event_time_bj 字符串；无该字段的条目剔除并计数）。"""
    out, skipped = [], 0
    for r in rows:
        if only_published and int(r.get("publish_status", 1)) != 1:
            continue
        t = r.get("event_time_bj")
        if not t:
            skipped += 1
            continue
        d = str(t)[:10]
        if start.isoformat() <= d < end.isoformat():
            out.append(r)
    out.sort(key=lambda r: (r.get("event_time_bj") or "", r.get("slug") or ""))
    return out, skipped


TYPE_CN = {
    "solar_eclipse": "日食", "lunar_eclipse": "月食", "planet": "行星天象",
    "meteor": "流星雨", "traditional": "传统天象", "historical": "历史天象",
}


# ============================== 渲染 ==============================
def render_md(title, label, start, end, rows, skipped):
    by_month = {}
    for r in rows:
        by_month.setdefault(str(r.get("event_time_bj"))[:7], []).append(r)
    L = []
    L.append("# " + title)
    L.append("")
    L.append("- 期间：**%s** 起，至 **%s** 止（含首不含尾）" % (start.isoformat(), end.isoformat()))
    L.append("- 条目数：**%d**" % len(rows))
    if skipped:
        L.append("- 已剔除 %d 条无时刻条目（历史史料型条目时刻不可考，不进预告报告）" % skipped)
    L.append("- 生成时间：%s（北京时）" % dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    L.append("- 出处：%s" % SITE)
    L.append("")
    if not rows:
        L.append("> 本期间暂无已发布的天象条目。可能是该期间确实没有达到收录门槛的天象，")
        L.append("> 也可能是数据尚未刷新 —— 本站条目由流水线离线预计算后导入，不是实时生成。")
        L.append("")
    else:
        L.append("| 时间（北京时） | 类型 | 天象 | 说明 |")
        L.append("| --- | --- | --- | --- |")
        for r in rows:
            t = str(r.get("event_type") or "")
            L.append("| %s | %s | %s | %s |" % (
                str(r.get("event_time_bj") or "")[:16],
                TYPE_CN.get(t, t),
                md_cell(r.get("title")),
                md_cell(r.get("summary")),
            ))
        L.append("")
        detail = []
        for r in rows:
            summ = (r.get("summary") or "").strip()
            if not summ:
                continue
            t = str(r.get("event_type") or "")
            detail.append("- **%s**（%s，%s）%s" % (
                str(r.get("event_time_bj") or "")[:16], TYPE_CN.get(t, t),
                str(r.get("method") or "—"), md_cell(summ)))
        if detail:
            L.append("## 逐条说明")
            L.append("")
            L += detail
            L.append("")
    L.append("---")
    L.append("")
    L.append("> " + SCOPE_NOTE)
    L.append(">")
    L.append("> " + COLOPHON)
    L.append(">")
    L.append("> " + DISCLAIMER)
    L.append("")
    return "\n".join(L)


def md_cell(s):
    if not s:
        return ""
    return str(s).replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


HTML_HEAD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%(title)s</title>
<style>
:root{--ink:#1F2933;--line:#E4DDCF;--cinnabar:#9C2A25;--paper:#FDFBF7;--soft:#F7F3EA;}
*{box-sizing:border-box;}
body{margin:0;background:var(--paper);color:var(--ink);
  font:16px/1.8 "Noto Serif SC","Songti SC","STSong",Georgia,serif;}
.wrap{max-width:820px;margin:0 auto;padding:34px 22px 60px;}
h1{font-size:26px;margin:0 0 6px;letter-spacing:.02em;}
h2{font-size:19px;margin:30px 0 10px;padding-left:10px;border-left:4px solid var(--cinnabar);}
h3{font-size:16px;margin:22px 0 8px;color:#555;}
.meta{font-size:13.5px;color:#666;border-bottom:2px solid var(--line);padding-bottom:12px;margin-bottom:20px;}
.meta b{color:var(--cinnabar);}
table{width:100%%;border-collapse:collapse;font-size:14px;margin:6px 0 4px;}
th,td{border:1px solid var(--line);padding:6px 9px;text-align:left;vertical-align:top;}
thead th{background:var(--soft);color:#555;}
tbody tr:nth-child(even){background:#fbf8f2;}
td.t{white-space:nowrap;font-variant-numeric:tabular-nums;}
ol.detail{padding-left:20px;font-size:14.5px;color:#444;}
ol.detail li{margin-bottom:8px;}
.note{font-size:13px;color:#777;}
footer{margin-top:34px;border-top:1px dashed var(--line);padding-top:14px;font-size:13px;color:#777;}
footer p{margin:6px 0;}
.empty{background:var(--soft);border:1px solid var(--line);border-radius:6px;padding:12px 14px;font-size:14.5px;}
@media print{body{background:#fff;}
  .wrap{padding:0;max-width:none;}
  h2{break-after:avoid;} tr{break-inside:avoid;}
  footer{page-break-inside:avoid;}}
</style>
</head>
<body><div class="wrap">
"""


def render_html(title, label, start, end, rows, skipped):
    e = html.escape
    P = [HTML_HEAD % {"title": e(title)}]
    P.append("<h1>%s</h1>" % e(title))
    P.append('<p class="meta">期间 <b>%s</b> 起，至 <b>%s</b> 止（含首不含尾）'
             "｜ 条目数 <b>%d</b>%s ｜ 生成时间 %s（北京时） ｜ 出处 <a href=\"%s\">%s</a></p>"
             % (e(start.isoformat()), e(end.isoformat()), len(rows),
                ("｜ 已剔除 %d 条无时刻条目" % skipped) if skipped else "",
                e(dt.datetime.now().strftime("%Y-%m-%d %H:%M")), e(SITE), e(SITE)))
    if not rows:
        P.append('<p class="empty">本期间暂无已发布的天象条目。可能是该期间确实没有达到收录门槛的'
                 "天象，也可能是数据尚未刷新 —— 本站条目由流水线离线预计算后导入，不是实时生成。</p>")
    else:
        by_month = {}
        for r in rows:
            by_month.setdefault(str(r.get("event_time_bj"))[:7], []).append(r)
        for ym, mrows in by_month.items():
            P.append("<h2>%s（%d 条）</h2>" % (e(ym), len(mrows)))
            P.append("<table><thead><tr><th>时间（北京时）</th><th>类型</th><th>天象</th>"
                     "<th>说明</th></tr></thead><tbody>")
            for r in mrows:
                t = str(r.get("event_type") or "")
                P.append("<tr><td class=\"t\">%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                    e(str(r.get("event_time_bj") or "")[:16]),
                    e(TYPE_CN.get(t, t)), e(r.get("title")), e(r.get("summary"))))
            P.append("</tbody></table>")
        P.append('<p class="note">%s</p>' % e(SCOPE_NOTE))
        detail = [r for r in rows if (r.get("summary") or "").strip()]
        if detail:
            P.append("<h2>逐条说明</h2><ol class=\"detail\">")
            for r in detail:
                t = str(r.get("event_type") or "")
                P.append("<li><b>%s</b>（%s，%s）%s</li>" % (
                    e(str(r.get("event_time_bj") or "")[:16]), e(TYPE_CN.get(t, t)),
                    e(str(r.get("method") or "—")), e(r.get("summary"))))
            P.append("</ol>")
    P.append("<footer><p>%s</p><p>%s</p><p>%s</p></footer>" % (e(SCOPE_NOTE), e(COLOPHON), e(DISCLAIMER)))
    P.append("</div></body></html>")
    return "".join(P)


def safe_name(s):
    for ch in '\\/:*?"<>|':
        s = s.replace(ch, "_")
    return s.replace(" ", "")


def write_report(rows, period, outdir, today=None):
    start, end, label = period_range(period, today)
    picked, skipped = pick(rows, start, end)
    title = "%s天象报告" % label
    os.makedirs(outdir, exist_ok=True)
    base = safe_name(title)
    mp = os.path.join(outdir, base + ".md")
    hp = os.path.join(outdir, base + ".html")
    with open(mp, "w", encoding="utf-8", newline="\n") as f:
        f.write(render_md(title, label, start, end, picked, skipped))
    with open(hp, "w", encoding="utf-8", newline="\n") as f:
        f.write(render_html(title, label, start, end, picked, skipped))
    return {"period": period, "label": label, "start": start.isoformat(), "end": end.isoformat(),
            "count": len(picked), "skipped": skipped, "md": mp, "html": hp}


def selftest():
    problems, ok = [], 0

    def chk(name, cond, detail=""):
        nonlocal ok
        if cond:
            ok += 1
            print("  [PASS] %s %s" % (name, detail))
        else:
            problems.append("%s %s" % (name, detail))
            print("  [FAIL] %s %s" % (name, detail))

    print("[gen_astro_report] selftest")
    # 期间口径
    t = dt.date(2026, 9, 23)
    s, e, lb = period_range("month", t)
    chk("月报期间", (s.isoformat(), e.isoformat()) == ("2026-09-01", "2026-10-01"),
        "%s ~ %s" % (s, e))
    s, e, lb = period_range("quarter", t)
    chk("季报期间（Q3）", (s.isoformat(), e.isoformat()) == ("2026-07-01", "2026-10-01"),
        "%s ~ %s" % (s, e))
    s, e, lb = period_range("year", t)
    chk("年报期间", (s.isoformat(), e.isoformat()) == ("2026-01-01", "2027-01-01"),
        "%s ~ %s" % (s, e))
    s, e, lb = period_range("next12", t)
    chk("未来十二个月期间", (e - s).days >= 360, "%s ~ %s（%d 天）" % (s, e, (e - s).days))
    # 跨年边界：12 月的月报不能落到 13 月
    s, e, lb = period_range("month", dt.date(2026, 12, 5))
    chk("★ 十二月月报跨年边界", (s.isoformat(), e.isoformat()) == ("2026-12-01", "2027-01-01"),
        "%s ~ %s" % (s, e))
    s, e, lb = period_range("quarter", dt.date(2026, 11, 5))
    chk("★ Q4 季报跨年边界", (s.isoformat(), e.isoformat()) == ("2026-10-01", "2027-01-01"),
        "%s ~ %s" % (s, e))

    # 过滤与渲染（构造数据，不依赖真数据文件）
    rows = [
        {"event_time_bj": "2026-09-25 10:00:00", "event_type": "planet", "title": "甲",
         "summary": "说明甲", "method": "ephemeris_de421", "publish_status": 1},
        {"event_time_bj": "2026-10-02 10:00:00", "event_type": "meteor", "title": "乙",
         "summary": "说明乙", "method": "ephemeris_de421", "publish_status": 1},
        {"event_time_bj": None, "event_type": "historical", "title": "丙",
         "summary": "", "method": "analytic_meeus", "publish_status": 1},
        {"event_time_bj": "2026-09-26 10:00:00", "event_type": "planet", "title": "丁",
         "summary": "草稿不该收", "method": "x", "publish_status": 0},
    ]
    picked, skipped = pick(rows, dt.date(2026, 9, 1), dt.date(2026, 10, 1))
    chk("★ 期间过滤 + 未发布剔除 + 无时刻条目计数",
        [r["title"] for r in picked] == ["甲"] and skipped == 1,
        "取到 %s，剔无时刻 %d" % ([r["title"] for r in picked], skipped))
    md = render_md("测试", "X", dt.date(2026, 9, 1), dt.date(2026, 10, 1), picked, skipped)
    htm = render_html("测试", "X", dt.date(2026, 9, 1), dt.date(2026, 10, 1), picked, skipped)
    chk("Markdown 含表头与免责句", "| 时间（北京时） |" in md and DISCLAIMER in md)
    chk("HTML 单文件（含 doctype 与样式）", htm.startswith("<!DOCTYPE html>") and "<style>" in htm)
    chk("★ HTML 已转义（构造含尖括号的标题）",
        "&lt;script&gt;" in render_html(
            "t", "l", dt.date(2026, 9, 1), dt.date(2026, 10, 1),
            [{"event_time_bj": "2026-09-05 00:00:00", "event_type": "planet",
              "title": "<script>x</script>", "summary": "a&b", "method": "m"}], 0),
        "尖括号与 & 均须转义")

    print("[gen_astro_report] selftest：通过 %d 项，失败 %d 项" % (ok, len(problems)))
    return 0 if not problems else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="生成月/季/年度天象报告（Markdown + 单文件 HTML）")
    ap.add_argument("--period", default="all",
                    choices=["all"] + list(PERIOD_ORDER))
    ap.add_argument("--data", default=DEFAULT_DATA, help="事件数据（默认 data/events_future.json）")
    ap.add_argument("--outdir", default=DEFAULT_OUTDIR)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    if not os.path.isfile(args.data):
        print("[gen_astro_report] 找不到数据文件：%s" % args.data, file=sys.stderr)
        return 2
    rows = load_events(args.data)
    print("[gen_astro_report] 读入 %s：%d 条" % (os.path.relpath(args.data, REPO_ROOT), len(rows)))
    periods = list(PERIOD_ORDER) if args.period == "all" else [args.period]

    made = []
    for p in periods:
        info = write_report(rows, p, args.outdir)
        made.append(info)
        print("  %-8s %-22s %4d 条 → %s"
              % (p, info["label"], info["count"],
                 os.path.relpath(info["html"], REPO_ROOT)))
    # 空集守卫：全部期间都 0 条 ⇒ 大概率是数据文件不对，报出来
    if all(i["count"] == 0 for i in made):
        print("[gen_astro_report] 警告：所有期间的条目数都是 0 —— 请确认数据文件是否含该区间的事件。",
              file=sys.stderr)
        return 3
    print("[gen_astro_report] 完成：%d 个期间 × （md + html）" % len(made))
    return 0


if __name__ == "__main__":
    sys.exit(main())
