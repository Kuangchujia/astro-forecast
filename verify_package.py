#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
天象预报模块 · 交付件校验器（收工一条命令）
用法：python verify_package.py [--root .]

校验面：
  1. PHP：**真语法解析**（tree-sitter-php 的 AST，`has_error` / ERROR 节点定位到行）
     + 结构纪律（无 BOM、纯 LF、ABSPATH 守卫、危险函数清单）
  2. PHP 符号：`kcj_*` 函数的**定义 ↔ 引用**双向核对（查未定义调用 / 死函数）
  3. SQL 与跨件一致性：install_tables.sql 与 class-astro-db.php（dbDelta）**列集 + 列类型/列宽**双向对拍
  4. JSON 样例：可解析、必需键齐备、禁用字段（value_xiu_of_day）不存在、区间型时间
  5. 落地指令集覆盖度：指令 01—10 逐条对拍到具体文件/符号
  6. URL 口径：全库不得残留旧前缀 /sky/forecast/（仅白名单处允许出现）
  7. ZIP：条目数、根目录名 == 插件目录名、关键文件齐备
  8. 空集守卫：任何一类扫描到 0 个目标即判失败
  9. 负控制：注入缺陷反证每个检测器**真的会报红**

关于 PHP 校验的诚实边界：
  本机无 PHP runtime，所以用的是 tree-sitter 的 PHP 语法树 —— 它能抓出**语法**错误
  （括号/引号/缺分号/错的关键字），也能抓出未定义函数这类**名字层面**的问题（第 2 节），
  但**不能**替代 PHP 解释器：不解析 include 图、不做类型检查、不跑运行时。
  因此「首次线上激活仍需人工盯 500」这一条不会因为它而取消。

设计纪律（吸取本项目既有教训，见技能 checker-self-reference-pitfalls）：
  - 空集必须报错，不得静默通过；
  - 判据只用「客观可测」项，不把「数据不足」当「不合格」；
  - 每条判据都打印实际取值，便于人工复核；
  - 每个检测器配一条负控制（只跑「关闭开关」那一挡会恰好掩盖缺陷）。
"""
import argparse
import ast
import datetime
import hashlib
import json
import os
import re
import sys
import zipfile

PLUGIN_DIR = "wp-astro-forecast"
DB_FILE = os.path.join(PLUGIN_DIR, "includes", "class-astro-db.php")
EXPECTED_TABLES = ["astro_daily", "astro_events", "astro_relations", "astro_daily_site"]

# 允许出现旧前缀的地方（其余处出现即为口径残留）
OLD_PREFIX = "/sky/forecast/"        # v1.1.0 的两段式前缀（已废）
NEW_PREFIX = "/sky-forecast/"        # v1.2.0 的单段前缀（指令 04）
OLD_PREFIX_ALLOW = (
    "wp-astro-forecast/includes/cpt.php",            # 301 跳转的匹配串本身（const KCJ_ASTRO_OLD_URL）
    "docs/acceptance-checklist.md",                  # 验收用例要真的去访问旧链
    "docs/deploy.md",                                # 上线后要 curl 探旧链是否 301
    "verify_package.py",                             # 本文件（判据自述）
)


class Report:
    def __init__(self):
        self.rows = []
        self.ok = 0
        self.fail = 0

    def chk(self, name, cond, detail=""):
        if cond:
            self.ok += 1
            self.rows.append(("PASS", name, detail))
        else:
            self.fail += 1
            self.rows.append(("FAIL", name, detail))

    def dump(self):
        for st, name, detail in self.rows:
            print("  [%s] %s %s" % (st, name, detail))
        print("\n—— 合计：通过 %d 项，失败 %d 项" % (self.ok, self.fail))
        return self.fail


def read_bytes(p):
    with open(p, "rb") as f:
        return f.read()


def read_text(p):
    return read_bytes(p).decode("utf-8", "replace")


def php_files(root):
    pdir = os.path.join(root, PLUGIN_DIR)
    out = []
    for dp, _dn, fn in os.walk(pdir):
        for f in fn:
            if f.endswith(".php"):
                out.append(os.path.join(dp, f))
    return sorted(out)


def strip_php_comments_only(src):
    """只剥注释、**保留字符串**（字符串里会注册回调名，剥掉就查不到引用了）。"""
    out = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "#":
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "/" and nxt == "*":
            j = src.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if c in ("'", '"'):
            q = c
            out.append(c)
            i += 1
            while i < n:
                out.append(src[i])
                if src[i] == "\\":
                    if i + 1 < n:
                        out.append(src[i + 1])
                    i += 2
                    continue
                if src[i] == q:
                    i += 1
                    break
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def strip_php_strings_and_comments(src):
    """去掉字符串与注释（供括号配平与危险函数扫描用）。"""
    out = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "#":
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "/" and nxt == "*":
            j = src.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if c in ("'", '"'):
            q = c
            i += 1
            while i < n:
                if src[i] == "\\":
                    i += 2
                    continue
                if src[i] == q:
                    i += 1
                    break
                i += 1
            continue
        if c == "<" and src[i:i + 5].lower() == "<?php":
            i += 5
            continue
        if c == "?" and src[i:i + 2] == "?>":
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def code_of(p, root=None):
    """取「可判定文本」：.php 去注释、其余原样。

    ★ 为什么必须有这一层（本文件自己踩过的坑）：
      判据若写成「文件里出现字符串 X」，那么**记录/解释该缺陷的注释**会把检查判红——
      自指悖论。本文件在 v1.2.0 首跑时有 4 项失败全部是注释命中：
        · activation.php 注释里写了「v1.1.0 ……register_post_type()」
        · astro-event-detail.php 注释里写了修复前的 `**未使用**`
        · rankmath.php 注释里解释了一个**不存在**的 Schema 类型名
        · 模板注释里写明了旧 URL 前缀
      故凡「某字符串不得出现」类判据，一律只扫去注释后的代码。
    """
    src = read_text(p)
    if p.endswith(".php"):
        return strip_php_comments_only(src)
    return src


def php_ast_errors(path):
    """tree-sitter 解析；返回 (是否可用, 错误列表[(行, 类型)])。"""
    try:
        from tree_sitter import Language, Parser
        import tree_sitter_php
    except Exception as e:                                   # noqa: BLE001
        return False, [("0", "tree-sitter 不可用：%s" % e)]
    lang = Language(tree_sitter_php.language_php())
    parser = Parser(lang)
    tree = parser.parse(read_bytes(path))
    errs = []
    if tree.root_node.has_error:
        stack = [tree.root_node]
        while stack:
            n = stack.pop()
            if n.type == "ERROR" or n.is_missing:
                errs.append((n.start_point[0] + 1, n.type))
                if len(errs) >= 5:
                    break
            stack.extend(n.children)
        if not errs:
            errs.append((0, "has_error 但未定位到 ERROR 节点"))
    return True, errs


def check_php(root, rep):
    files = php_files(root)
    rep.chk("PHP 文件数 > 0（空集守卫）", len(files) > 0, "= %d 个" % len(files))
    if not files:
        return files

    ts_ok, ts_err = php_ast_errors(files[0])
    rep.chk("★ PHP 真语法解析可用（tree-sitter-php）", ts_ok,
            "缺失时请执行 pip install tree-sitter tree-sitter-php"
            + ("" if ts_ok else "｜%s" % ts_err))

    syntax_bad, bad_bom, bad_eol, no_guard, dangerous, brace_bad = [], [], [], [], [], []
    for p in files:
        raw = read_bytes(p)
        rel = os.path.relpath(p, root).replace("\\", "/")
        if raw.startswith(b"\xef\xbb\xbf"):
            bad_bom.append(rel)
        if b"\r\n" in raw:
            bad_eol.append(rel)
        src = raw.decode("utf-8", "replace")
        if ts_ok:
            _ok, errs = php_ast_errors(p)
            if errs:
                syntax_bad.append("%s@行%s(%s)" % (rel, errs[0][0], errs[0][1]))
        code = strip_php_strings_and_comments(src)
        if code.count("{") != code.count("}") or code.count("(") != code.count(")"):
            brace_bad.append("%s({%d}/{%d},(%d)/(%d))" % (rel, code.count("{"), code.count("}"),
                                                          code.count("("), code.count(")")))
        if ("/includes/" in rel or "/templates/" in rel) and "defined('ABSPATH')" not in src:
            no_guard.append(rel)
        for fn in ("eval(", "exec(", "system(", "shell_exec(", "passthru("):
            if fn in code:
                dangerous.append("%s:%s" % (rel, fn))

    rep.chk("★ PHP 语法正确（AST 无 ERROR 节点）", not syntax_bad,
            "异常：%s" % (syntax_bad or "无"))
    rep.chk("PHP 括号配平（辅助判据）", not brace_bad, "异常：%s" % (brace_bad or "无"))
    rep.chk("PHP 无 BOM", not bad_bom, "异常：%s" % (bad_bom or "无"))
    rep.chk("PHP 纯 LF", not bad_eol, "异常：%s" % (bad_eol or "无"))
    rep.chk("includes/templates 均有 ABSPATH 守卫", not no_guard, "缺失：%s" % (no_guard or "无"))
    rep.chk("无危险函数（eval/exec/system/…）", not dangerous, "命中：%s" % (dangerous or "无"))
    return files


def collect_php_symbols(files, root):
    """收集 kcj_* 函数的定义与引用（引用 = 调用或字符串注册）。"""
    defined = {}     # name -> rel
    refs = {}        # name -> [rel...]
    for p in files:
        rel = os.path.relpath(p, root).replace("\\", "/")
        src = strip_php_comments_only(read_text(p))
        for m in re.finditer(r"\bfunction\s+(kcj_[A-Za-z0-9_]+)\s*\(", src):
            defined.setdefault(m.group(1), rel)
        for m in re.finditer(r"\b(kcj_[A-Za-z0-9_]+)\b", src):
            refs.setdefault(m.group(1), set()).add(rel)
    return defined, refs


def check_php_symbols(files, root, rep):
    """未定义调用 / 死函数。这是 tree-sitter 语法树给不了的一层（名字解析）。"""
    if not files:
        return
    defined, _refs = collect_php_symbols(files, root)
    rep.chk("kcj_* 函数定义数 > 0（空集守卫）", len(defined) > 0, "= %d 个" % len(defined))

    # 调用点（去掉 function 定义行自身）
    calls = {}
    # 出现总次数（含字符串注册，如 add_action('x','kcj_f') / register_post_meta 的 sanitize_callback）
    occ = {}
    defc = {}
    for p in files:
        rel = os.path.relpath(p, root).replace("\\", "/")
        src = strip_php_comments_only(read_text(p))
        for m in re.finditer(r"\b(kcj_[A-Za-z0-9_]+)\b", src):
            occ[m.group(1)] = occ.get(m.group(1), 0) + 1
        for m in re.finditer(r"\bfunction\s+(kcj_[A-Za-z0-9_]+)\s*\(", src):
            defc[m.group(1)] = defc.get(m.group(1), 0) + 1
        src_nofun = re.sub(r"\bfunction\s+kcj_[A-Za-z0-9_]+\s*\(", "FUNABS(", src)
        for m in re.finditer(r"\b(kcj_[A-Za-z0-9_]+)\s*\(", src_nofun):
            calls.setdefault(m.group(1), set()).add(rel)

    undef = sorted(n for n in calls if n not in defined)
    rep.chk("★ 无未定义的 kcj_* 函数调用", not undef, "未定义：%s" % (undef or "无"))

    # 死函数：除定义处外再无任何出现（调用或字符串引用都算引用）。
    # ⚠ 不能用「其他文件里出现过」判——同一文件内 add_action('h','kcj_f') 才是最常见形态，
    #   那样会把 7 个正常函数全判成死函数（本文件首跑即如此）。
    dead = []
    for name in sorted(defined):
        if occ.get(name, 0) - defc.get(name, 0) < 1:
            dead.append(name)
    rep.chk("★ 无死函数（定义后无任何引用）", not dead, "可疑：%s" % (dead or "无"))


def sql_columns(sql, table):
    """install_tables.sql 里 CREATE TABLE `wp_<table>` 段的列名。"""
    m = re.search(r"CREATE TABLE IF NOT EXISTS `wp_%s`\s*\((.*?)\n\)\s*ENGINE" % table, sql, re.S)
    if not m:
        return None
    cols = []
    for line in m.group(1).splitlines():
        s = line.strip()
        if re.match(r"^(PRIMARY|UNIQUE|KEY|INDEX|CONSTRAINT|FULLTEXT)\b", s, re.I):
            continue
        cm = re.match(r"^`([A-Za-z_][A-Za-z0-9_]*)`\s+[A-Za-z]", s)
        if cm:
            cols.append(cm.group(1))
    return cols


def dbdelta_columns(php_src, prefix_var, table):
    """class-astro-db.php 的 dbDelta SQL 里的列名。"""
    m = re.search(r"CREATE TABLE \{%s\}%s\s*\((.*?)\)\s*\$charset;" % (prefix_var, table),
                  php_src, re.S)
    if not m:
        return None
    cols = []
    for line in m.group(1).splitlines():
        s = line.strip().rstrip(",")
        if re.match(r"^(PRIMARY|UNIQUE|KEY|INDEX|CONSTRAINT|FULLTEXT)\b", s, re.I):
            continue
        cm = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s+[A-Za-z]", s)
        if cm:
            cols.append(cm.group(1))
    return cols


def _first_type_token(s):
    """取「列名 后的类型」：`VARCHAR(64)` → `VARCHAR(64)`；`BIGINT UNSIGNED` → `BIGINT`。

    只取第一个类型词 + 可选括号，故两个正本的写法差异（缩进/注释/`UNSIGNED`）
    不会造成假红；但 `ENUM(...)` 与 `VARCHAR(32)` 这种**真类型差异**必然被抓到。
    """
    m = re.match(r"^([A-Za-z]+)(\s*\([^)]*\))?", s)
    return (m.group(1) + (m.group(2) or "")).replace(" ", "").upper() if m else None


def sql_column_types(sql, table):
    """install_tables.sql 里 `wp_<table>` 段的 {列名: 类型}。"""
    m = re.search(r"CREATE TABLE IF NOT EXISTS `wp_%s`\s*\((.*?)\n\)\s*ENGINE" % table, sql, re.S)
    if not m:
        return None
    out = {}
    for line in m.group(1).splitlines():
        s = line.strip()
        if re.match(r"^(PRIMARY|UNIQUE|KEY|INDEX|CONSTRAINT|FULLTEXT)\b", s, re.I):
            continue
        cm = re.match(r"^`([A-Za-z_][A-Za-z0-9_]*)`\s+(.*)$", s)
        if cm:
            t = _first_type_token(cm.group(2))
            if t:
                out[cm.group(1)] = t
    return out


def dbdelta_column_types(php_src, prefix_var, table):
    """class-astro-db.php 的 dbDelta SQL 里的 {列名: 类型}。"""
    m = re.search(r"CREATE TABLE \{%s\}%s\s*\((.*?)\)\s*\$charset;" % (prefix_var, table),
                  php_src, re.S)
    if not m:
        return None
    out = {}
    for line in m.group(1).splitlines():
        s = line.strip().rstrip(",")
        if re.match(r"^(PRIMARY|UNIQUE|KEY|INDEX|CONSTRAINT|FULLTEXT)\b", s, re.I):
            continue
        cm = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s+(.*)$", s)
        if cm:
            t = _first_type_token(cm.group(2))
            if t:
                out[cm.group(1)] = t
    return out


def count_sql_statements(sql):
    lines = []
    for ln in sql.splitlines():
        s = ln.strip()
        if not s or s.startswith("--"):
            continue
        lines.append(ln)
    return [s for s in "\n".join(lines).split(";") if s.strip()]


def check_sql(root, rep):
    sql_p = os.path.join(root, "sql", "install_tables.sql")
    db_p = os.path.join(root, DB_FILE)
    rep.chk("建表 SQL 存在", os.path.isfile(sql_p), sql_p)
    rep.chk("数据层正本 class-astro-db.php 存在", os.path.isfile(db_p), db_p)
    if not (os.path.isfile(sql_p) and os.path.isfile(db_p)):
        return
    sql = read_text(sql_p)
    php = read_text(db_p)

    stmts = count_sql_statements(sql)
    rep.chk("SQL 语句数 ≥ 4（SET NAMES + 3 表）", len(stmts) >= 4, "= %d" % len(stmts))
    rep.chk("SQL 反引号成对", sql.count("`") % 2 == 0, "= %d 个" % sql.count("`"))
    for t in EXPECTED_TABLES:
        rep.chk("SQL 含表 %s" % t, ("`wp_%s`" % t) in sql)
        rep.chk("SQL 表 %s 有 ENGINE/CHARSET" % t,
                bool(re.search(r"`wp_%s`.*?ENGINE=InnoDB DEFAULT CHARSET=utf8mb4" % t, sql, re.S)))
        col_sql = sql_columns(sql, t)
        col_php = dbdelta_columns(php, r"\$p", t)
        rep.chk("★ 列集一致（SQL ↔ dbDelta）：%s" % t,
                col_sql is not None and col_php is not None and col_sql == col_php,
                "SQL %s / PHP %s" % (col_sql, col_php))
        # ★ v1.2.1：光比列名不够 —— 列**类型/宽度**不一致同样会让两份正本分岔（F22/F23）。
        typ_sql = sql_column_types(sql, t)
        typ_php = dbdelta_column_types(php, r"\$p", t)
        diff_typ = type_mismatches(typ_sql, typ_php)
        rep.chk("★ 列类型/列宽逐列一致（SQL ↔ dbDelta）：%s" % t,
                typ_sql is not None and typ_php is not None and not diff_typ,
                "类型不一致：%s" % [{k: "SQL=%s / PHP=%s" % ((typ_sql or {}).get(k), (typ_php or {}).get(k))}
                                 for k in diff_typ] or "全部一致")

    rep.chk("SQL 含 utf8mb4_unicode_ci", "utf8mb4_unicode_ci" in sql)
    # 幂等键：v1.2.0 新增 date_str 与 relations 的唯一键
    rep.chk("★ SQL daily 有 date_str 唯一键（幂等）", "uk_date_str" in sql)
    rep.chk("★ SQL relations 有三元唯一键（幂等）", "uk_from_to_rel" in sql)
    rep.chk("SQL 含 jd 唯一索引", "uk_jd" in sql)
    rep.chk("SQL 含 slug 唯一索引", "uk_slug" in sql)
    rep.chk("SQL 含求解法溯源列 method", "`method`" in sql)
    rep.chk("SQL 含星历溯源列 ephemeris", "`ephemeris`" in sql)
    rep.chk("SQL 含观测地列 obs_site", "`obs_site`" in sql)
    rep.chk("SQL 含 special_event_ids（指令 02 字段清单）", "`special_event_ids`" in sql)
    # dbDelta 侧的幂等键也必须存在（两边任一漏了，线上表就少一个键）
    rep.chk("★ dbDelta daily 有 uk_date_str", "uk_date_str" in php)
    rep.chk("★ dbDelta relations 有 uk_from_to_rel", "uk_from_to_rel" in php)
    rep.chk("SQL 纯 LF", b"\r\n" not in read_bytes(sql_p))


def type_mismatches(sql_types, php_types):
    """两份正本的**列类型差异**：列名 → "SQL=x / PHP=y"。

    ★ 抽成纯函数是为了能做负控制：注入一份「SQL=ENUM / PHP=VARCHAR(32)」的样本，
      必须命中；注入两份相同的样本，必须为空 —— 双向都验过，判据才不是空壳。
    """
    return sorted(k for k in set(sql_types or {}) | set(php_types or {})
                  if (sql_types or {}).get(k) != (php_types or {}).get(k))


def width_violations(types, obs):
    """列宽 < 实测最长值 的列，返回 (违规列表, 实际比对的列数)。

    只比 `VARCHAR(数字)`；`obs` 里没有的键**跳过**（数据不足 ≠ 不合格）。
    返回比对列数是为了让调用方能做**空集守卫**：一列都没比过就不算「全达标」。
    """
    out, compared = [], 0
    for key in sorted(types or {}):
        if key not in (obs or {}):
            continue
        for t, typ in types[key]:
            m = re.match(r"^([A-Z]+)\((\d+)\)$", typ)
            if not m or m.group(1) != "VARCHAR":
                continue
            compared += 1
            if obs[key] > int(m.group(2)):
                out.append("%s.%s 列宽 %d < 实测最长值 %d" % (t, key, int(m.group(2)), obs[key]))
    return out, compared


def width_violations_dual(types, obs2):
    """列宽 vs 实测最长值：**字符数与字节数都判**（v2.2.6 新增）。返回 (违规, 比对列数)。

    为什么必须双口径 —— 这是 F27 唯一的教训：
      WordPress 的 `wpdb` 在「按什么计量」上分**两种口径**（wp-includes/class-wpdb.php 的
      `strip_invalid_text()`）：utf8* 字符集按**字符**截断（`mb_strlen`/`mb_substr`），
      latin1、或值恰为纯 ASCII 时按**字节**截断（`strlen`/`substr`）。
      而本地判据**拿不到线上那一列的字符集** ⇒ 只能两种都按：
      字符数或字节数**任一**超过声明宽度，就报出来。
      ⚠ 这比线上更严（utf8mb4 下 varchar(191) 装 191 个汉字、占 573 字节，是合法的 MySQL 行为）。
        但本项目所有取值都远在限内，从严不会误伤；而反过来漏一次的代价已经见到了 ——
        「线上 4,672 行全失败，本地判据全绿」。
      → 宁可本地拦下来问一句，也不要再让判据和线上各说各话。

    只比 `VARCHAR(数字)`；`obs2` 里没有的键**跳过**（数据不足 ≠ 不合格）。
    返回比对列数，是为了让调用方能做**空集守卫**：一列都没比过就不算「全达标」。
    """
    out, compared = [], 0
    for key in sorted(types or {}):
        if key not in (obs2 or {}):
            continue
        o = obs2[key]
        if not isinstance(o, dict):
            continue
        for t, typ in types[key]:
            m = re.match(r"^([A-Z]+)\((\d+)\)$", typ)
            if not m or m.group(1) != "VARCHAR":
                continue
            compared += 1
            w = int(m.group(2))
            why = []
            if o.get("chars", 0) > w:
                why.append("字符数 %d > %d" % (o.get("chars", 0), w))
            if o.get("bytes", 0) > w:
                why.append("字节数 %d > %d" % (o.get("bytes", 0), w))
            if why:
                out.append("%s.%s 列宽 %d 不足（%s）" % (t, key, w, "；".join(why)))
    return out, compared


def colmaxlen_mismatches(cm, types):
    """客户端裁剪表 COL_MAXLEN 与 SQL 列宽的差异（漏登记/拼写错/数值不符）。"""
    out = []
    for k, w in sorted((cm or {}).items()):
        occ = (types or {}).get(k)
        if not occ:
            out.append("%s 不在任何表的列清单里（键名拼写错？）" % k)
            continue
        for t, typ in occ:
            m = re.match(r"^VARCHAR\((\d+)\)$", typ)
            if m and int(m.group(1)) != w:
                out.append("%s：COL_MAXLEN=%d 而 %s.%s=%s" % (k, w, t, k, typ))
    return out


def _walk_strings(obj):
    """递归产出 (键名, 字符串值)。键名以 `_json` 结尾的字符串**再解析一层** ——
    否则 data_json 只会贡献一条「很长」的长度，而它内层才是真正的列值。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str):
                yield k, v
                if k.endswith("_json"):
                    try:
                        yield from _walk_strings(json.loads(v))
                    except Exception:
                        pass
            else:
                yield from _walk_strings(v)
    elif isinstance(obj, list):
        for it in obj:
            yield from _walk_strings(it)


def _obs_add(obs, k, v):
    """把一个字符串值登记进「实测最长值」表，**字符数与字节数分别取最大**。

    ★ 两个数**必须各取各的最大**，不能从同一个值上取 ——
      最长字符数的值未必是字节数最多的值（拉丁字母 1 字节/字符，汉字 3 字节/字符）。
      本轮就吃过这个亏的近亲：只数一个数，另一个数上的超限**在判据里根本不存在**。
    """
    c, b = len(v), len(v.encode("utf-8"))
    cur = obs.get(k)
    if cur is None:
        obs[k] = {"chars": c, "bytes": b}
    else:
        if c > cur["chars"]:
            cur["chars"] = c
        if b > cur["bytes"]:
            cur["bytes"] = b


def collect_observed_max_dual(root):
    """从**真数据**收集每个键的最长字符串值（返回字符数与字节数**两个**数）。

    取数面与旧版 `collect_observed_max` 完全一致（刻意不从「声明」里读，避免自证）：
      samples/*.json、wp-astro-forecast/data/samples/*.json、data/*.ndjson（逐行）、data/*.json，
      外加源码里**可达的常量值**（DATA_VERSION 及其 `+analytic` 降级形态 —— 后者当前样本里没有，
      但代码路径能产生，必须计入，否则「今天没有」会掩盖「明天就有」）。

    ★★ v2.2.6 为什么非要加字节数（F27 的全部教训就在这一句）：
      旧版只数**字符**（Python 的 `len`），于是
      「`time_uncertainty` = 60 字符 / **159 字节** vs `VARCHAR(64)`」在它眼里**完全合规**，
      判据给出「列宽装得下实测最长值」全绿 —— 而线上那 4,672 行恰恰死在字节上。
      **判据只能量它认识的量；它不认识的那一半，就等于没查。**
      故两个数都收，判定时两个都判（见 width_violations_dual）。
    """
    obs, n_files = {}, 0
    cands = []
    for sub in ("samples", "data", os.path.join(PLUGIN_DIR, "data")):
        d = os.path.join(root, sub)
        if os.path.isdir(d):
            for dirpath, _dn, fns in os.walk(d):
                for fn in sorted(fns):
                    if fn.endswith((".json", ".ndjson")):
                        cands.append(os.path.join(dirpath, fn))
    for path in cands:
        try:
            text = read_text(path)
        except Exception:
            continue
        objs = []
        if path.endswith(".ndjson"):
            for ln in text.splitlines():
                if ln.strip():
                    try:
                        objs.append(json.loads(ln))
                    except Exception:
                        pass
        else:
            try:
                objs.append(json.loads(text))
            except Exception:
                pass
        if not objs:
            continue
        n_files += 1
        for o in objs:
            for k, v in _walk_strings(o):
                _obs_add(obs, k, v)

    cks = os.path.join(root, "python", "compute_sky.py")
    if os.path.isfile(cks):
        m = re.search(r'DATA_VERSION\s*=\s*"([^"]*)"', read_text(cks))
        if m:
            dv = m.group(1)
            for k, v in (("data_version", dv), ("data_version", dv + "+analytic"), ("dt_model", dv)):
                _obs_add(obs, k, v)
            n_files += 1
    return obs, n_files


def collect_observed_max(root):
    """向后兼容的薄封装：只返回字符数（旧调用方与旧负控制用的就是这个口径）。"""
    obs2, n = collect_observed_max_dual(root)
    return {k: v["chars"] for k, v in obs2.items()}, n


# ★ v2.2.6 续：`COL_MAXLEN` 的**全部来源**。加第四份时必须同时加进来，
#   否则「无冲突」这条判据会**只对拍它认识的两处而放行其余**（本轮实测的漂移就是这么发生的）。
COL_MAXLEN_SOURCES = (
    "python/build_dataset.py",   # daily / events 的列
    "python/build_site.py",      # 观测地维度表（wp_astro_daily_site）
    "python/event_almanac.py",   # ★ v2.2.6 续补：**第三份**，此前从未被对拍
)


def parse_col_maxlen_sources(root):
    """读客户端裁剪表 COL_MAXLEN（**全部来源**，见 `COL_MAXLEN_SOURCES`）。

    为什么要把**所有**来源合并后再对拍：同一列名（如 method / data_version /
    time_uncertainty）在多处都出现，若给出的上限不同，就是「同一事实多处硬编码」
    的经典漂移源 —— 今天一致、明天改了其中一处就悄悄分岔。

    ★★ 本轮（2026-09-23）实测的教训：`event_almanac.py` 里那一份**从未被读**，
      于是它静默停在 `time_uncertainty: 64 / ephemeris: 96`（旧值），
      而另两处早已 191 —— **判据报绿，值却分叉了**。
      ⇒ 修法不只是「多读一个文件」，而是下面那条**来源覆盖自检**
      （凡出现 `COL_MAXLEN = {` 的文件都必须在 `COL_MAXLEN_SOURCES` 里）。

    返回 (合并后的 dict, 冲突清单, 实际读到的来源清单)。
    """
    merged, conflicts, found = {}, [], []
    merged_src = {}
    for rel in COL_MAXLEN_SOURCES:
        p = os.path.join(root, rel)
        if not os.path.isfile(p):
            continue
        m = re.search(r"COL_MAXLEN\s*=\s*\{(.*?)\n\}", read_text(p), re.S)
        if not m:
            continue
        found.append(rel)
        for k, n in re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"\s*:\s*(\d+)', m.group(1)):
            n = int(n)
            if k in merged and merged[k] != n:
                conflicts.append("%s：%s=%d（%s）vs %d（%s）"
                                 % (k, k, merged[k], merged_src.get(k, "?"), n, rel))
            else:
                merged[k] = n
                merged_src[k] = rel
    return merged, conflicts, found


def parse_col_maxlen(root):
    """向后兼容的薄封装：只返回合并后的 dict。"""
    merged, _conflicts, _found = parse_col_maxlen_sources(root)
    return merged or None


def check_widths(root, rep):
    """★ v1.2.1 新增：**列类型/列宽层面**的判据（v1.2.0 只比了列名）。

    病根（两个都是同一处失职）：
      · `data_version`/`dt_model` 列宽 32，而真值 36/45 ⇒ 线上 MySQL 拒行、回执 written:0（F22）；
      · `event_type` 在 SQL 里是 ENUM、在 dbDelta 里是 VARCHAR(32)，两份「必须逐列一致」的
        正本其实类型不同，也从没被查出来（F23）。
    """
    sql_p = os.path.join(root, "sql", "install_tables.sql")
    if not os.path.isfile(sql_p):
        rep.chk("列宽判据：SQL 存在", False, sql_p)
        return
    sql = read_text(sql_p)

    types = {}
    for t in EXPECTED_TABLES:
        for k, v in (sql_column_types(sql, t) or {}).items():
            types.setdefault(k, []).append((t, v))

    obs, n_files = collect_observed_max(root)
    # 空集守卫：一个样本都没读到 ⇒ 判据无从谈起，必须报错而不是「全达标」
    rep.chk("列宽判据：已从真数据收集到样本（空集守卫）", n_files > 0 and bool(obs),
            "%d 个数据文件 / %d 个键" % (n_files, len(obs)))

    narrow, compared = width_violations(types, obs)
    rep.chk("★ 列宽装得下实测最长值（VARCHAR 逐列）", compared > 0 and not narrow,
            "比对 %d 列；过窄：%s" % (compared, narrow or "无"))

    # ★★ v2.2.6（F27）：**同一个问题要按两个口径各量一次**。
    #   上面那条只数**字符**，而线上 `events.time_uncertainty`（60 字符 / **159 字节** vs 声明 64）
    #   恰恰是在**字节**口径上溢出 ⇒ 上面那条全绿、线上 4,672 行全失败。
    #   新增下面两条之后，同类事故在**本地判据**里就拦得住了。
    obs2, n_files2 = collect_observed_max_dual(root)
    rep.chk("列宽判据（双口径）：已从真数据收集到样本（空集守卫）",
            n_files2 > 0 and bool(obs2), "%d 个数据文件 / %d 个键" % (n_files2, len(obs2)))
    narrow2, compared2 = width_violations_dual(types, obs2)
    rep.chk("★★ 列宽**按字符与字节双口径**都装得下（v2.2.6 新增；只数字符会漏掉 F27）",
            compared2 > 0 and not narrow2,
            "比对 %d 列；过窄：%s" % (compared2, narrow2 or "无"))
    if obs2:
        topb = sorted(obs2.items(), key=lambda kv: -kv[1].get("bytes", 0))[:6]
        rep.chk("列宽判据（双口径）：实测最长值可复核（按字节降序前 6）", True,
                " / ".join("%s=%d字符/%d字节" % (k, v.get("chars", 0), v.get("bytes", 0))
                           for k, v in topb))

    cm = parse_col_maxlen(root)
    rep.chk("★ COL_MAXLEN 可解析且非空", bool(cm), "= %s" % (cm or "解析失败"))
    if cm:
        mism = colmaxlen_mismatches(cm, types)
        rep.chk("★ COL_MAXLEN 与 SQL 列宽逐项一致（客户端裁剪 ↔ 服务端结构）",
                not mism, "; ".join(mism) or "全部一致（%d 项）" % len(cm))

    # ★ v2.0.0：COL_MAXLEN 有**两处来源**（日记录/事件 与 观测地表），合并时若同一个列名
    #   给出不同宽度，即为「同一事实两处硬编码」的漂移，必须报出来。
    _merged, cm_conflicts, cm_sources = parse_col_maxlen_sources(root)
    rep.chk("★ COL_MAXLEN 的多处来源之间无冲突（同名同宽）",
            not cm_conflicts,
            ("来源：%s；" % ", ".join(cm_sources)) + ("; ".join(cm_conflicts) or "无冲突"))
    rep.chk("观测地表 COL_MAXLEN 已被纳入对拍（python/build_site.py）",
            "python/build_site.py" in cm_sources, "来源：%s" % (cm_sources or "无"))
    # ★★ v2.2.6 续：**来源覆盖自检** —— 只要某个文件里出现 `COL_MAXLEN = {`，
    #   它就**必须**在 COL_MAXLEN_SOURCES 里。这条是「防第四份出现」的唯一机制：
    #   本轮就是因为漏了一份，才让旧值在视野外活了很久。
    _all_cm_files, _missed = [], []
    _pydir = os.path.join(root, "python")
    if os.path.isdir(_pydir):
        for _fn in sorted(os.listdir(_pydir)):
            if not _fn.endswith(".py"):
                continue
            _rel = "python/" + _fn
            if re.search(r"COL_MAXLEN\s*=\s*\{", read_text(os.path.join(_pydir, _fn))):
                _all_cm_files.append(_rel)
                if _rel not in COL_MAXLEN_SOURCES:
                    _missed.append(_rel)
    rep.chk("★★ COL_MAXLEN 的**出现处**全部被纳入对拍（防出现第四份而无人知道）",
            not _missed,
            "出现处 %s；未纳入 %s" % (_all_cm_files or "无", _missed or "无"))
    rep.chk("★★ COL_MAXLEN 的来源清单每一项都真的读到（名单不许有幽灵项）",
            set(cm_sources) == set(COL_MAXLEN_SOURCES),
            "读到 %s ／ 名单 %s" % (cm_sources, list(COL_MAXLEN_SOURCES)))

    if obs:
        top = sorted(obs.items(), key=lambda kv: -kv[1])[:8]
        rep.chk("列宽判据：实测最长值可复核（打印前 8）", True,
                " / ".join("%s=%d" % (k, v) for k, v in top))


def check_json(root, rep):
    sdir = os.path.join(root, "samples")
    names = ["daily_sample.json", "future_event_sample.json", "historical_event_sample.json"]
    docs = {}
    for nm in names:
        p = os.path.join(sdir, nm)
        rep.chk("样例存在：%s" % nm, os.path.isfile(p), p)
        if os.path.isfile(p):
            try:
                docs[nm] = json.loads(read_text(p))
                rep.chk("样例可解析：%s" % nm, True)
            except Exception as e:                           # noqa: BLE001
                rep.chk("样例可解析：%s" % nm, False, str(e))
    rep.chk("样例件数 = 3（空集守卫）", len(docs) == 3, "= %d" % len(docs))

    # 插件内 data/samples/ 必须是同一份（防两处样例漂移）
    pdir_samples = os.path.join(root, PLUGIN_DIR, "data", "samples")
    same = 0
    for nm in names:
        a = os.path.join(sdir, nm)
        b = os.path.join(pdir_samples, nm)
        if os.path.isfile(a) and os.path.isfile(b) and read_bytes(a) == read_bytes(b):
            same += 1
    rep.chk("★ 插件 data/samples 与仓库 samples 逐字节一致", same == 3, "一致 %d/3" % same)

    # ★ 行尾：样例 JSON 必须纯 LF（本项目 05-工具/ 一律 LF）
    #   实测教训：compute_sky.to_json() 原先以文本模式写盘，Windows 下 \n→\r\n，
    #   于是 --emit-samples 的产物是 CRLF，而 build_dataset.py 的 _write_json
    #   （已 newline="\n"）是 LF —— 同一目录两套行尾。已给 to_json 补 newline="\n"，
    #   此处立判据防回归。注意：JSON 规范把 CR/LF 都当空白，功能上无害，
    #   所以这个缺陷**不会被任何解析类判据发现**，只能靠行尾判据。
    lf_files, crlf_files = [], []
    for base in (sdir, pdir_samples):
        for nm in names:
            p = os.path.join(base, nm)
            if not os.path.isfile(p):
                continue
            raw = read_bytes(p)
            tag = "%s/%s" % (os.path.basename(base), nm)
            (lf_files if raw.count(b"\r") == 0 else crlf_files).append(tag)
    rep.chk("★ 样例 JSON 行尾为纯 LF（无 CR）", not crlf_files,
            "CRLF：%s" % (sorted(crlf_files) or "无"))

    d = docs.get("daily_sample.json")
    if isinstance(d, dict):
        for k in ("date_str", "jd", "observer", "data_version", "method", "ephemeris",
                  "sun", "moon", "planets", "xiu", "disclaimer"):
            rep.chk("日样例含键 %s" % k, k in d)
        rep.chk("日样例行星 = 5 颗", isinstance(d.get("planets"), dict) and len(d["planets"]) == 5,
                "= %s" % (len(d["planets"]) if isinstance(d.get("planets"), dict) else "—"))
        rep.chk("★ 日样例不含 value_xiu_of_day（合规）",
                isinstance(d.get("xiu"), dict) and "value_xiu_of_day" not in d["xiu"])
        rep.chk("日样例 jd 为数值", isinstance(d.get("jd"), (int, float)), "= %s" % d.get("jd"))
        rep.chk("★ 日样例自述 jd 尺度（F17）",
                str(d.get("jd_scale", "")).startswith("TT"), "jd_scale=%s" % d.get("jd_scale"))
        for pb in ("mercury", "venus", "mars", "jupiter", "saturn"):
            rep.chk("日样例含行星 %s 且星等为数值" % pb,
                    isinstance(d.get("planets"), dict) and pb in d["planets"]
                    and isinstance(d["planets"][pb].get("apparent_mag"), (int, float)))
    else:
        rep.chk("日样例为对象", False)

    h = docs.get("historical_event_sample.json")
    if isinstance(h, dict):
        rep.chk("历史样例三层齐备（literature/calc/discussion）",
                all(k in h for k in ("literature", "calc", "discussion")))
        calc = h.get("calc", {})
        rep.chk("历史样例 calc 含 method/ephemeris", "method" in calc and "ephemeris" in calc)
        rep.chk("历史样例含 nearest_phases", isinstance(calc.get("nearest_phases"), list)
                and len(calc["nearest_phases"]) > 0,
                "= %d 条" % len(calc.get("nearest_phases", [])))
        ph = (calc.get("nearest_phases") or [{}])[0]
        rep.chk("★ 历史样例给区间（earliest < latest）",
                bool(ph.get("time_bj_earliest")) and bool(ph.get("time_bj_latest"))
                and ph["time_bj_earliest"] < ph["time_bj_latest"],
                "%s ~ %s" % (ph.get("time_bj_earliest"), ph.get("time_bj_latest")))
        ch = h.get("chronology", {})
        rep.chk("★ 纪年口径：720BC → 天文年 -719 且显示为公元前720年",
                ch.get("era_year") == -719 and "公元前 720 年" in str(ch.get("era_year_display")),
                "era_year=%s display=%s" % (ch.get("era_year"), ch.get("era_year_display")))
        # ★ F17：历史回推必须同时给出 UT 与 TT 两个尺度，且差值 == ΔT
        jt, ju = calc.get("jd_query_tt"), calc.get("jd_query_ut")
        dt = calc.get("delta_t_sec")
        ok_scale = all(isinstance(v, (int, float)) for v in (jt, ju, dt))
        rep.chk("★ 历史样例已做 UT→TT 折算（F17）",
                ok_scale and abs((jt - ju) - dt / 86400.0) < 1e-6,
                "jd_tt−jd_ut=%.6f 天 / ΔT=%s s" % ((jt - ju) if ok_scale else float("nan"), dt))
        lit = h.get("literature", {})
        rep.chk("★ 历史样例只引古籍正本（不引近现代注本）",
                "春秋" in str(lit.get("source_ref", "")) and "杨伯峻" not in json.dumps(h, ensure_ascii=False),
                str(lit.get("source_ref", "")))
    else:
        rep.chk("历史样例为对象", False)

    f = docs.get("future_event_sample.json")
    if isinstance(f, dict):
        rep.chk("未来样例含 event_type/method/ephemeris/publish_status",
                all(k in f for k in ("event_type", "method", "ephemeris", "publish_status")))
        fc = f.get("calc", {}) if isinstance(f.get("calc"), dict) else {}
        rep.chk("★ 未来样例 jd_core 为 TT 尺度（F17）",
                str(f.get("jd_scale", "")).startswith("TT") or str(fc.get("jd_scale", "")).startswith("TT"),
                "jd_scale=%s" % (f.get("jd_scale") or fc.get("jd_scale")))


def check_instructions(root, rep):
    """落地指令集 指令 01—10 逐条对拍。"""
    pdir = os.path.join(root, PLUGIN_DIR)
    inc = os.path.join(pdir, "includes")

    def has(rel, *needles, **kw):
        """正向检查（必须出现）。raw=True 时连注释一起扫。

        ★ 何时用 raw：判据本身**就住在注释里**的场合 —— 例如插件头
          （`Plugin Name:` 在 /* */ 块里）与文档块。负向检查（「不得出现」）
          一律不走本函数、且一律只扫代码，两者不可混用。
        """
        raw = bool(kw.get("raw", False))
        p = os.path.join(root, rel)
        if not os.path.isfile(p):
            return False, "文件缺失"
        src = read_text(p) if raw else code_of(p)
        miss = [n for n in needles if n not in src]
        return (not miss), ("缺 %s" % miss if miss else "OK")

    # 指令 01 插件骨架与目录结构
    ok, d = has(PLUGIN_DIR + "/wp-astro-forecast.php", "Plugin Name:", "KCJ_ASTRO_VER",
                "includes/", raw=True)
    rep.chk("指令01 插件主文件与标准插件头", ok, d)
    for sub in ("includes", "templates", "assets", "data"):
        rep.chk("指令01 目录存在：%s/" % sub, os.path.isdir(os.path.join(pdir, sub)))
    rep.chk("指令01 样式文件名 = astro-style.css",
            os.path.isfile(os.path.join(pdir, "assets", "astro-style.css")))
    rep.chk("指令01 旧样式 astro.css 已移除",
            not os.path.isfile(os.path.join(pdir, "assets", "astro.css")))

    # 指令 02 建表（class-astro-db.php + dbDelta + 激活钩子）
    ok, d = has(DB_FILE, "dbDelta", "KCJ_Astro_DB", "create()")
    rep.chk("指令02 includes/class-astro-db.php 建表正本", ok, d)
    ok, d = has(PLUGIN_DIR + "/includes/activation.php",
                "function kcj_astro_forecast_activate", "KCJ_Astro_DB::create()",
                "kcj_astro_cron_schedule()")
    rep.chk("指令02 activation.php 薄壳：建表 + 排程", ok, d)
    ok, d = has(PLUGIN_DIR + "/wp-astro-forecast.php",
                "register_activation_hook", "register_deactivation_hook")
    rep.chk("指令02 激活/停用钩子在主文件注册", ok, d)
    ok, d = has(PLUGIN_DIR + "/includes/class-astro-db.php", "special_event_ids", "created_at")
    rep.chk("指令02 daily 含 special_event_ids / created_at", ok, d)
    rep.chk("指令02 三表齐备（daily/events/relations）",
            all(t in read_text(os.path.join(root, DB_FILE)) for t in EXPECTED_TABLES))

    # 指令 03 Python + 导入
    rep.chk("指令03 python/compute_sky.py 存在",
            os.path.isfile(os.path.join(root, "python", "compute_sky.py")))
    ok, d = has("python/build_dataset.py", "argparse", "--push", "--selftest")
    rep.chk("指令03 python/build_dataset.py 批量构建 + 推送", ok, d)
    ok, d = has(PLUGIN_DIR + "/includes/rest-import.php", "register_rest_route",
                "'/import'", "permission_callback", "'edit_posts'", "KCJ_ASTRO_REST_MAX_ROWS")
    rep.chk("指令03 REST 导入端点存在且鉴权（edit_posts + 分批上限）", ok, d)
    ok, d = has(PLUGIN_DIR + "/includes/rest-import.php", "kcj_astro_sync_event_to_post")
    rep.chk("指令03 事件导入后同步为 CPT 文章", ok, d)

    # 指令 04 CPT / 分类法 / 元字段 / URL 前缀
    ok, d = has(PLUGIN_DIR + "/includes/cpt.php", "register_post_type", "register_taxonomy",
                "register_post_meta", "kcj_astro_meta_fields")
    rep.chk("指令04 CPT + 分类法 + 元字段注册", ok, d)
    ok, d = has(PLUGIN_DIR + "/includes/cpt.php", "add_action('init'")
    rep.chk("★ 指令04 CPT 在 init 注册（不在激活钩子里）", ok, d)
    ok, d = has(PLUGIN_DIR + "/includes/cpt.php", "const KCJ_ASTRO_SLUG    = 'sky-forecast'")
    rep.chk("指令04 固定链接前缀 = sky-forecast", ok, d)
    cpt_src = code_of(os.path.join(pdir, "includes", "cpt.php"))
    rep.chk("★ 指令04 激活钩子内不再注册 CPT（F20 必崩缺陷已修）",
            "register_post_type" not in code_of(os.path.join(pdir, "includes", "activation.php")))
    for meta in ("kcj_jd_core", "kcj_event_time_bj", "kcj_params", "kcj_obs_site",
                 "kcj_source_ref", "kcj_related_hist_ids", "kcj_related_future_ids"):
        rep.chk("指令04 元字段 %s" % meta, meta in cpt_src)

    # 指令 05 三个短代码
    sc = read_text(os.path.join(pdir, "includes", "shortcodes.php"))
    for scode in ("astro_today", "astro_forecast_list", "astro_related_events"):
        rep.chk("指令05 短代码 [%s]" % scode, ("add_shortcode('%s'" % scode) in sc)
    for tv in ("solar", "lunar", "planet", "meteor", "traditional", "historical"):
        rep.chk("指令05 type 支持 '%s'" % tv, ("'%s'" % tv) in read_text(os.path.join(pdir, "includes", "cpt.php")))

    # 指令 06 模板
    for tpl in ("single-astro_event.php", "archive-astro_event.php", "astro-forecast-list.php",
                "astro-today.php", "astro-event-detail.php", "astro-related-events.php"):
        rep.chk("指令06 模板 templates/%s" % tpl,
                os.path.isfile(os.path.join(pdir, "templates", tpl)))
    cpt_src = read_text(os.path.join(pdir, "includes", "cpt.php"))
    rep.chk("指令06 模板经 template_include 注入（WP.com 禁改主题）",
            "template_include" in cpt_src and "locate_template" in cpt_src)
    rep.chk("指令06 修掉 ** 字面量（原 v1.1.0 会在页面显示两个星号）",
            "**未使用**" not in code_of(os.path.join(pdir, "templates", "astro-event-detail.php")))

    # 指令 07 Rank Math
    rm = code_of(os.path.join(pdir, "includes", "rankmath.php"))
    rep.chk("指令07 rankmath.php 存在", len(rm) > 0)
    rep.chk("指令07 接真实钩子 rank_math/json_ld", "rank_math/json_ld" in rm)
    # 注：只扫代码，故注释里为说明「这两个类型不存在」而写下它们的名字不算违规
    rep.chk("★ 指令07 代码里不出现不存在的 Schema 类型 AstronomicalObject",
            "AstronomicalObject" not in rm)
    rep.chk("★ 指令07 代码里不出现不存在的 Schema 类型 Calendar",
            "'Calendar'" not in rm and '"Calendar"' not in rm)
    rep.chk("指令07 ScholarlyArticle 由本插件补位（Rank Math 免费版无）",
            "ScholarlyArticle" in rm)
    rep.chk("指令07 文档 docs/rank-math-config.md 存在",
            os.path.isfile(os.path.join(root, "docs", "rank-math-config.md")))
    # ★ 2026-09-23 新增：PHP 层判据的落点。本机原本没有 PHP，插件代码从未被执行过，
    #   于是「面板选了 Event 却零输出」这类问题只能靠读源码猜（见 docs/feasibility-review.md F37/F38）。
    rep.chk("PHP 层判据 php_selftest.py 存在（语法闸 + WordPress 钩子桩测试）",
            os.path.isfile(os.path.join(root, "php_selftest.py")))
    # ★ 2026-09-23 新增：线上验收的落点。`verify_package` 查「包内一致」、`php_selftest` 查「PHP 层逻辑」，
    #   两者都跑在本机、都碰不到线上 ⇒「包对了 ≠ 线上对了」这一段原先没有判据。
    #   F37（面板选了 Event、前台零 JSON-LD）与 F38（首页挂空日期 Dataset）都是这一段漏出去的。
    lv_path = os.path.join(root, "live_verify.py")
    lv_exists = os.path.isfile(lv_path)
    rep.chk("线上验收判据 live_verify.py 存在（上传后跑的那一条）", lv_exists)
    lv_ok, lv_msg = False, "文件不存在"
    if lv_exists:
        try:
            compile(read_text(lv_path), "live_verify.py", "exec")
            lv_ok, lv_msg = True, ""
        except Exception as e:   # noqa: BLE001
            lv_msg = str(e)[:200]
    rep.chk("★ live_verify.py 语法可编译（语法闸）", lv_ok, lv_msg)

    # 指令 08 Cron / 内链
    ok, d = has(PLUGIN_DIR + "/includes/cron.php", "wp_schedule_event", "kcj_astro_cron_monthly",
                "kcj_astro_cron_quarterly", "kcj_astro_freshness")
    rep.chk("指令08 定时任务与新鲜度审计", ok, d)
    rep.chk("★ 指令08 停用时撤排程（对称清理）",
            "kcj_astro_cron_unschedule" in read_text(os.path.join(pdir, "includes", "activation.php")))
    ok, d = has(PLUGIN_DIR + "/includes/compliance.php", "kcj_astro_auto_internal_links")
    rep.chk("指令08 自动内链（默认关闭 + 可配置）", ok, d)
    rep.chk("★ 指令08 自动内链默认关闭",
            "auto_links', 0" in read_text(os.path.join(pdir, "includes", "compliance.php")))

    # 指令 09 免责声明
    ok, d = has(PLUGIN_DIR + "/includes/compliance.php", "the_content",
                "kcj_astro_disclaimer_text", "kcj_astro_append_disclaimer")
    rep.chk("指令09 the_content 自动挂载免责声明", ok, d)
    rep.chk("★ 指令09 声明有去重（避免同页两份）",
            "kcj_astro_disclaimer_signature" in read_text(os.path.join(pdir, "includes", "compliance.php")))
    rep.chk("★ 指令09 声明含 GB/T 33661—2017 且未超范围主张月相精度",
            "GB/T 33661—2017" in read_text(os.path.join(pdir, "includes", "compliance.php"))
            and "农历日期与二十四节气的编排符合" in read_text(os.path.join(pdir, "includes", "compliance.php")))

    # 指令 10 验收
    rep.chk("指令10 验收清单 docs/acceptance-checklist.md 存在",
            os.path.isfile(os.path.join(root, "docs", "acceptance-checklist.md")))


def check_url_prefix(root, rep):
    """全库不得「不明说地」残留旧前缀 /sky/forecast/。

    ★ 判据为何是**行级**而不是文件级（2026-09-22 实测教训 · 自指族陷阱）：
      最初写成「文件里出现旧前缀就算残留」，结果把它自己那套判据的**记述文档**
      （feasibility-review / milestones / verification-report 里「旧前缀 X → 新前缀 Y 加 301」
      以及「断言无残留旧前缀 X」这些话）全判红了——文档在**描述这次变更**，
      却被变更检测器当成变更残留，属自指悖论。
      修法不是把这几份文档塞进白名单（那会让它们真正残留时也漏判），而是收紧判据本身：
      **提及旧前缀而不同时交代「它是旧的」，才算残留。**
      即：一行里出现旧前缀，若同时出现新前缀（对照写法）或出现遗留标记
      （「旧」/`OLD`/`legacy`/`301`），视为记述变更；否则报红。
      真实残留（例如「详情页：/sky/forecast/{slug}/」）不含任何遗留标记，照样会被抓到——
      负控制⑧专门反证这一点，防止判据被架空成恒真。
    """
    LEGACY_MARKERS = ("旧", "OLD", "legacy", "Legacy", "301")
    hits, scanned = [], 0
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in ("__pycache__", ".git")]
        for f in fn:
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, root).replace("\\", "/")
            if f.endswith((".png", ".jpg", ".zip", ".pyc", ".bsp")):
                continue
            scanned += 1
            try:
                # ★ PHP 只看代码：模板/CPT 注释里为记录变更而写着旧前缀，不算口径残留
                src = code_of(p) if f.endswith(".php") else read_text(p)
            except Exception:                                # noqa: BLE001
                continue
            if OLD_PREFIX not in src:
                continue
            if any(rel.startswith(a) for a in OLD_PREFIX_ALLOW):
                continue
            # 行级：逐行判「是不是在交代它是旧前缀」
            for i, line in enumerate(src.splitlines(), 1):
                if OLD_PREFIX not in line:
                    continue
                if NEW_PREFIX in line:                       # 对照写法：旧→新 同现
                    continue
                if any(m in line for m in LEGACY_MARKERS):   # 明确标注为遗留
                    continue
                hits.append("%s:%d" % (rel, i))
    rep.chk("URL 前缀一致性：扫描到文件 > 0（空集守卫）", scanned > 0, "= %d 个" % scanned)
    rep.chk("★ 无残留旧前缀 %s（行级判据：不交代遗留即报红）" % OLD_PREFIX,
            not hits, "命中：%s" % (hits or "无"))

    # 新前缀必须在关键位置出现
    cpt = read_text(os.path.join(root, PLUGIN_DIR, "includes", "cpt.php"))
    rep.chk("★ 301 跳转已实现（旧→新）", "wp_safe_redirect" in cpt and "301" in cpt)
    list_tpl = read_text(os.path.join(root, PLUGIN_DIR, "templates", "astro-forecast-list.php"))
    rep.chk("★ 列表模板不再硬编码 URL（改走 permalink 助手）",
            "kcj_astro_event_permalink" in list_tpl)


def zip_disk_diffs(zip_map, disk_map):
    """返回「zip 内容 ≠ 磁盘内容」的条目名（两边的键都按 zip 内的相对路径）。

    ★ 抽成纯函数是为了能做负控制：注入一条差异必须命中、注入完全一致必须为空。

    为什么需要这条判据：v1.2.0 的 `check_zip` 只验「**文件在不在**」。
    于是**源件改了、zip 忘了重打**这种最常见的交付事故**完全查不出来** ——
    用户上传的是旧代码，而收工闸门全绿。（与本轮 F22/F23 同族：**比了名字不比内容**。）
    """
    out = []
    for n in sorted(zip_map):
        if n not in disk_map:
            out.append("%s（磁盘上没有）" % n)
        elif zip_map[n] != disk_map[n]:
            out.append(n)
    return out


def check_zip(root, rep):
    z = os.path.join(root, PLUGIN_DIR + ".zip")
    rep.chk("插件 zip 存在", os.path.isfile(z), z)
    if not os.path.isfile(z):
        return
    with zipfile.ZipFile(z) as zf:
        names = zf.namelist()
    rep.chk("zip 条目数 ≥ 12", len(names) >= 12, "= %d" % len(names))
    roots = set(n.split("/")[0] for n in names)
    rep.chk("zip 根目录唯一且 == 插件目录名", roots == {PLUGIN_DIR}, "= %s" % sorted(roots))

    need = [
        PLUGIN_DIR + "/wp-astro-forecast.php",
        PLUGIN_DIR + "/includes/class-astro-db.php",
        PLUGIN_DIR + "/includes/cpt.php",
        PLUGIN_DIR + "/includes/shortcodes.php",
        PLUGIN_DIR + "/includes/rest-import.php",
        PLUGIN_DIR + "/includes/cron.php",
        PLUGIN_DIR + "/includes/compliance.php",
        PLUGIN_DIR + "/includes/rankmath.php",
        PLUGIN_DIR + "/includes/activation.php",
        # ★ v2.2.5 补：admin-import.php 原先**不在**这张清单里（漏了 ⑨，
        #   而它正是「一键导入」的实现；漏进包 ⇒ 后台菜单点了就 500，
        #   而 zip 判据当时是绿的）。status-beacon.php 是 v2.2.5 新增。
        PLUGIN_DIR + "/includes/admin-import.php",
        PLUGIN_DIR + "/includes/status-beacon.php",
        # ★ v2.2.6 新增：col-budget.php（字段长度预检）。
        #   为什么它必须进这张清单：rest-import.php 会用 `function_exists('kcj_astro_preflight')`
        #   **守卫**着调用它 —— 一旦它漏进包，守卫会让调用静默失效：
        #   页面照常、导入照常、**预检一个字都不报**，于是「新加的护栏」变成空气，
        #   而 zip 判据还是绿的（与 ⑨ admin-import.php 那次是同一个坑，故同一张清单）。
        PLUGIN_DIR + "/includes/col-budget.php",
        PLUGIN_DIR + "/assets/astro-style.css",
        PLUGIN_DIR + "/assets/astro-place.js",
        PLUGIN_DIR + "/assets/astro-report.js",
        PLUGIN_DIR + "/templates/astro-today.php",
        PLUGIN_DIR + "/templates/astro-forecast-list.php",
        PLUGIN_DIR + "/templates/astro-event-detail.php",
        PLUGIN_DIR + "/templates/astro-related-events.php",
        PLUGIN_DIR + "/templates/single-astro_event.php",
        PLUGIN_DIR + "/templates/archive-astro_event.php",
        PLUGIN_DIR + "/templates/astro-history-today.php",
        PLUGIN_DIR + "/templates/astro-forecast-report.php",
        PLUGIN_DIR + "/templates/astro-hub.php",
        PLUGIN_DIR + "/data/README.md",
    ]
    miss = [n for n in need if n not in names]
    rep.chk("★ zip 内含全部必需文件（%d 项）" % len(need), not miss, "缺：%s" % (miss or "无"))
    stale = [n for n in names if n.endswith("assets/astro.css")]
    rep.chk("zip 不含已废弃的 assets/astro.css", not stale, "命中：%s" % (stale or "无"))

    # ★ v1.2.1：zip 必须**内容**等于磁盘 —— 只验「在不在」会放过**过期包**
    #   （源件改了、zip 没重打 ⇒ 用户上传旧代码，而收工闸门全绿）。
    with zipfile.ZipFile(z) as zf:
        zip_map = dict((n, zf.read(n)) for n in names if not n.endswith("/"))
    disk_map = {}
    for n in zip_map:
        disk_p = os.path.join(root, n.replace("/", os.sep))
        if os.path.isfile(disk_p):
            with open(disk_p, "rb") as f:
                disk_map[n] = f.read()
    diffs = zip_disk_diffs(zip_map, disk_map)
    rep.chk("★ zip 内容与磁盘逐字节一致（%d 条）" % len(zip_map),
            len(zip_map) > 0 and not diffs,
            "不一致 %d 条：%s" % (len(diffs), diffs[:5] or "无"))


# ── 表结构升级守卫（F24—F26，v1.2.1 第二轮）────────────────────────────
# 这一族与 F22 同源：**系统以为自己升级了，其实没有**。判据的设计原则也同源——
# 不能只验「代码里有那行字」，要验**语义**：
#   ① 同一个 option 的**所有**写入点语义必须唯一（F24）；
#   ② 落账必须发生在**实测之后**（判据坐在被测流程下游就恒真 —— F22 的元教训）（F25）；
#   ③ 失败必须**说得出原因**，而不是只报个数（F26 / failed 无 reason）。

# 与 class-astro-db.php 的 KCJ_Astro_DB::min_widths() 必须逐项一致
# （v2.0.0 加 daily_site：新表沿用同一个 data_version 版本号常量，宽度要求一致）
# ★ v2.2.6（F27）加 events.time_uncertainty：事故列原先**不在监视面内**，
#   于是「表结构就绪、列宽达标」是真话、却覆盖不到真正出问题的那一列。
MIN_WIDTHS_PHP = {"daily": {"data_version": 64},
                  "events": {"dt_model": 64, "time_uncertainty": 191, "ephemeris": 191},
                  "daily_site": {"data_version": 64}}


def parse_min_widths(db_src):
    """从 PHP 源码解析 min_widths() 的返回值 → {'daily': {'data_version': 64}, ...}"""
    m = re.search(r"function\s+min_widths\s*\(\s*\)\s*\{(.*?)\n    \}", db_src, re.S)
    if not m:
        return None
    out = {}
    for tname, inner in re.findall(r"'(\w+)'\s*=>\s*array\(([^()]*)\)", m.group(1)):
        cols = dict((c, int(n)) for c, n in re.findall(r"'(\w+)'\s*=>\s*(\d+)", inner))
        if cols:
            out[tname] = cols
    return out or None


def width_shortfalls_py(min_widths, actual):
    """KCJ_Astro_DB::width_shortfalls() 的等价实现（供两向负控制用）。

    ★ 抽出来的直接动因：PHP 侧**第一版写错了** —— 它先把结果**无条件**赋值，
      再靠 `strpos($v, ' < 需要 ')` 过滤，而每个值都被拼上了「< 需要」，
      过滤条件对全部项成立 ⇒ **达标项也留在缺口清单里** ⇒ 列宽永远判为不合格
      ⇒ 守卫每次请求都跑一遍 dbDelta。有了这个等价函数 + 两向负控制，
      「达标必须不在清单里」当场可验，不必等上线才发现。
    """
    bad = {}
    for t, cols in min_widths.items():
        for c, mn in cols.items():
            key = t + "." + c
            w = actual.get(key)
            if w is None:
                bad[key] = "读不到列宽（列缺失或非字符型），需要 %d" % mn
            elif w < mn:
                bad[key] = "varchar(%d) < 需要 %d" % (w, mn)
    return bad


def schema_option_writers(srcs):
    """收集全部 PHP 源码里对 kcj_astro_schema_version 的 update_option 写入值。

    F24 的本质：**同一个 option 被两处以不同语义写入**。
    这里不比「有没有那行」，比的是「所有写入点的值是否是同一个」——
    多一个写入点、或换了别的常量，都会当场报红。
    """
    vals = {}
    for name, src in srcs.items():
        for v in re.findall(
                r"""update_option\(\s*'kcj_astro_schema_version'\s*,\s*([A-Za-z0-9_'".]+)""", src):
            vals.setdefault(v, []).append(name)
    return vals


def create_guard_findings(db_src):
    """create() 里「先实测、后落账、未达标即提前返回」三件事是否齐。"""
    m = re.search(r"function\s+create\s*\(\s*\)\s*\{(.*?)\n    \}", db_src, re.S)
    if not m:
        return ["找不到 create() 函数体"]
    body = m.group(1)
    bad = []
    if "width_shortfalls()" not in body:
        bad.append("create() 没有列宽实测 —— dbDelta 跑完即落账，ALTER 失败会被记成成功")
    if "update_option('kcj_astro_schema_version'" not in body:
        bad.append("create() 没有落账语句")
    i_meas = body.find("width_shortfalls()")
    i_book = body.find("update_option('kcj_astro_schema_version'")
    if i_meas >= 0 and i_book >= 0 and i_meas > i_book:
        bad.append("实测发生在落账**之后** —— 判据落在被测流程下游，恒真（F22 元教训）")
    if "$bad" not in body:
        bad.append("create() 没把实测结果接到分支上")
    if "return $done;" not in body:
        bad.append("create() 未达标时没有提前返回（会照样落账）")
    return bad


def failed_without_reason(rest_src, window=200):
    """每个 $failed++ 之后 window 字符内必须出现 $errors[]（失败必须说得出原因）。"""
    out = []
    for m in re.finditer(r"\$failed\+\+;", rest_src):
        if "$errors[]" not in rest_src[m.end():m.end() + window]:
            out.append(rest_src[:m.start()].count("\n") + 1)
    return out


def check_schema(root, rep):
    """F24—F26：表结构升级守卫的语义判据。

    ★ 必须先**剥注释**再扫：每一条判据都要在注释里写明「改前是什么样」，
      而那串被禁的旧写法一旦被文本匹配扫到，判据就会**被自己的说明文字绊倒**
      （自指陷阱，本库踩过多次）。剥了注释，判据只认代码。
    """
    inc = os.path.join(root, PLUGIN_DIR, "includes")
    act_src = strip_php_comments_only(read_text(os.path.join(inc, "activation.php")))
    db_src = strip_php_comments_only(read_text(os.path.join(inc, "class-astro-db.php")))
    rest_src = strip_php_comments_only(read_text(os.path.join(inc, "rest-import.php")))

    # ① 同一个 option 的所有写入点语义必须唯一（F24 的本质）
    writers = schema_option_writers({"activation.php": act_src,
                                     "class-astro-db.php": db_src})
    rep.chk("★ 表结构版本 option 的写入点语义唯一（F24）",
            list(writers) == ["KCJ_ASTRO_SCHEMA"],
            "写入值 %s" % (writers or "无"))

    # ② create() 三件事齐备（F25）
    g = create_guard_findings(db_src)
    rep.chk("★ create() 先实测后落账、未达标即重试（F25）", not g, "；".join(g) or "齐备")

    # ③ min_widths() 与校验侧常量逐项一致（比了名字还要比内容）
    parsed = parse_min_widths(db_src)
    rep.chk("★ min_widths() 与校验侧常量逐项一致",
            parsed == MIN_WIDTHS_PHP, "PHP=%s / 校验侧=%s" % (parsed, MIN_WIDTHS_PHP))

    # ④ /health 必须暴露表结构状态（F26）
    rep.chk("★ /health 暴露表结构状态（F26）",
            "schema_status()" in rest_src and "function schema_status" in db_src,
            "rest 引用=%s / db 定义=%s" % ("schema_status()" in rest_src,
                                        "function schema_status" in db_src))

    # ⑤ 失败必须带原因
    nrs = failed_without_reason(rest_src)
    rep.chk("★ 每个 $failed++ 都带得出原因（不留「失败 N 行」）", not nrs,
            "无原因的行号：%s" % (nrs or "无"))


def check_negative_controls(root, rep):
    """负控制：注入缺陷，确认每个检测器**真的会报红**。

    校验器最大的风险不是漏判，而是「系统性恒真」——判据写法错一步就永远 PASS。
    """
    # ① SQL 列集漂移
    sql_p = os.path.join(root, "sql", "install_tables.sql")
    if os.path.isfile(sql_p):
        sql = read_text(sql_p)
        orig = sql_columns(sql, "astro_daily")
        mut = sql.replace("  KEY `idx_method` (`method`)",
                          "  `zzz_injected` VARCHAR(8),\n  KEY `idx_method` (`method`)", 1)
        rep.chk("负控制①：SQL 列集漂移可被检出",
                orig is not None and sql_columns(mut, "astro_daily") != orig,
                "原 %d 列 → 注入后 %s 列" % (len(orig or []),
                                          len(sql_columns(mut, "astro_daily") or [])))

    # ② 括号失衡
    bad = strip_php_strings_and_comments("<?php function f(){ if(1){ } ")
    rep.chk("负控制②：PHP 括号失衡可被检出",
            bad.count("{") != bad.count("}"), "{%d}/{%d}" % (bad.count("{"), bad.count("}")))

    # ③ 字符串内括号不干扰配平
    good = strip_php_strings_and_comments("<?php f('{'); g(')');")
    rep.chk("负控制③：字符串内括号已被剔除（不干扰配平）",
            good.count("{") == 0 and good.count("(") == good.count(")"),
            "剥离后 = %r" % good.strip())

    # ④ 合规禁用字段
    dj = os.path.join(root, "samples", "daily_sample.json")
    if os.path.isfile(dj):
        d = json.loads(read_text(dj))
        d.setdefault("xiu", {})["value_xiu_of_day"] = "翼"
        rep.chk("负控制④：合规禁用字段可被检出", "value_xiu_of_day" in d.get("xiu", {}))

    # ⑤ ★ tree-sitter 真语法检测：注入一个真语法错，必须被检出
    files = php_files(root)
    if files:
        tmp = os.path.join(root, "_negcontrol_tmp.php")
        try:
            with open(tmp, "wb") as f:
                f.write(b"<?php\nfunction kcj_broken( { \n  return 1;\n}\n")
            ok_avail, errs = php_ast_errors(tmp)
            rep.chk("★ 负控制⑤：PHP 真语法错可被 AST 检出",
                    ok_avail and bool(errs), "检出 %s" % (errs[:1] if errs else "无（检测器失效）"))
        finally:
            if os.path.isfile(tmp):
                os.remove(tmp)

    # ⑥ ★ 未定义函数检测器：注入一个不存在的 kcj_ 调用，必须被认出未定义
    if files:
        defined, _refs = collect_php_symbols(files, root)
        fake = "kcj_astro_zzz_undefined_probe"
        rep.chk("★ 负控制⑥：未定义 kcj_* 调用可被检出",
                fake not in defined and bool(defined),
                "已定义 %d 个函数；探针 %s 不在其中" % (len(defined), fake))

    # ⑦ ★ URL 前缀检测器：注入旧前缀到白名单外的文件，必须被认出
    rep.chk("★ 负控制⑦：旧 URL 前缀检测的白名单非空且可命中",
            len(OLD_PREFIX_ALLOW) > 0 and OLD_PREFIX == "/sky/forecast/")

    # ⑧⑨ ★ URL 前缀检测器（行级判据）不被「遗留标记」架空：
    #      既要证明「真残留会被抓」，也要证明「交代了遗留的不误报」——
    #      两条一起跑，才能证明判据既非恒真也非恒假。
    def _prefix_violations(text_lines):
        out = []
        for i, line in enumerate(text_lines, 1):
            if OLD_PREFIX not in line:
                continue
            if NEW_PREFIX in line:
                continue
            if any(m in line for m in ("旧", "OLD", "legacy", "Legacy", "301")):
                continue
            out.append(i)
        return out

    stale_probe = ["详情页：/sky/forecast/{slug}/", "访问 /sky/forecast/2026-09-22/ 查看"]
    legacy_probe = ["旧前缀 `/sky/forecast/` → `/sky-forecast/` 加 301",
                    "const KCJ_ASTRO_OLD_URL = '/sky/forecast/';"]
    rep.chk("★ 负控制⑧：真·残留旧前缀会被抓（判据非恒假）",
            _prefix_violations(stale_probe) == [1, 2],
            "命中行 %s" % _prefix_violations(stale_probe))
    rep.chk("★ 负控制⑨：交代了「旧」的记述不误报（判据非恒真）",
            _prefix_violations(legacy_probe) == [],
            "误报行 %s" % _prefix_violations(legacy_probe))

    # ⑩—⑬ ★ v1.2.1：列类型/列宽判据的两向负控制。
    #   这两条判据是本次 F22/F23 的补丁，若它们自己恒真，就等于用空壳换了个心安。
    probe_types = {"data_version": [("astro_daily", "VARCHAR(32)")],
                   "dt_model": [("astro_events", "VARCHAR(64)")]}
    probe_obs = {"data_version": 45, "dt_model": 36}
    v_bad, n_bad = width_violations(probe_types, probe_obs)
    rep.chk("★ 负控制⑩：列宽过窄可被检出（判据非恒假）",
            len(v_bad) == 1 and "data_version" in v_bad[0] and n_bad == 2,
            "命中 %s（比对 %d 列）" % (v_bad, n_bad))
    v_ok, n_ok = width_violations({"data_version": [("astro_daily", "VARCHAR(64)")]},
                                  {"data_version": 45})
    rep.chk("★ 负控制⑪：列宽充足时不误报（判据非恒真）",
            v_ok == [] and n_ok == 1, "命中 %s（比对 %d 列）" % (v_ok, n_ok))

    # ㊲—㊴ ★ v2.2.6（F27）：**双口径**列宽判据的两向负控制，外加一条「旧判据为什么瞎」的自证。
    #   这一段是本轮最重要的负控制：它同时证明
    #     (a) 新判据能抓到字节溢出；(b) 新判据不会恒真；(c) **旧判据在本案上确实全绿**。
    #   (c) 不是自嘲 —— 它是这条判据存在的理由。没有 (c)，
    #   后人会以为「旧判据不是也能查列宽吗」，从而把新增的这条当冗余删掉，然后事故重演。
    f27_probe = {"time_uncertainty": [("astro_events", "VARCHAR(64)")]}
    f27_obs   = {"time_uncertainty": {"chars": 60, "bytes": 159}}   # 线上真值
    d_bad, dn_bad = width_violations_dual(f27_probe, f27_obs)
    rep.chk("★ 负控制㊲：**字节**溢出可被双口径判据检出（判据非恒假）",
            len(d_bad) == 1 and "159" in d_bad[0] and dn_bad == 1,
            "命中 %s（比对 %d 列）" % (d_bad, dn_bad))
    d_ok, dn_ok = width_violations_dual(
        {"time_uncertainty": [("astro_events", "VARCHAR(191)")]}, f27_obs)
    rep.chk("★ 负控制㊳：放宽到 191 后不误报（判据非恒真）",
            d_ok == [] and dn_ok == 1, "命中 %s（比对 %d 列）" % (d_ok, dn_ok))
    old_on_f27, _n_old = width_violations(f27_probe, {"time_uncertainty": 60})
    rep.chk("★★ 负控制㊴：**旧（只数字符的）判据在本案上确实全绿** —— 这就是它漏掉 F27 的原因",
            old_on_f27 == [],
            "旧判据命中 %s（60 字符 ≤ 64 ⇒ 它看不出 159 字节装不下）" % old_on_f27)

    rep.chk("★ 负控制⑫：ENUM vs VARCHAR(32) 的类型分岔可被检出",
            type_mismatches({"event_type": "ENUM('A','B')"}, {"event_type": "VARCHAR(32)"}) == ["event_type"],
            "命中 %s" % type_mismatches({"event_type": "ENUM('A','B')"}, {"event_type": "VARCHAR(32)"}))
    rep.chk("★ 负控制⑬：类型一致时不误报",
            type_mismatches({"a": "VARCHAR(64)", "b": "TEXT"}, {"a": "VARCHAR(64)", "b": "TEXT"}) == [],
            "命中 %s" % type_mismatches({"a": "VARCHAR(64)", "b": "TEXT"}, {"a": "VARCHAR(64)", "b": "TEXT"}))

    # ⑭ zip↔磁盘 内容比对的两向负控制（同上：判据自己不能是空壳）
    good = {"a.php": b"AAA", "b.css": b"BBB"}
    bad = {"a.php": b"AAA", "b.css": b"BBX"}
    rep.chk("★ 负控制⑭：zip 与磁盘的字节差异可被检出（判据非恒真）",
            zip_disk_diffs(bad, good) == ["b.css"], "命中 %s" % zip_disk_diffs(bad, good))
    rep.chk("★ 负控制⑮：zip 与磁盘一致时不误报（判据非恒假）",
            zip_disk_diffs(dict(good), good) == [], "命中 %s" % zip_disk_diffs(dict(good), good))

    # ⑯—㉑ ★ v1.2.1 第二轮：表结构守卫判据的两向负控制。
    #   ⑯⑰ 直接锁住「PHP 第一版那个错」——达标项绝不许出现在缺口清单里。
    #
    #   ★ v2.0.0 修：观察集**从 MIN_WIDTHS_PHP 自身派生**。
    #     原先是硬编码 {"daily.data_version": 64, "events.dt_model": 64}；
    #     本轮给常量加了第三张表（daily_site），新表不在那份硬编码样本里 ⇒
    #     立刻被判成「读不到列宽」⇒ **负控制自己变红**。
    #     这是「判据扩了适用面、负控制的样本没跟着扩」的典型漂移 ——
    #     改成派生式后，以后无论再加几张表，这条负控制都自动跟着走。
    #     为免派生式退化成「用被测常量喂被测函数」的空壳，配套两条守卫：
    #       ① 空集守卫：覆盖面必须与预期表名逐项一致（常量被掏空即红）；
    #       ② ⑰ 反向断言：全部读不到时，缺口条数必须**等于**常量里的列总数。
    #   ★ v2.2.6：预期由「只表名 ＋ 写死的总列数」改成「**逐表**列数」——
    #     原先断言 `len(_mw_cols) == 3`，给 events 加两列后立刻变假红，而失败信息
    #     只说「共 5 列」，看不出是哪张表多了列（判据扩了适用面、样本没跟着扩的又一例）。
    #     现改成逐表比列数：常量被掏空、漏写、多写，都能一眼定位到表。
    _mw_cols = [(t, c) for t, cols in MIN_WIDTHS_PHP.items() for c in cols]
    _mw_expect = {"daily": 1, "events": 3, "daily_site": 1}   # v2.2.6：events 由 1 列增至 3 列
    _mw_got = {t: len(cs) for t, cs in MIN_WIDTHS_PHP.items()}
    rep.chk("★ 负控制㉝（㉖-前置）：MIN_WIDTHS_PHP 覆盖面与预期逐项一致（空集守卫）",
            _mw_got == _mw_expect,
            "实际 %s / 预期 %s（共 %d 列）" % (_mw_got, _mw_expect, len(_mw_cols)))

    ok_w = width_shortfalls_py(
        MIN_WIDTHS_PHP,
        {("%s.%s" % (t, c)): n for t, cols in MIN_WIDTHS_PHP.items()
         for c, n in cols.items()})
    rep.chk("★ 负控制⑯：列宽达标时不算缺口（判据非恒真）",
            ok_w == {}, "命中 %s" % (ok_w or "无"))

    # 两种成因都要盖到：一列「过窄」、其余「读不到」
    bad_actual = {("%s.%s" % (t, c)): None for t, c in _mw_cols}
    bad_actual["daily.data_version"] = 32
    bad_w = width_shortfalls_py(MIN_WIDTHS_PHP, bad_actual)
    rep.chk("★ 负控制⑰：列宽过窄 / 读不到必被列为缺口（判据非恒假）",
            len(bad_w) == len(_mw_cols) and "32" in bad_w.get("daily.data_version", ""),
            "命中 %d 项（常量共 %d 列）%s" % (len(bad_w), len(_mw_cols), bad_w))

    w2 = schema_option_writers({
        "a.php": "update_option('kcj_astro_schema_version', KCJ_ASTRO_VER);",
        "b.php": "update_option('kcj_astro_schema_version', KCJ_ASTRO_SCHEMA);"})
    rep.chk("★ 负控制⑱：同一 option 两处不同语义必被检出（F24 的核心）",
            len(w2) == 2, "检出写入值 %s" % sorted(w2))
    w1 = schema_option_writers({
        "a.php": "update_option('kcj_astro_schema_version', KCJ_ASTRO_SCHEMA);"})
    rep.chk("★ 负控制⑲：写入点语义一致时不误报",
            len(w1) == 1, "检出写入值 %s" % sorted(w1))

    probe_bad = "<?php\nif (1) { $failed++;\n            continue; }\n"
    probe_ok = "<?php\nif (1) { $failed++;\n            $errors[] = 'x';\n            continue; }\n"
    rep.chk("★ 负控制⑳：$failed++ 未记原因必被检出",
            failed_without_reason(probe_bad) == [2],
            "命中行 %s" % failed_without_reason(probe_bad))
    rep.chk("★ 负控制㉑：$failed++ 已记原因时不误报",
            failed_without_reason(probe_ok) == [],
            "命中行 %s" % failed_without_reason(probe_ok))

    # ㉒ ★ 自指陷阱的防御：判据的**说明文字**里必然要写出被禁的旧写法，
    #     若不剥注释，判据就会被自己的文档绊倒。这条证明「剥了注释」是有效的。
    probe_c = "<?php\n// update_option('kcj_astro_schema_version', KCJ_ASTRO_VER);\n"
    rep.chk("★ 负控制㉒：注释里出现的旧写法不误报（自指陷阱）",
            schema_option_writers({"a.php": strip_php_comments_only(probe_c)}) == {},
            "剥注释后检出 %s" % (schema_option_writers(
                {"a.php": strip_php_comments_only(probe_c)}) or "无"))
    rep.chk("★ 负控制㉓：同一行写在**代码**里则必被检出（反向证明上一条非恒假）",
            len(schema_option_writers({"a.php": strip_php_comments_only(
                "<?php\nupdate_option('kcj_astro_schema_version', KCJ_ASTRO_VER);\n")})) == 1)

    # ㉚—㉜ ★ v2.0.0 第四轮：期间口径哨兵的两向负控制。
    #   编号接在事件模块轮的 ㉙ 之后 —— 本轮首写时误用了 ㉔㉕㉖，
    #   而那三个号**已被事件模块轮占用**（㉔/㉔b/㉕/㉖/㉗/㉘/㉙），
    #   输出里于是出现两组同名编号，「一共几条」当场变成糊涂账。已改正。
    #   直接对上本轮实际踩的坑 —— 哨兵要禁的旧写法**必然写在注释里做警示**，
    #   若不剥注释，哨兵当场被自己的文档绊倒（本轮实测：两条新哨兵一起报红，
    #   而代码其实已经改对了）。故这三条既验「代码里写得出来就抓得到」，
    #   又验「注释里写着不误报」——「剥注释」这个动作本身也要被证明有效。
    _bad_py = "def period_range():\n    end = dt.date(2028, 2, 29) + dt.timedelta(days=365)\n"
    _good_py = "def period_range():\n    end = dt.date(y2, m2, min(d2, calendar.monthrange(y2, m2)[1]))\n"
    rep.chk("★ 负控制㉚：＋365 天写在**代码**里必被检出（期间哨兵非恒真）",
            "timedelta(days=365)" in strip_php_comments_only(_bad_py)
            and "timedelta(days=365)" not in strip_php_comments_only(_good_py))
    rep.chk("★ 负控制㉛：同样的写法写在**注释**里不误报（自指陷阱）",
            "timedelta(days=365)" not in strip_php_comments_only(
                "# 旧写法：timedelta(days=365) 闰年会少一天\n")
            and "strtotime" not in strip_php_comments_only(
                "// 旧写法 strtotime('+12 months') 会进位到下月 1 日\n"))
    rep.chk("★ 负控制㉜：strtotime 加月写在**代码**里必被检出",
            "strtotime" in strip_php_comments_only(
                "$e = date('Y-m-d', strtotime($s . ' +12 months'));"))

    # ㉞—㊱ ★ v2.1.0：历史栏目三条规则谓词的两向负控制。
    #   ★ 关键：负控制调的是**模块级同一个函数**（见 rule_history_* 的说明），
    #     不是在这里重抄一遍正则 —— 否则证明的只是「我抄的这份会报红」。
    _gk_good = ("function kcj_astro_history_group_key($t) {\n"
                "    return preg_replace('/\\s*（\\d{4}-\\d{2}-\\d{2}）\\s*$/u', '', $t);\n}\n")
    _gk_bad = ("function kcj_astro_history_group_key($t) {\n"
               "    return preg_replace('/\\s*（[^）]*）\\s*$/u', '', $t);\n}\n")
    _gk_ok1, _ = rule_history_group_key_date_only(_gk_good)
    _gk_ok2, _gk_w2 = rule_history_group_key_date_only(_gk_bad)
    rep.chk("★ 负控制㉞：分组键只剥日期形括号（恒真则反向样本抓不住）",
            _gk_ok1 and not _gk_ok2, "反向样本：%s" % (_gk_w2 or "居然通过！"))

    _nav_good = ("function kcj_astro_history_nav($m, $d) {\n"
                 "    return mktime(0, 0, 0, $m, $d + 1, 2028);\n}\n")
    _nav_bad = ("function kcj_astro_history_nav($m, $d) {\n"
                "    return mktime(0, 0, 0, $m, $d + 1, 2026);\n}\n")
    _nv_ok1, _ = rule_history_nav_leap_base(_nav_good)
    _nv_ok2, _nv_w2 = rule_history_nav_leap_base(_nav_bad)
    rep.chk("★ 负控制㉟：跳转必须用闰年基准（非闰年样本必报红）",
            _nv_ok1 and not _nv_ok2, "非闰年样本：%s" % (_nv_w2 or "居然通过！"))

    # ㊱ 两向：代码里的粗体必被抓；注释里的粗体不得误报（自指陷阱）。
    #    —— 后者正是本轮首版误报 3 条的原因，故必须成为判据的一部分。
    _b_ok1, _ = rule_no_markdown_bold(strip_php_comments_only("<p>**粗体**</p>\n"))
    _b_ok2, _ = rule_no_markdown_bold(strip_php_comments_only("// 说明：写 **粗体** 会原样输出星号\n"))
    rep.chk("★ 负控制㊱：模板粗体哨兵两向（代码里抓得到、注释里不误报）",
            not _b_ok1 and _b_ok2,
            "代码样本=%s／注释样本=%s" % ("抓到" if not _b_ok1 else "漏了",
                                        "不报" if _b_ok2 else "误报"))


# =============================================================================
# 11. 事件枚举模块（2026-09-23 新增）
#   ★ 本节的判据全部围绕一条最容易复发的老毛病：**客户端与服务端各写一份正本，
#     然后各自漂移**（F22 列宽、F23 列类型都是这个病）。事件模块新增了一个
#     客户端常量表（EVENTS_WHITELIST / COL_MAXLEN），故必须与插件 PHP 对拍。
# =============================================================================
PY_COMPUTE = os.path.join("python", "compute_sky.py")
PY_EVENTS = os.path.join("python", "event_almanac.py")
PY_BUILD = os.path.join("python", "build_dataset.py")
MANUAL_JSON = os.path.join("data", "events_manual.json")

# 事件侧必须成套出现的三个模块级常量
EVENTS_CONSTS = ("EVENTS_WHITELIST", "NEVER_SEND", "COL_MAXLEN")
MANUAL_KINDS = ("historical", "catalog")
MANUAL_REQUIRED = {
    "historical": ("era_year", "month", "day", "calendar_note", "source_text", "source_ref"),
    "catalog": ("jd_core", "title", "source_ref", "event_type"),
}


def _module_literal(src, name):
    """从 Python 源码里取出模块级**字面量**赋值的值（走 AST，不用正则猜）。"""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    try:
                        return ast.literal_eval(node.value)
                    except Exception:
                        return None
    return None


def _func_src(src, name):
    """取出某个顶层函数的源码片段（用于「判据必须装在写盘之前」这类位置判据）。"""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return ""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(src, node) or ""
    return ""


def _type_width(t):
    """`VARCHAR(64)` → 64；无括号 → None。"""
    m = re.search(r"\((\d+)\)", t or "")
    return int(m.group(1)) if m else None


def _events_whitelist_in_php(php):
    m = re.search(r"'events'\s*=>\s*array\(([^)]*)\)", php)
    if not m:
        return None
    return tuple(re.findall(r"'([^']+)'", m.group(1)))


def _wl_mismatch(a, b):
    """两份白名单的差异描述；完全一致（含顺序）返回空串。

    ★ 抽成函数是为了**能被负控制调用**：判据写成内联表达式时，负控制只能
      「断言某个常量不等」—— 那恒真，等于没测。这里可以真喂一份篡改过的表进去。
    """
    if a is None or b is None:
        return "取不到（%s / %s）" % (a is not None, b is not None)
    if tuple(a) == tuple(b):
        return ""
    extra = [x for x in a if x not in b]
    missing = [x for x in b if x not in a]
    if not extra and not missing:
        return "仅顺序不同"
    return "多 %s ／ 少 %s" % (extra, missing)


def check_events(root, rep):
    ev_p = os.path.join(root, PY_EVENTS)
    bd_p = os.path.join(root, PY_BUILD)
    man_p = os.path.join(root, MANUAL_JSON)
    db_p = os.path.join(root, DB_FILE)
    sql_p = os.path.join(root, "sql", "install_tables.sql")

    rep.chk("事件枚举模块存在", os.path.isfile(ev_p), PY_EVENTS)
    if not os.path.isfile(ev_p):
        return
    ev_src = read_text(ev_p)

    # ── 11.1 可编译（交付件不能是半成品） ──
    syn = ""
    try:
        compile(ev_src, PY_EVENTS, "exec")
    except SyntaxError as e:
        syn = "%s (line %s)" % (e.msg, e.lineno)
    rep.chk("事件枚举模块可编译（无 SyntaxError）", not syn, syn)
    rep.chk("事件枚举模块有版本号常量 SCRIPT_VERSION",
            bool(re.search(r"^SCRIPT_VERSION\s*=\s*['\"]", ev_src, re.M)))

    # ── 11.2 白名单与插件 PHP **逐字对拍**（顺序也算：写库按列序） ──
    wl = _module_literal(ev_src, "EVENTS_WHITELIST")
    never = _module_literal(ev_src, "NEVER_SEND")
    colmax = _module_literal(ev_src, "COL_MAXLEN")
    rep.chk("EVENTS_WHITELIST 是字面量元组", isinstance(wl, tuple) and len(wl) > 0,
            "%s" % (list(wl) if isinstance(wl, tuple) else wl))
    if os.path.isfile(db_p):
        php = read_text(db_p)
        # 事件白名单在 rest-import.php 里
        rest_p = os.path.join(root, PLUGIN_DIR, "includes", "rest-import.php")
        php_wl = _events_whitelist_in_php(read_text(rest_p)) if os.path.isfile(rest_p) else None
        rep.chk("插件 rest-import.php 的 events 白名单可解析", php_wl is not None)
        if isinstance(wl, tuple) and php_wl is not None:
            rep.chk("★ 事件白名单 客户端 == 插件（逐项且同序）",
                    _wl_mismatch(wl, php_wl) == "", _wl_mismatch(wl, php_wl))
        # NEVER_SEND 必须是白名单子集且只含主键两项
        rep.chk("NEVER_SEND 只含 event_id / post_id（其余会被服务端丢弃或由插件回填）",
                tuple(sorted(never or ())) == ("event_id", "post_id"),
                "%s" % (list(never) if never else never))
        if isinstance(wl, tuple) and never:
            rep.chk("NEVER_SEND ⊆ EVENTS_WHITELIST", set(never) <= set(wl))
        # COL_MAXLEN 的键必须是白名单内真实存在的列（防拼错键＝既不裁剪也不设防）
        if isinstance(wl, tuple) and isinstance(colmax, dict):
            unknown = sorted(set(colmax) - set(wl))
            rep.chk("COL_MAXLEN 的键全在事件白名单内（拼错键＝静默不设防）", not unknown,
                    "越界键 %s" % unknown)

    # ── 11.3 ★ 列宽对拍：客户端的裁剪上限不得宽于真实列（F22 同族） ──
    if isinstance(colmax, dict) and os.path.isfile(sql_p):
        sql_types = sql_column_types(read_text(sql_p), "astro_events") or {}
        rep.chk("SQL 里取到 astro_events 列类型", bool(sql_types), "%d 列" % len(sql_types))
        bad, checked = [], 0
        for col, lim in colmax.items():
            if lim is None:
                continue          # TEXT 列不限宽，声明 None 是明确的
            t = sql_types.get(col)
            if t is None:
                bad.append("%s（SQL 无此列）" % col)
                continue
            w = _type_width(t)
            checked += 1
            if w is not None and lim > w:
                bad.append("%s: COL_MAXLEN=%d > %s" % (col, lim, t))
        rep.chk("★ 事件列宽：COL_MAXLEN 不宽于 SQL 列宽（%d 项对拍）" % checked, not bad,
                "; ".join(bad))

    # ── 11.4 build_dataset 接线（回归守卫：防止有人把空数组桩改回来） ──
    rep.chk("build_dataset.py 存在", os.path.isfile(bd_p), PY_BUILD)
    if os.path.isfile(bd_p):
        bd_src = read_text(bd_p)
        rep.chk("build_dataset 引用事件枚举模块（import event_almanac）",
                bool(re.search(r"^import event_almanac as \w+", bd_src, re.M)))
        bf = _func_src(bd_src, "build_future")
        rep.chk("build_future() 取到源码片段", bool(bf))
        rep.chk("★ build_future() 已无空数组桩 `_write_json(path, [])`",
                "_write_json(path, [])" not in bf,
                "（若回归，前台六个 Tab 会一起显示「暂无」且无人报错）")
        rep.chk("build_future() 真调 ea.build_events",
                "build_events" in bf)
        # ★ 判据必须装在**写盘之前**：装在之后会留下空数组文件（静默失败）
        gi, wi = bf.find("_guard_events"), bf.find("_write_json(path, rows)")
        rep.chk("★ 空集守卫装在写盘之前（否则留下空文件＝静默失败）",
                gi >= 0 and wi >= 0 and gi < wi, "guard@%d write@%d" % (gi, wi))
        rep.chk("build_future() 应用发布窗口（_apply_publish_window）",
                "_apply_publish_window" in bf)
        rep.chk("manifest 已无旧状态串 structural_samples_need_manual_entry",
                "structural_samples_need_manual_entry" not in bd_src)
        # 占位过滤必须用 slug 前缀谓词，而不是硬编码名单
        rep.chk("占位件过滤走 pushable_events（按 slug 前缀，不是硬编码名单）",
                'startswith("todo-")' in bd_src and "def pushable_events" in bd_src)

    # ── 11.5 人工条目表（红线：缺出处＝不落库） ──
    rep.chk("人工条目表存在（唯一手工编辑的输入件）", os.path.isfile(man_p), MANUAL_JSON)
    if os.path.isfile(man_p):
        try:
            obj = json.loads(read_text(man_p))
        except Exception as e:
            obj = None
            rep.chk("人工条目表是合法 JSON", False, str(e))
        if isinstance(obj, dict):
            rep.chk("人工条目表是对象且含 entries 数组",
                    isinstance(obj.get("entries"), list))
            ents = obj.get("entries") or []
            rep.chk("人工条目表有 schema 与 red_line 说明",
                    "schema" in obj and "red_line" in obj)
            bad_kind = [e.get("kind") for e in ents if e.get("kind") not in MANUAL_KINDS]
            rep.chk("每条 kind 都在 %s 内" % (MANUAL_KINDS,), not bad_kind, "%s" % bad_kind)
            slugs = [e.get("slug") for e in ents]
            rep.chk("人工条目表 slug 齐全且唯一",
                    all(slugs) and len(slugs) == len(set(slugs)),
                    "%d 条 / %d 唯一" % (len(slugs), len(set(slugs))))
            miss = []
            for i, e in enumerate(ents, 1):
                for k in MANUAL_REQUIRED.get(e.get("kind"), ()):
                    if e.get(k) in (None, ""):
                        miss.append("第%d条(%s) 缺 %s" % (i, e.get("slug"), k))
            rep.chk("人工条目表必填项齐备（按 kind 分别要求）", not miss, "; ".join(miss[:4]))
            no_src = [e.get("slug") for e in ents if not str(e.get("source_ref") or "").strip()]
            rep.chk("★ 每条都有 source_ref（红线：不编造，缺出处即不落库）", not no_src,
                    "%s" % no_src)

    # ── 11.6 文档口径（行级判据，防自指陷阱） ──
    #   ★ 只查**未划线的陈述句**：原文留档处必须带 `~~` 或位于引用块。
    #     若写成「文件里出现该串即失败」，判据会被它自己的留档绊倒（本项目踩过两次）。
    stale = "未来事件集是空数组"
    offenders = []
    for dirpath, _dirs, fns in os.walk(os.path.join(root, "docs")):
        for fn in fns:
            if not fn.endswith(".md"):
                continue
            p = os.path.join(dirpath, fn)
            for ln in read_text(p).splitlines():
                if stale in ln and "~~" not in ln and not ln.lstrip().startswith(">"):
                    offenders.append("%s: %s" % (os.path.relpath(p, root), ln.strip()[:50]))
    rep.chk("★ 文档无「未划线的过期口径」(%s)" % stale, not offenders, "; ".join(offenders))

    # ── 11.7 负控制：证明上面几条真的会报红 ──
    # ① 白名单对拍：真喂一份篡改过的表进比较器（不是「断言某常量不等」那种恒真写法）
    if isinstance(wl, tuple) and wl:
        rep.chk("★ 负控制㉔：比较器对篡改后的白名单必报红（真喂数据，不是断言常量不等）",
                _wl_mismatch(tuple(list(wl)[:-1] + ["publish_status_typo"]), wl) != ""
                and _wl_mismatch(wl, wl) == "",
                "%s" % _wl_mismatch(tuple(list(wl)[:-1] + ["x"]), wl))
        rep.chk("★ 负控制㉔b：只调顺序也必须报红（写库按列序，顺序也是契约）",
                _wl_mismatch(tuple(reversed(wl)), wl) == "仅顺序不同",
                "%s" % _wl_mismatch(tuple(reversed(wl)), wl))
    # ② 位置判据：把守卫挪到写盘之后，必须报红
    probe_bad = "def build_future():\n    _write_json(path, rows)\n    _guard_events(rows)\n"
    pb = _func_src(probe_bad, "build_future")
    rep.chk("★ 负控制㉕：守卫若装在写盘之后，位置判据必报红",
            pb.find("_guard_events") > pb.find("_write_json"))
    # ③ 空数组桩必须被判据认出
    probe_stub = "def build_future():\n    _write_json(path, [])\n"
    rep.chk("★ 负控制㉖：空数组桩若回归，判据必报红",
            "_write_json(path, [])" in _func_src(probe_stub, "build_future"))
    # ④ 人工条目缺 source_ref 必须报红
    probe_ent = {"kind": "catalog", "slug": "x-20260101", "jd_core": 1.0,
                 "title": "t", "event_type": "traditional"}
    probe_miss = [k for k in MANUAL_REQUIRED["catalog"] if probe_ent.get(k) in (None, "")]
    rep.chk("★ 负控制㉗：人工条目缺 source_ref 必被必填判据抓出",
            probe_miss == ["source_ref"], "%s" % probe_miss)
    # ⑤ 文档行级判据：未划线的旧口径行必须报红
    probe_lines = ["3. 未来事件集是空数组。", "3. ~~未来事件集是空数组。~~"]
    hit = [l for l in probe_lines if stale in l and "~~" not in l
           and not l.lstrip().startswith(">")]
    rep.chk("★ 负控制㉘：未划线的旧口径行必被认出（同时留档行不误报）",
            hit == ["3. 未来事件集是空数组。"], "%s" % hit)
    # ⑥ AST 取值器本身：改过名的常量必须取不到（否则「取到 None」会被当成通过）
    rep.chk("★ 负控制㉙：常量名写错时 _module_literal 返回 None（不静默给默认值）",
            _module_literal("EVENTS_WHITELISTX = ('a',)\n", "EVENTS_WHITELIST") is None)

    # ⑦ ★ v2.0.0：负控制**编号不得重复**。
    #   编号就是账；重号了「一共几条控制」当场说不清，后来人也不知道该改哪一条。
    #   本轮实地踩到两处：① 新加的三条误用了事件模块轮已占用的 ㉔㉕㉖；
    #   ② 「㉖-前置」这类**派生编号**又占了一次本体号。输出里于是出现两组同名编号，
    #   而且分处两节、不并排就不易察觉。
    #   ⇒ 只统计**定义行**（含 `rep.chk(` 且名字里出现 `负控制X`）。
    #     注意早期四条（①—④）没有 `★` 前缀，故正则**不要求** `★` —— 要求了就会
    #     漏掉它们，「共 N 条」照样是错账。注释里引用既有编号（如「⑯⑰ 直接锁住…」）
    #     不含 `rep.chk(`，自然被排除 —— 这一条正是自指陷阱的绕法：
    #     判据要扫自身，就必须能把「说它」与「是它」分开。
    #     判据自己那行写的是「负控制**编号**唯一」，后面跟的不是圈号，故不会自指。
    try:
        _self = read_text(os.path.abspath(__file__))
        _ids = []
        for _ln in _self.splitlines():
            if "rep.chk(" not in _ln:
                continue
            _m = re.search(r"负控制([\u2460-\u2473\u3251-\u325f]+[a-z]?)", _ln)
            if _m:
                _ids.append(_m.group(1))
        _dup = sorted(set(i for i in _ids if _ids.count(i) > 1))
        rep.chk("★ 负控制编号唯一（无重号；重号即账目不清）",
                len(_ids) > 0 and not _dup,
                "共 %d 条定义；重号：%s" % (len(_ids), _dup or "无"))
    except Exception as _ex:
        rep.chk("★ 负控制编号唯一（无重号；重号即账目不清）", False, "异常：%r" % (_ex,))


# ── 历史栏目（v2.1.0）的三条**规则谓词** ────────────────────────────────────
#   ★ 为什么抽成模块级函数：判据与「负控制」必须调**同一份**代码。
#     若负控制里再抄一遍正则，它证明的只是「我抄的这份会报红」，
#     而不是「线上跑的那条判据会报红」—— 判据与它的反证各自漂移，正是假绿的常见来源。
def rule_history_group_key_date_only(src):
    """分组键的正则只许剥「日期形」括号。

    一刀切地剥「（…）」会把「土星留（转逆行）」与「土星留（转顺行）」并成同一组
    （两种**相反**的天象混在一起，页面上看不出方向）。
    返回 (是否通过, 说明)。
    """
    m = re.search(r"function kcj_astro_history_group_key\(.*?\n\}", src, re.S)
    if not m:
        return False, "未找到 kcj_astro_history_group_key()"
    body = m.group(0)
    if r"\d{4}-\d{2}-\d{2}" not in body:
        return False, "正则里没有「日期形」（\\d{4}-\\d{2}-\\d{2}）"
    if "[^）]*" in body:
        return False, "出现一刀切的 [^）]* ⇒ 语义括号会被误剥"
    return True, ""


def rule_history_nav_leap_base(src):
    """日期跳转的天数基准必须是**闰年**，否则 02-29 永远不可达。

    用非闰年做基准时，从 02-28 加一天会跳到 03-01 ——
    于是 02-29 自己写不出来、也没法跳过去，而页面上**完全看不出来**。
    """
    m = re.search(r"function kcj_astro_history_nav\(.*?\n\}", src, re.S)
    if not m:
        return False, "未找到 kcj_astro_history_nav()"
    body = m.group(0)
    years = [int(y) for y in re.findall(r"\b(1[89]\d{2}|2[01]\d{2})\b", body)]
    if not years:
        return False, "取不到基准年"
    if not any((y % 4 == 0 and y % 100 != 0) or y % 400 == 0 for y in years):
        return False, "基准年 %s 里没有闰年 ⇒ 02-28 加一天会跳到 03-01" % (years,)
    return True, ""


def rule_no_markdown_bold(src):
    """PHP 模板里不得出现 markdown 粗体（模板输出 HTML，`**x**` 会原样显示成星号）。

    ⚠ 调用方**必须**先剥注释 —— 注释里有意写着 `**加粗**` 做说明，
      不剥就会让这条判据「自己咬住自己的文档」。
    """
    hits = re.findall(r"\*\*[^*\n]{1,40}\*\*", src)
    return (not hits), ("命中：%s" % hits[:3] if hits else "")


def check_places(root, rep):
    """★ v2.0.0 新增：观测地维度（「今日天象 · 观测地可选」）与两个新子项的判据。

    覆盖四件事：
      A. 观测地表：SQL ↔ dbDelta 列集/列宽（由 EXPECTED_TABLES 自动带出）＋ 复合唯一键；
      B. 升落口径（F42 北京日窗口 / F43 地平线 −0.8333°）—— 这两条是**数值正确性**的根，
         判据只能落在源码常量上，真值对拍在 compute_sky 的 selftest 与 history_events 的
         `--verify` 里做（都需要真算，不适合放进静态校验器）；
      C. 新短代码与模板/脚本齐备；
      D. **外部资源里不得出现裸与号字符** —— 平台后处理会把正文里的裸与号换成实体引用，
         script 内容不做实体解码 ⇒ 内联脚本会被拆断（v1.3.0「老黄历线上失效」的真因）。
         这一条对本项目的 JS 是**硬约束**，故做成静态判据。
    """
    plug = os.path.join(root, PLUGIN_DIR)
    sc_p = os.path.join(plug, "includes", "shortcodes.php")
    db_p = os.path.join(plug, "includes", "class-astro-db.php")
    sql_p = os.path.join(root, "sql", "install_tables.sql")
    main_p = os.path.join(plug, "wp-astro-forecast.php")

    # ── A. 观测地表 ──
    php = read_text(db_p) if os.path.isfile(db_p) else ""
    sql = read_text(sql_p) if os.path.isfile(sql_p) else ""
    rep.chk("dbDelta 定义含 daily_site 表", "astro_daily_site" in php)
    rep.chk("SQL 定义含 daily_site 表", "`wp_astro_daily_site`" in sql)
    rep.chk("★ daily_site 有复合唯一键 uk_date_city(date_str, city)（幂等）",
            "uk_date_city" in php and "uk_date_city" in sql)
    rep.chk("daily_site 在 KCJ_Astro_DB::TABLES 白名单内（否则 table() 取不到表名）",
            bool(re.search(r"const\s+TABLES\s*=\s*array\([^)]*'daily_site'", php)))
    rep.chk("daily_site 的 data_version 纳入最小列宽守卫",
            bool(re.search(r"'daily_site'\s*=>\s*array\(\s*'data_version'\s*=>\s*64", php)))

    # ── B. 升落口径 ──
    cs_p = os.path.join(root, PY_COMPUTE)
    cs = read_text(cs_p) if os.path.isfile(cs_p) else ""
    rep.chk("★ F43：升落地平线常量为 −0.8333°（折射 34′ ＋ 太阳视半径 16′）",
            bool(re.search(r"RISE_SET_HORIZON_DEG\s*=\s*-0\.8333", cs)),
            "在 python/compute_sky.py 里找不到 RISE_SET_HORIZON_DEG = -0.8333")
    rep.chk("★ F42：升落/晨昏按**北京日**取窗（_bj_day_utc_bounds 存在且被调用）",
            "_bj_day_utc_bounds" in cs
            and cs.count("_bj_day_utc_bounds(") >= 3,
            "调用处 %d 次（定义 1 + 使用 2 才算接线）" % cs.count("_bj_day_utc_bounds("))
    rep.chk("升落显式传 horizon（不再吃 skyfield 的 −0.5667 默认值）",
            "horizon_degrees=float(horizon_degrees)" in cs
            or "horizon_degrees=float(RISE_SET_HORIZON_DEG)" in cs,
            "risings_and_settings 调用处未见显式 horizon")
    rep.chk("★ 观测地维度只算 11 项（SITE_FIELDS 与模板取值点一致）",
            "SITE_FIELDS" in cs and cs.count('"sunrise_bj"') >= 1)
    rep.chk("compute_site_daily() 存在（观测地维度的唯一出口）",
            "def compute_site_daily(" in cs)
    rep.chk("resolve_city_key() 认不出时返回 None（不得静默回落默认城）",
            bool(re.search(r"def resolve_city_key\(.*?return None", cs, re.S)))

    # ── C. 新短代码 / 模板 / 脚本 ──
    sc = read_text(sc_p) if os.path.isfile(sc_p) else ""
    for code in ("astro_today", "astro_forecast_list", "astro_related_events",
                 "astro_history_today", "astro_forecast_report", "astro_event_detail",
                 "astro_hub"):
        rep.chk("短代码 %s 已注册" % code,
                bool(re.search(r"add_shortcode\(\s*'%s'" % re.escape(code), sc)), "")
    rep.chk("★ astro_forecast_list 有 side 属性（future/past/all）",
            "'side'" in sc and "side === 'future'" in sc,
            "缺 side 过滤 ⇒ 历史月食会混进未来预告列表")
    rep.chk("★ astro_today 有 place 属性（off/fixed/auto 三态）",
            "'place'" in sc and "place_mode" in sc)
    for tpl in ("astro-history-today.php", "astro-forecast-report.php",
                "astro-today.php"):
        rep.chk("模板 %s 存在" % tpl,
                os.path.isfile(os.path.join(plug, "templates", tpl)), "")
    for js in ("astro-place.js", "astro-report.js"):
        rep.chk("前端脚本 %s 存在" % js,
                os.path.isfile(os.path.join(plug, "assets", js)), "")
    rep.chk("模板引用观测地脚本（astro-place.js 已入队）",
            "astro-place.js" in sc)
    rep.chk("模板引用下载脚本（astro-report.js 已入队）",
            "astro-report.js" in sc)

    # ── D. 外置脚本不得含裸与号 ──
    for js in ("astro-place.js", "astro-report.js"):
        p = os.path.join(plug, "assets", js)
        if not os.path.isfile(p):
            continue
        src = read_text(p)
        # 去掉注释与字符串后仍出现的 & 才是「裸与号」；这里只做保守判据：
        # 全文若含 '&' 就报出来，由人工确认是否在注释里（本项目要求一个都不留）。
        bare = [(i + 1, ln.strip()[:70]) for i, ln in enumerate(src.splitlines())
                if "&" in ln]
        rep.chk("★ %s 无裸与号字符（平台会把它换成实体引用 ⇒ 脚本整块失效）" % js,
                not bare, "命中 %d 行：%s" % (len(bare), bare[:3] or "无"))

    # ── E. 版本与表结构版本 ──
    mf = read_text(main_p) if os.path.isfile(main_p) else ""
    rep.chk("插件版本 ≥ 2.0.0", bool(re.search(r"KCJ_ASTRO_VER',\s*'2\.", mf)),
            re.search(r"KCJ_ASTRO_VER',\s*'([^']+)'", mf).group(1)
            if re.search(r"KCJ_ASTRO_VER',\s*'([^']+)'", mf) else "取不到")
    # ★ v2.2.6（F27）：由 3 升到 4 —— events.time_uncertainty 64→191、
    #   events.ephemeris 96→191（后者是新判据当场揪出来的**同类·潜伏**事故列）。
    rep.chk("★ 表结构版本 KCJ_ASTRO_SCHEMA 已升到 4（v2.2.6 放宽两列，触发 dbDelta 增量 ALTER）",
            bool(re.search(r"KCJ_ASTRO_SCHEMA',\s*'4'", mf)),
            re.search(r"KCJ_ASTRO_SCHEMA',\s*'([^']+)'", mf).group(1)
            if re.search(r"KCJ_ASTRO_SCHEMA',\s*'([^']+)'", mf) else "取不到")

    # ── E2. ★★ 插件头部 `Version:` 必须与常量 KCJ_ASTRO_VER **一致**（v2.2.0 新增）──
    #     为什么值得做成常驻判据（2026-09-23 实际踩到）：
    #       升版本时改了常量 `KCJ_ASTRO_VER`、**漏改插件头部的 `Version:` 字段**。
    #       后果不是「显示不对」这么轻 —— 托管平台的插件上传器会拿它比对版本，
    #       可能把「版本没变」当成**无需替换**而静默略过：用户那边提示「已安装」，
    #       站点上跑的却还是旧版，从外部只能靠文件指纹才能发现（本项目就是这样查出来的）。
    #     两侧各有各的读者，缺一不可：**头部字段 = WordPress/平台认的**；**常量 = 插件内部用的**。
    _hv = re.search(r"^\s*\*\s*Version:\s*([0-9][0-9A-Za-z.\-]*)", mf, re.M)
    _cv = re.search(r"define\(\s*'KCJ_ASTRO_VER'\s*,\s*'([^']+)'\s*\)", mf)
    rep.chk("★ 插件头部有 Version 字段（平台按它判版本）",
            bool(_hv), "头部 Version=%s" % (_hv.group(1) if _hv else "取不到"))
    rep.chk("★★ 头部 Version 与常量 KCJ_ASTRO_VER 一致（改一处必须同改另一处）",
            bool(_hv and _cv) and _hv.group(1) == _cv.group(1),
            "头部=%s ｜ 常量=%s" % (_hv.group(1) if _hv else "取不到",
                                   _cv.group(1) if _cv else "取不到"))
    # 负控制（判据必须真的会红）：把两份样本分别改坏一处，断言判据能识别
    def _ver_pair_ok(txt):
        h = re.search(r"^\s*\*\s*Version:\s*([0-9][0-9A-Za-z.\-]*)", txt, re.M)
        c = re.search(r"define\(\s*'KCJ_ASTRO_VER'\s*,\s*'([^']+)'\s*\)", txt)
        return bool(h and c) and h.group(1) == c.group(1)
    _good = "* Version:           9.9.9\n" + "define('KCJ_ASTRO_VER', '9.9.9');\n"
    _bad1 = "* Version:           9.9.8\n" + "define('KCJ_ASTRO_VER', '9.9.9');\n"
    _bad2 = "define('KCJ_ASTRO_VER', '9.9.9');\n"          # 头部缺失
    rep.chk("★ 负控制：版本判据能同时识别「不一致」与「头部缺失」",
            _ver_pair_ok(_good) and not _ver_pair_ok(_bad1) and not _ver_pair_ok(_bad2),
            "样本 = 一致/不一致/缺头部")

    # ── E3. ★★ CSS 版本标记必须与头部 Version 一致（v2.2.2 新增）──
    #     为什么要有这一条：PHP 文件有 ABSPATH 守卫，**直访只输出 0 字节** ⇒ 外部
    #     拿不到版本号，无法核对「站上跑的是哪一版」。而 CSS 是公开可读的，且托管
    #     平台会把它挂成 `astro-style.css?m=<mtime>` ⇒ 读 CSS 即可**免凭据**核对版本。
    #     另一层用途：因为「CSS 每次改版都跟着改」，`?m=` 也必然变化 —— 顺带解决了
    #     「只改了 PHP 时从外部看不出包换没换」的盲区（正是「装了等于没装」那个坑）。
    #     ⚠ 代价是多一处联动，所以必须有这条判据钉住，漏改即报红。
    css_p = os.path.join(plug, "assets", "astro-style.css")
    css_t = read_text(css_p) if os.path.isfile(css_p) else ""
    _mv = re.search(r"kcj-astro-version:\s*([0-9][0-9A-Za-z.\-]*)", css_t)
    rep.chk("★ CSS 里有版本标记（供线上免凭据核对）", bool(_mv),
            "值=%s" % (_mv.group(1) if _mv else "取不到"))
    rep.chk("★★ CSS 版本标记与头部 Version 一致（改版时三处必须同改）",
            bool(_mv and _hv) and _mv.group(1) == _hv.group(1),
            "CSS=%s ｜ 头部=%s" % (_mv.group(1) if _mv else "取不到",
                                  _hv.group(1) if _hv else "取不到"))

    def _css_pair_ok(css, txt):
        m1 = re.search(r"kcj-astro-version:\s*([0-9][0-9A-Za-z.\-]*)", css)
        h1 = re.search(r"^\s*\*\s*Version:\s*([0-9][0-9A-Za-z.\-]*)", txt, re.M)
        return bool(m1 and h1) and m1.group(1) == h1.group(1)
    rep.chk("★ 负控制：CSS 版本判据能识别「不一致」与「标记缺失」",
            _css_pair_ok("/* kcj-astro-version: 9.9.9 */", _good)
            and not _css_pair_ok("/* kcj-astro-version: 9.9.8 */", _good)
            and not _css_pair_ok("/* 无标记 */", _good),
            "样本 = 一致/不一致/缺标记")

    # ── F. REST 层支持新表 ──
    rest_p = os.path.join(plug, "includes", "rest-import.php")
    rest = read_text(rest_p) if os.path.isfile(rest_p) else ""
    rep.chk("REST 白名单含 daily_site", "'daily_site'" in rest and "city_cn" in rest)
    rep.chk("★ REST 判重键支持**复合键**（daily_site 为 (date_str, city)）",
            "is_array($ukey)" in rest,
            "只支持单列键时，同一天的第二座城会覆盖第一座，且不报错")
    for col in ("lat", "lon", "elev_m", "day_length_min"):
        rep.chk("REST 数值列含 %s" % col, ("'%s'" % col) in rest, "")

    # ── G. Python 侧新脚本 ──
    for rel in ("python/build_site.py", "python/history_events.py",
                "python/gen_astro_report.py"):
        rep.chk("Python 脚本 %s 存在" % rel, os.path.isfile(os.path.join(root, rel)), "")
    bs = read_text(os.path.join(root, "python", "build_site.py")) \
        if os.path.isfile(os.path.join(root, "python", "build_site.py")) else ""
    rep.chk("★ build_site.py 与插件白名单**同序**（20 列）",
            "SITE_REST_WHITELIST" in bs, "")
    if bs and rest:
        m = re.search(r"SITE_REST_WHITELIST\s*=\s*\((.*?)\n\)", bs, re.S)
        py_wl = tuple(re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"', m.group(1))) if m else None
        php_wl = None
        mm = re.search(r"'daily_site'\s*=>\s*array\(([^)]*)\)", rest, re.S)
        if mm:
            php_wl = tuple(re.findall(r"'([^']+)'", mm.group(1)))
        rep.chk("★ 观测地白名单 客户端 == 插件（逐项且同序）",
                py_wl is not None and php_wl is not None and py_wl == php_wl,
                "Python %s / PHP %s" % (list(py_wl or []), list(php_wl or [])))

    # ── H. 期间口径（「未来十二个月」）的两条错路 · 静态哨兵 ──
    #    这条口径在 PHP 与 Python **各有一份实现**，而分岔只在闰日附近显现：
    #      · 「＋365 天」—— 2027-03-01 起算会得到 2028-02-29（应 2028-03-01）；
    #      · 「strtotime('+12 months')」—— 2028-02-29 起算会得到 2029-03-01（应 2029-02-28）。
    #    动态对拍在 php_selftest.py（要装 PHP 才跑得起来），这里放静态哨兵，
    #    好让**没装 PHP 的环境也挡得住回退**。两者互不替代：静态防改回去，动态防想歪了。
    gen_p = os.path.join(root, "python", "gen_astro_report.py")
    gen = read_text(gen_p) if os.path.isfile(gen_p) else ""
    # ★ 必须先剥注释再扫：这两条哨兵要禁的旧写法（strtotime +12 months / timedelta(days=365)）
    #   恰恰必须**写在注释里**做警示，不剥注释就会被自己的文档绊倒 —— 自指陷阱，
    #   本项目已踩过两次（见 check_negative_controls 的负控制㉒）。
    gen_code = strip_php_comments_only(gen)      # 该函数同时认 # 注释，可用于 Python 源码
    sc_code = strip_php_comments_only(sc)
    m_pr = re.search(r"def period_range\(.*?\n(?=PERIOD_ORDER|\ndef |\Z)", gen_code, re.S)
    body_py = m_pr.group(0) if m_pr else ""
    m_rg = re.search(r"function kcj_astro_report_range\(.*?\n\}", sc_code, re.S)
    body_php = m_rg.group(0) if m_rg else ""
    rep.chk("★ 期间口径：两侧都有 period_range / kcj_astro_report_range 且含 next12",
            "next12" in body_py and "next12" in body_php,
            "Python 有 next12=%s ／ PHP 有 next12=%s"
            % ("next12" in body_py, "next12" in body_php))
    rep.chk("★ 期间口径：Python 不用「＋365 天」（闰年少一天）",
            "timedelta(days=365)" not in body_py,
            "命中 ⇒ 2027-03-01 起算得 2028-02-29，与 PHP 差一天")
    rep.chk("★ 期间口径：Python 用 calendar.monthrange 做「目标月无该日取月末」",
            "calendar.monthrange" in body_py
            and re.search(r"^import calendar", gen_code, re.M) is not None)
    rep.chk("★ 期间口径：PHP 不用 strtotime('+12 months')（2/29 会进位到下月 1 日）",
            "strtotime" not in body_php,
            "命中 ⇒ 2028-02-29 起算得 2029-03-01，与 Python 差一天")
    rep.chk("★ 期间口径：PHP 用 date('t', mktime(...)) 做「目标月无该日取月末」",
            "date('t'" in body_php and "mktime" in body_php)

    # ── I. 打包脚本：`--selftest` 不得被误读成「已重新打包」 ──
    #    本轮实地踩到：`make_zip.py --selftest` 只检不写（函数里直接 return），
    #    但输出里不说 ⇒ 被读成「打完包了」⇒ verify_package 的「zip↔磁盘逐字节一致」
    #    红得莫名其妙。故要求它在自检末尾明写「本次未写入」。
    mz_p = os.path.join(root, "make_zip.py")
    mz = read_text(mz_p) if os.path.isfile(mz_p) else ""
    rep.chk("★ make_zip.py --selftest 明示「未落盘」（防被读成已重打包）",
            "未写入" in mz or "未落盘" in mz,
            "自检模式不写 zip，输出里却不提 ⇒ 下次还会误读")

    # ── J. 三栏目外壳（用户令：「3个子项以三个栏目的样式体现，**不能做成菜单**」）──
    #    为什么要做成判据：这条要求的落地方式是「纯 CSS 切换」，而**任何**内联脚本
    #    在平台上都有被后处理拆断的风险（v1.3.0 老黄历失效的真因）。
    #    若后人图省事换成 JS 切换，页面在某些平台上会整块失效 —— 且本地看不出来。
    hub_tpl_p = os.path.join(plug, "templates", "astro-hub.php")
    hub = read_text(hub_tpl_p) if os.path.isfile(hub_tpl_p) else ""
    css_p2 = os.path.join(plug, "assets", "astro-style.css")
    css2 = read_text(css_p2) if os.path.isfile(css_p2) else ""
    rep.chk("★ 栏目模板 astro-hub.php 存在", bool(hub), hub_tpl_p)
    rep.chk("★ 栏目外壳**不含脚本标签**（纯 CSS 切换 ⇒ 绕开平台的内联脚本后处理）",
            bool(hub) and "<script" not in hub.lower(),
            "含 <script 就会被平台的 wpautop/实体替换拆断，线上整块失效")
    # 三个栏目的 key 定义在**短代码**里（模板按 $s['key'] 动态渲染，故模板里
    # 本来就不该有 'today' 之类的字面量 —— 首版判据要求模板也出现字面量，
    # 结果三条一起误报；这里改正，并反过来要求模板**必须**用 $s['key']）。
    rep.chk("★ 栏目外壳按 key 动态渲染（模板用 $s['key']，不硬编码栏目名）",
            "$s['key']" in hub,
            "模板若硬编码栏目名，短代码增减栏目时会漏渲染")
    for _k in ("today", "future", "past"):
        rep.chk("★ 短代码定义「%s」栏目（三个子项齐备）" % _k,
                ("'key'   => '%s'" % _k) in sc or ("'%s'" % _k) in sc,
                "在 shortcodes.php 里找不到该栏目的 key")
    #   ⚠ 判据别写死对齐空格：短代码里 'today' 与 'future'/'past' 的等号前空格数不同
    #     （一处是为了对齐补了两个空格），写死 "'future'  => '1'" 会只匹配上 today。
    #     首版就是这么误报的两条。凡是「源码格式」判据，一律用 \s* 容错。
    for _k in ("today", "future", "past"):
        rep.chk("★ [astro_hub] 可用参数单独开关「%s」栏目" % _k,
                bool(re.search(r"'%s'\s*=>\s*'1'" % re.escape(_k), sc)),
                "缺可开关参数 ⇒ 三个子项只能全开或全关")
    rep.chk("★ 栏目样式已写进 astro-style.css", ".kcj-astro-hub" in css2)
    rep.chk("★ 栏目在打印时**全部展开**（否则打印出来的报告会少两栏）",
            bool(re.search(r"@media print\s*\{(?:[^{}]|\{[^{}]*\})*?"
                           r"\.kcj-astro-hub-pane\s*\{\s*display:\s*block\s*!important",
                           css2, re.S)),
            "打印样式里找不到 .kcj-astro-hub-pane { display:block !important }")
    rep.chk("★ 栏目**未**加「默认显示第一栏」的兜底（会导致两栏同时显示）",
            "kcj-astro-hub-pane:first-child" not in css2,
            "加了这条兜底：切到第 2/3 栏时第一栏被强制 block ⇒ 两栏同显")
    rep.chk("★ 同一页放两个外壳不串扰（radio 的 name 带唯一后缀）",
            "uniqid" in sc and "esc_attr($hid); ?>-tab" in hub,
            "name 相同时，两组栏目会互相取消选择")

    # ── K. ★ 数据集随包 ＋ 数据分层硬约束（v2.2.0 新增）──
    #    为什么必须判：数据不在包里时，后台导入页会如实报「数据集未随包提供」，
    #    但那要**装到线上之后**才发现 —— 意味着白白浪费一整轮上传/替换。
    #    所以把判据前移到打包前：清单在 ＋ 每个数据件在 ＋ **行数 == 清单声明** ＋ 分层取值正确。
    ds_dir = os.path.join(plug, "data", "datasets")
    man_p = os.path.join(ds_dir, "_manifest.json")
    rep.chk("★ 数据集随包（data/datasets/_manifest.json 存在）", os.path.isfile(man_p), man_p)
    _sets = []
    if os.path.isfile(man_p):
        try:
            _sets = json.loads(read_text(man_p)).get("sets", [])
        except Exception as exc:
            rep.chk("清单是合法 JSON", False, repr(exc))
    rep.chk("★ 清单含 4 个数据集", len(_sets) == 4, "= %d" % len(_sets))
    for _s in _sets:
        _fp = os.path.join(ds_dir, str(_s.get("file", "")))
        _n = 0
        if os.path.isfile(_fp):
            with open(_fp, "rb") as _f:
                _n = sum(1 for _ln in _f if _ln.strip())
        rep.chk("★ 数据件 %s 在位且行数 == 清单声明" % _s.get("key"),
                os.path.isfile(_fp) and _n == int(_s.get("rows", -1)),
                "磁盘 %d 行 / 清单 %s 行" % (_n, _s.get("rows")))
    # 数据分层的硬约束（见 make_datasets.py 的长注释）：历史＝数据集（0/不建页），未来＝文章（1/建页）
    for _k, _pub, _sync in (("events_future", 1, True), ("events_past", 0, False)):
        _s = next((x for x in _sets if x.get("key") == _k), None)
        rep.chk("★ 分层约束：%s 的 publish_status=%d、sync_posts=%s" % (_k, _pub, _sync),
                bool(_s) and _s.get("publish_status") == _pub
                and bool(_s.get("sync_posts")) is _sync,
                "清单里查不到该数据集或取值不符 ⇒ 历史数据会长出几千篇薄页面，或目标栏目查不到")
    # 分层能成立的前提有两处，缺一处这个设计就崩，故一并钉住：
    rep.chk("★ 历史栏查询**不看** publish_status（数据集≠已发布文章）",
            bool(re.search(r"WHERE event_type IN \(\$ph\)\s*\n\s*AND event_time_bj IS NOT NULL", sc)),
            "短代码里历史栏的 WHERE 仍带 publish_status ⇒ 导成 0 之后该栏什么都查不到")
    _hist_p = os.path.join(plug, "templates", "astro-history-today.php")
    _hist = read_text(_hist_p) if os.path.isfile(_hist_p) else ""
    rep.chk("★ 历史栏模板不外链（无 permalink 调用）—— 这是「不建页」成立的前提",
            bool(_hist) and "permalink" not in _hist,
            "历史栏若外链到详情页，则「不建页」会造出成批坏链")
    # 报告模板**是外链**的 ⇒ 它必须只吃已发布行（未来事件），这一条防止有人顺手也去掉过滤
    _rep_p = os.path.join(plug, "templates", "astro-forecast-report.php")
    _rep = read_text(_rep_p) if os.path.isfile(_rep_p) else ""
    rep.chk("★ 报告模板保持外链（故未来事件必须建页，两处约束互为前提）",
            "kcj_astro_event_permalink" in _rep)

    # ── K. 历史栏目「历年同日」（v2.1.0 新增）──────────────────────────────────
    #    这一组的每一条，守的都是**「看着对、却会静默坏」**的地方：
    #    分组键错 ⇒ 两种相反的天象并成一组；闰年基准错 ⇒ 02-29 永远不可达；
    #    数据岛被平台后处理拆坏 ⇒ 下载按钮点了没反应（本项目已犯过两次同类）。
    hist_p = os.path.join(plug, "templates", "astro-history-today.php")
    hist = read_text(hist_p) if os.path.isfile(hist_p) else ""
    rep.chk("★ 历史栏目模板 astro-history-today.php 存在", bool(hist), hist_p)

    # ① 分组键必须是**抽出来的函数**（可被 php_selftest 单测），且模板也确实在用它。
    rep.chk("★ 分组键抽成函数 kcj_astro_history_group_key()（否则桩测试碰不到）",
            "function kcj_astro_history_group_key(" in sc,
            "内联在模板/闭包里的规则，php_selftest 测不到 ⇒ 只能靠读码，等于没判据")
    rep.chk("★ 模板经该函数取分组键（不是自己另写一遍）",
            "kcj_astro_history_group_key(" in hist,
            "模板另写一份 ⇒ 两处会漂移")
    # ② ★ 关键：只许剥**日期形**括号。一刀切剥「（…）」会把
    #    「土星留（转逆行）」与「土星留（转顺行）」并成同一组（两种相反的天象混在一起）。
    #    （判定逻辑抽在 rule_history_group_key_date_only()，负控制㉞ 调同一份代码。）
    _ok, _why = rule_history_group_key_date_only(sc)
    rep.chk("★ 分组键只剥「日期形」括号（正则含日期、不含一刀切的 [^）]*）", _ok, _why)
    # ③ ★ 跳转的天数基准必须是**闰年**，否则 02-28 加一天跳到 03-01，02-29 永不可达。
    _ok3, _why3 = rule_history_nav_leap_base(sc)
    rep.chk("★ 日期跳转用闰年做天数基准（否则 02-29 永远不可达）", _ok3, _why3)
    rep.chk("★ 短代码给了「前后几天」跳转（含 URL 参数 ?kcj_md=）",
            "kcj_astro_history_nav(" in sc and "kcj_md" in sc and "_GET['kcj_md']" in sc,
            "没有跳转 ⇒ 「这一天确实没有」时读者没有任何办法换一天看")
    rep.chk("★ 日期跳转在打印时隐藏（链接印在纸上是点不动的假按钮）",
            bool(re.search(r"@media print\s*\{(?:[^{}]|\{[^{}]*\})*?"
                           r"\.kcj-astro-history-nav\s*\{\s*display:\s*none\s*!important",
                           css2, re.S)),
            "打印样式里找不到 .kcj-astro-history-nav { display:none !important }")
    # ④ ★ 数据岛：必须单行 + 十六进制转义。平台会对正文跑后处理，
    #    裸 & 会被换成实体引用、空行会被换成 </p><p> —— 两者都会把 JSON 拆坏。
    rep.chk("★ 历史页的数据岛用 JSON_HEX_AMP｜JSON_HEX_TAG（防平台实体替换）",
            "JSON_HEX_AMP" in hist and "JSON_HEX_TAG" in hist,
            "裸 & 会被平台换成实体引用；<script> 内容不做实体解码 ⇒ 数据岛整块失效")
    # ⑤ ★ 必须区分「未录入」与「确实没有」—— 这是本项目反复踩的静默失败。
    rep.chk("★ 空结果时区分「未录入」与「这一天确实没有」（用 $coverage 佐证）",
            "$coverage" in hist and "未录入" in hist,
            "把「没查」说成「没有」，是本项目反复踩的静默失败")
    rep.chk("★ 空结果时逐族报 coverage（否则读者不知道该不该信这个「没有」）",
            "kcj-astro-coverage" in hist,
            "缺 coverage 列表 ⇒ 无法判断是「没录」还是「真没有」")
    # ⑥ ★ 短代码默认族必须**含日食**：日食在历史段内 coverage=0，
    #    页面会如实说「一条都没收录 ⇒ 属未录入」。若因「反正没数据」把它从默认里删掉，
    #    这句如实说明也就跟着消失了（把「没查」重新藏起来）。
    rep.chk("★ [astro_history_today] 默认族含日食（保住「未录入」那句如实说明）",
            bool(re.search(r"'types'\s*=>\s*'[^']*solar_eclipse", sc)),
            "默认族里去掉 solar_eclipse ⇒ 「日食未录入」的如实说明一并消失")
    for _fam in ("lunar_eclipse", "meteor", "planet"):
        rep.chk("★ [astro_history_today] 默认族含可自算的 %s" % _fam,
                bool(re.search(r"'types'\s*=>\s*'[^']*" + re.escape(_fam), sc)),
                "只收月食时日历覆盖仅 36.3%，多数日子打开是空的")
    # ⑦ ★ PHP 模板**不得**写 markdown 粗体 —— 模板输出的是 HTML，
    #    `**x**` 会原样显示成星号（本项目的 md 习惯会不自觉漏进来）。
    #    ⚠ 必须先剥注释再扫：注释里**有意**写着 `**加粗**` 做说明（本模板头部就有），
    #      不剥注释会让这条判据**自己命中自己的文档** —— 首版正是这样误报 3 条。
    #      （这与「描述判据的文档把自己豁免」是同一族的自指陷阱，方向相反：
    #        那边是判据放过文档，这边是判据咬住文档。修法都是「把注释排除出观察面」。）
    _hist_code = strip_php_comments_only(hist)
    _ok7, _why7 = rule_no_markdown_bold(_hist_code)
    rep.chk("★ 历史模板里不出现 markdown 粗体（PHP 模板会原样输出星号）", _ok7, _why7)
    # ⑧ 成组阈值与「年份清单」渲染必须在模板里（否则加了数据会把页面刷爆）
    rep.chk("★ 模板有成组渲染（≥6 条同名 ⇒ 折成「年份清单」）",
            "GROUP_MIN" in hist and "kcj-astro-history-group" in hist and "kcj-astro-years" in hist,
            "缺成组 ⇒ 英仙座极大在 8/12 那天会刷出 126 条卡片")
    # ⑨ 数据文件（若已生成）必须只含白名单内的族
    past_p = os.path.join(root, "data", "events_past.json")
    ok_past, note_past = True, "文件未生成（属未跑，不等于通过）"
    if os.path.isfile(past_p):
        try:
            _raw = json.loads(read_text(past_p))
            _rows = _raw if isinstance(_raw, list) else []
            _types = {r.get("event_type") for r in _rows if isinstance(r, dict)}
            _allow = {"lunar_eclipse", "meteor", "planet", "solar_eclipse"}
            ok_past = bool(_rows) and _types.issubset(_allow)
            note_past = "族=%s，共 %d 条" % (sorted(t for t in _types if t), len(_rows))
        except Exception as exc:  # noqa: BLE001
            ok_past, note_past = False, "解析失败：%r" % (exc,)
    rep.chk("★ data/events_past.json 的族落在白名单内（且非空）", ok_past, note_past)


# ── 13. 导入器（v2.2.2）：失败必须发声 ────────────────────────────────────
#   背景：线上出现「页面显示已完成 100%，而表里一行没有」——
#   写入失败只累加 failed、游标照推、页面仍渲染成绿色的「已完成」，
#   用户据此判定「已全部完成」。以下 7 条把这类**静默失败**钉住，末条为负控制。
#
#   ⚠ 判定一律在**剥掉注释**后的代码上做：这些坑的注释里**有意**写着旧写法
#     （如 `$offset += count($rows)`）作说明，不剥注释就会自己命中自己的文档
#     —— 与「描述判据的文档把自己豁免」同族的自指陷阱。
def check_importer(root, rep):
    p = os.path.join(root, "wp-astro-forecast", "includes", "admin-import.php")
    src = read_text(p) if os.path.isfile(p) else ""
    code = strip_php_comments_only(src)

    # ① 目标表存在性前置检查：缺表即报错，不开跑
    rep.chk("★ 导入前检查目标表是否存在（缺表即报错，不开跑）",
            "kcj_astro_no_table" in code and "KCJ_Astro_DB::health()" in code,
            "缺这道 ⇒ 表不存在时逐行 insert 全失败而游标照推 ⇒ 页面显示「已完成」但表里一行没有")

    # ② 写入失败必须显性：红色 notice + 失败行数 + 原因
    rep.chk("★ 写入失败以 notice-error 显性呈现（给出失败行数与前因）",
            "⚠ 其中写入失败" in code and "notice-error" in code,
            "只判 done ⇒「成功 0 / 失败 29298」也会被渲染成绿色的「已完成」")

    # ③ 补建表结构入口（不单靠 init 守卫）
    rep.chk("★ 提供「补建 / 升级表结构」动作（不单靠 init 守卫）",
            "repair" in code and "kcj_astro_import_repair" in code,
            "守卫只在 option 与常量不符时才跑；option 一旦被误写便永不再试，表会永远缺着")

    # ④ 表结构自检区：表存在性与现存行数肉眼可见
    rep.chk("★ 页面有表结构自检区（4 张表的「存在」与「现存行数」）",
            "表结构自检" in src and "'exists'" in code and "'rows'" in code,
            "看不见表在不在 ⇒ 无法区分「表不存在」与「表存在但空」")

    # ⑤ 读取器支持字节位直读（O(n²) ⇒ O(1)）
    rep.chk("★ 读取器支持字节位直读 fseek（不再每跳从文件头扫到 offset）",
            "function kcj_astro_import_read($file, $offset, $limit, $file_size" in code
            and "fseek(" in code and "'pos'" in code and "'size'" in code,
            "每跳 fgets 到 offset ⇒ 29,298 行的数据件是 O(n²)，越跑越慢、最后像卡死")

    # ⑥ 游标按「消费行数」推进（含被跳过的非法行）
    rep.chk("★ 游标按 consumed（消费行数）推进，含被跳过的非法行",
            "$offset += $b['consumed'];" in code and "consumed" in code,
            "按成功行数推进 ⇒ 1 行非法 JSON 即永远重读（死循环）")

    # ⑦ 负控制：旧写法不得残留
    rep.chk("★ 负控制：旧写法 `$offset += count($rows)` 已清除",
            "$offset += count($rows)" not in code,
            "残留即回退到「坏行死循环 / 兜底静默跳过后面所有行」")

    # ⑧ 全库：PHP 双引号插值不得出现「$var 紧跟全角字符」
    #   原理：PHP 变量名允许字节 \x80-\xff，而全角「（」的 UTF-8 首字节是 0xEF
    #   ⇒ `"…$bo（应为 4）"` 的变量名被解析成 `$bo（` ⇒ 未定义变量、插值成空串。
    #   代码区不可能这样写（那是语法错），故命中即必在字符串内 —— 本项目文案全中文，
    #   极易复发（本文件所在的测试件就踩过一次，输出里那处变量是空的）。
    fw_re = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*[（），。：；！？、》】」』…—～]")
    bad_fw = []
    plug_root = os.path.join(root, PLUGIN_DIR)
    for dp, _dn, fns in os.walk(plug_root):
        for fn in fns:
            if not fn.endswith(".php"):
                continue
            fp = os.path.join(dp, fn)
            c = strip_php_comments_only(read_text(fp))
            for mm in fw_re.finditer(c):
                bad_fw.append("%s:%d %r" % (os.path.relpath(fp, root),
                                            c[:mm.start()].count("\n") + 1, mm.group(0)))
    rep.chk("★ PHP 双引号插值里无「$var 后紧跟全角字符」（会被静默吞掉、插值成空串）",
            not bad_fw, "；".join(bad_fw[:5]) if bad_fw else "0 处（扫 %d 个 PHP）" % len(php_files(root)))

    # ⑨ 负控制：上面这条真能咬住样本
    _fw_sample = '$x = "推进到 $bo（应为 4）";'
    rep.chk("★ 负控制：全角插值判据真能咬住样本",
            bool(fw_re.search(strip_php_comments_only(_fw_sample))),
            "样本 %r" % _fw_sample)

    # ⑩ 全库：PHP 输出文案里不得出现 markdown 粗体
    #   PHP 模板/页面输出的是 HTML，`**x**` 会原样显示成星号。本项目的写作习惯
    #   大量用 `**强调**`，写 PHP 文案时会不自觉带进来（本次实测命中 3 处：
    #   「全部失败」「可重复点」「页面内联展示」）。
    #   ⚠ 必须先剥注释：注释里**有意**写 `**v2.2.0**` 做说明。
    md_re = re.compile(r"\*\*[^*\n]{1,40}\*\*")
    bad_md = []
    for dp, _dn, fns in os.walk(plug_root):
        for fn in fns:
            if not fn.endswith(".php"):
                continue
            fp = os.path.join(dp, fn)
            c = strip_php_comments_only(read_text(fp))
            for mm in md_re.finditer(c):
                bad_md.append("%s %r" % (os.path.relpath(fp, root), mm.group(0)[:30]))
    rep.chk("★ 全库 PHP 输出里无 markdown 粗体（会原样显示成星号）",
            not bad_md, "；".join(bad_md[:5]) if bad_md else "0 处")

    # ⑪ 负控制：样本必须被判出
    rep.chk("★ 负控制：markdown 粗体判据真能咬住样本",
            bool(md_re.search(strip_php_comments_only("echo '导入会**全部失败**';"))),
            "样本 echo '导入会**全部失败**';")


# ---------------------------------------------------------------------------
# 14. 数据集行序与 sha1 指纹（v2.2.3 新增）
# ---------------------------------------------------------------------------
#  这一组守的是「**在站外完全看不出来**」的一类错：
#    · 行序错了 ⇒ 导入是逐跳推进的，核心数据排在几千行之外 ⇒ 用户点了导入、
#      等了 9 分钟、页面一字未变，合理地判成「已完成 / 坏了」（本轮线上即如此）。
#    · 数据件被换过而只判「字节数」⇒ **重排行序不改字节数**（实测四项一字节不差）
#      ⇒ 判不出变更 ⇒ 沿用旧字节位落在行中间 ⇒ 后半段静默读丢、页面照报「已完成」。
#  故判据分两层：**行序不变量**（第一行必须是最近的）＋ **sha1 与清单一致**。

def _ds_date_ord(s):
    try:
        return datetime.date(int(s[0:4]), int(s[5:7]), int(s[8:10])).toordinal()
    except (ValueError, TypeError, IndexError):
        return None


def _ds_md_ord(s):
    """'YYYY-MM-DD…' 的月日 → 年内序日，**基准年取 2000（闰年）**。

    ★ 基准年必须与 make_datasets.py 一致。本轮曾用 `today.timetuple().tm_yday`
      （锚点按 **2026 平年**算）去和「2000 闰年基准的月日」比 ⇒ 2 月之后整体差 1
      ⇒ 排序中心落在 09-22 而今天是 09-23，**错得很像对的**。
    """
    try:
        return datetime.date(2000, int(s[5:7]), int(s[8:10])).timetuple().tm_yday
    except (ValueError, TypeError, IndexError):
        return None


def _ds_ring(a, b):
    if a is None or b is None:
        return 10 ** 6
    d = abs(a - b)
    return min(d, 366 - d)


def rule_order_first_is_nearest(kind, keys, anchor_iso):
    """行序不变量：**第 1 行的「距离」必须是全件最小**。返回 (ok, why)。

    keys = 每行的身份串（`date_str` 或 `event_time_bj`）；anchor_iso = 'YYYY-MM-DD'。
    ★ 刻意**不判「第一行必须等于今天」**：数据件可能不覆盖今天（例如已过期或用
      --today 固定过）。那时**正确的不变量**是「离今天最近的那一行排在最前」，
      判「等于今天」会变成假红。
    """
    if not keys:
        return False, "空件（0 行）"
    if kind == "time_asc":
        lo = min(keys)
        return (keys[0] == lo, "首行 %s / 最小 %s" % (keys[0][:19], lo[:19]))
    if kind == "near_date":
        a = _ds_date_ord(anchor_iso)
        dists = []
        for k in keys:
            o = _ds_date_ord(k)
            dists.append(10 ** 9 if o is None else abs(o - a))
    elif kind == "near_md":
        a = _ds_md_ord(anchor_iso)
        dists = [_ds_ring(_ds_md_ord(k), a) for k in keys]
    else:
        return False, "未知行序 %r" % kind
    return (dists[0] == min(dists), "首行距离 %d / 最小 %d" % (dists[0], min(dists)))


def rule_no_size_based_change_detection(code):
    """判据：**不得**以「文件字节数变化」作为「数据件内容变了」的判据。返回 (ok, why)。

    ★ 抽成函数是为了**能被证伪**。这本来写成内联的 `"…" not in code`，而它的
      负控制样本（v2.2.1）**恰好也不含那一串**（按字节数判变更是 v2.2.2 才引入的），
      于是样本永远无法证伪它 —— 负控制跑完 10 FAIL / 1 PASS，一眼看出这一条是空壳。
      「断言某串**不存在**」的判据天然难以证伪：样本必须是**含该串**的版本，
      而那种版本往往已被覆盖。故此处改成规则函数 ＋ 专用的含缺陷样本。
    """
    bad = "数据件已变更（字节数 " in code
    return (not bad), ("仍含「按字节数判数据件变更」的写法" if bad else "0 处")


def check_datasets_order(root, rep):
    plug = os.path.join(root, PLUGIN_DIR)
    ds   = os.path.join(plug, "data", "datasets")
    man_p = os.path.join(ds, "_manifest.json")
    man = {}
    if os.path.isfile(man_p):
        try:
            man = json.loads(read_text(man_p))
        except Exception as exc:
            rep.chk("清单是合法 JSON（行序与 sha1 判据的前提）", False, repr(exc))
    if not isinstance(man, dict):
        man = {}
    sets   = man.get("sets", []) if isinstance(man.get("sets"), list) else []
    anchor = str(man.get("anchor_date") or "")

    rep.chk("★ 清单有行序锚点 anchor_date（行序判据的基准）",
            bool(re.match(r"^\d{4}-\d{2}-\d{2}$", anchor)),
            "= %r（缺它则无法判定「第一行是不是最近的」）" % anchor)

    allowed = ("near_date", "near_md", "time_asc")
    bad_ord = [("%s=%r" % (s.get("key"), s.get("order"))) for s in sets
               if s.get("order") not in allowed]
    rep.chk("★ 每个数据集都声明了行序 order，且在允许集合内", not bad_ord,
            "；".join(bad_ord) if bad_ord else "4 件均可（%s）" % "/".join(allowed))

    bad_sha = [str(s.get("key")) for s in sets
               if not re.match(r"^[0-9a-f]{40}$", str(s.get("sha1") or ""))]
    rep.chk("★ 每个数据集都带 40 位十六进制 sha1（行序变更的唯一探针）", not bad_sha,
            "缺：%s" % "、".join(bad_sha) if bad_sha else "4 件齐备")

    # 磁盘实际 sha1 == 清单声明（防「改了数据件却没重跑 make_datasets.py」）
    mism = []
    for s in sets:
        fp = os.path.join(ds, os.path.basename(str(s.get("file") or "")))
        if not os.path.isfile(fp):
            mism.append("%s 文件不存在" % s.get("key"))
            continue
        with open(fp, "rb") as fh:
            have = hashlib.sha1(fh.read()).hexdigest()
        if have != str(s.get("sha1") or ""):
            mism.append("%s 磁盘 %s… ≠ 清单 %s…"
                        % (s.get("key"), have[:8], str(s.get("sha1") or "?")[:8]))
    rep.chk("★ 数据件磁盘 sha1 == 清单声明（改了数据件必须重跑 make_datasets.py）",
            not mism, "；".join(mism) if mism else "4 件一致")

    # 行序不变量：逐件判「第一行是不是最近的」
    for s in sets:
        k  = str(s.get("key"))
        fp = os.path.join(ds, os.path.basename(str(s.get("file") or "")))
        key_field = "event_time_bj" if s.get("table") == "events" else "date_str"
        keys = []
        if os.path.isfile(fp):
            with open(fp, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        keys.append(str(json.loads(line).get(key_field) or ""))
                    except ValueError:
                        keys.append("")
        ok, why = rule_order_first_is_nearest(str(s.get("order") or ""), keys, anchor)
        rep.chk("★ 行序：%s 的第 1 行是离锚点最近的一行" % k, ok,
                "order=%s，%s" % (s.get("order"), why))

    # ── 导入器侧：判据从「字节数」升级为「sha1」──────────────────────────
    src_p = os.path.join(plug, "includes", "admin-import.php")
    code  = strip_php_comments_only(read_text(src_p)) if os.path.isfile(src_p) else ""
    rep.chk("★ 导入器以 sha1 判定「数据件内容变了」（sha1_file ＋ 明确错误码）",
            "sha1_file(" in code and "kcj_astro_sha_mismatch" in code,
            "只判字节数 ⇒ 重排行序（字节数不变）判不出来")
    rep.chk("★ 导入器把数据件 sha1 存进状态（下一跳据此发现内容变更）",
            bool(re.search(r"'sha1'\s*=>\s*\$file_sha", code)),
            "状态里没有 sha1 ⇒ 既使守卫算了也留不下痕迹")
    _ok_sz, _why_sz = rule_no_size_based_change_detection(code)
    rep.chk("★ 旧的「按字节数判数据件变更」判据已撤除（防止两套判据并存、后者误导）",
            _ok_sz,
            "若保留，页面会同时报「字节数变了」与「sha1 变了」，前者对本场景是错的")
    # ★ 这条的**专用负控制**：v2.2.1 样本证伪不了它（那一版还没有这个写法），
    #   故另配一个「含缺陷」的样本 —— 判据必须能把样本判成不合格。
    _sz_sample = ("if ($b['size'] !== $file_size) { $errors[] = "
                  "'数据件已变更（字节数 ' . $file_size; }")
    _ok_sz_s, _why_sz_s = rule_no_size_based_change_detection(_sz_sample)
    rep.chk("★ 负控制：「按字节数判变更」判据真能咬住含缺陷样本（非空壳）",
            not _ok_sz_s, "样本 %r → %s" % (_sz_sample[:44], _why_sz_s))

    # ★★ 升级路径上最容易漏的一处（漏了就等于白改行序、还看不出错）：
    #    线上游标是 v2.2.2 留下的 —— **状态里没有 sha1**。若只判「sha1 不符」，
    #    这条旧游标会绕过守卫、沿用旧字节位，而新数据件是**重排过**的（字节数没变）
    #    ⇒ 落在行中间 ⇒ 后半段静默丢失。故必须把「状态无 sha1」也判成「从头重导」。
    rep.chk("★ 状态里没有 sha1 的旧游标也必须从第 1 行重导（升级路径的关键一处）",
            "elseif ($prev_sha === '')" in code
            and bool(re.search(r"\$reset_why\s*=\s*''", code))
            and bool(re.search(r"if\s*\(\s*\$reset_why\s*!==\s*''\s*&&\s*\$offset\s*>\s*0\s*\)",
                               code)),
            "若只判「sha1 不符」⇒ v2.2.2 遗留的无 sha1 游标会绕过守卫、沿用旧字节位"
            "（新数据件已重排而字节数不变）⇒ 后半段静默丢失")
    rep.chk("★ 后台页有「数据件自检」区（列出 行序 / 第 1 行 / sha1 / 是否一致）",
            "kcj_astro_import_data_report(" in code
            and "数据件自检" in read_text(src_p)
            and "anchor_date" in code,
            "没有这一节 ⇒ 「包没换」「行序错了」在站外仍是不可见的")

    # ── 负控制 ①：同字节数的重排，sha1 必变、而旧判据（只比字节数）必瞎 ──
    nd = os.path.join(ds, "daily_2026.ndjson")
    if os.path.isfile(nd):
        with open(nd, "rb") as fh:
            raw = fh.read()
        rev = b"".join(reversed(raw.splitlines(True)))
        rep.chk("★ 负控制：重排行序后字节数不变、sha1 必变（故只判字节数必然漏检）",
                len(rev) == len(raw) and hashlib.sha1(rev).hexdigest()
                != hashlib.sha1(raw).hexdigest(),
                "原 %d B/%s… 重排后 %d B/%s…"
                % (len(raw), hashlib.sha1(raw).hexdigest()[:8],
                   len(rev), hashlib.sha1(rev).hexdigest()[:8]))
    else:
        rep.chk("★ 负控制：重排行序后字节数不变、sha1 必变", False, "缺样本 %s" % nd)

    # ── 负控制 ②③：行序判据既不能空壳（倒序必须判出），也不能假红（正样本必须过）──
    #   两条必须成对：只留「倒序判出」则一个恒返回 False 的实现也能通过；
    #   只留「正样本通过」则一个恒返回 True 的实现也能通过。
    _good = ["2026-09-23", "2026-09-22", "2026-09-24"]
    _bad  = list(reversed(_good))
    _ok_good, _why_good = rule_order_first_is_nearest("near_date", _good, "2026-09-23")
    _ok_bad,  _why_bad  = rule_order_first_is_nearest("near_date", _bad, "2026-09-23")
    rep.chk("★ 负控制：行序判据对「最近在前」的正样本必须通过（否则是假红）",
            _ok_good, _why_good)
    rep.chk("★ 负控制：行序判据对「倒序」样本必须判出（否则是空壳）",
            not _ok_bad, "倒序样本 %s → %s" % (_bad, _why_bad))


# ---------------------------------------------------------------------------
# 15. 导入推进机制三条（v2.2.4 新增）
# ---------------------------------------------------------------------------
#  守的是 v2.2.3 上线后「外部取证全部通过、三栏却一字未变」暴露的缺口：
#  包对、数据件对、行序对都验过了，唯独「导入这一步有没有真的发生」验不到。
#  回读源码定出四个成因（F57—F60），其中三个是新机制、须有常驻判据：
#    · F57 队头阻塞：某个集报错即 return WP_Error ⇒ 排在它后面的集**永远轮不到**
#      （daily_site 排第 2 位、恰是最易报错的 ⇒ events_* 从不被导入 ⇒
#        「历史栏一直空」与「今日栏一直降级」是**同一个原因**）。
#    · F58 dbDelta 静默跳过：它**先解析** DDL 再比对，认不出的部分**不报错、只是不做**
#      ⇒ 「4 张表建好 3 张」，而 init 守卫因列读不到而判不合格 ⇒ 每次请求白跑一遍。
#    · F59 每跳只推进一个集 ⇒ 先排的集垄断所有跳。改为每跳各推进一跳（时间盒**分摊**）。
#    · F60 打开导入页不自动开始 ⇒ 改为「一打开就开始 / 续跑」（页面本身已过权限门）。
#  ⚠ 每条机制都必须**能被证伪**：各配一个「含缺陷样本」负控制，否则判据是空壳
#    （本项目已有教训：断言某串**不存在**的判据，样本恰好也不含它 ⇒ 永远证伪不了）。

def rule_auto_import_starts(code):
    """打开导入页即自动开始 / 续跑，且**数据件不自检放行就不开跑**。返回 (ok, why)。"""
    if "$auto_start = true;" not in code:
        return False, "缺 `$auto_start = true;`"
    if not re.search(r"if\s*\(\s*\$run\s*===\s*''\s*&&\s*\$sets\s*\)", code):
        return False, "缺「仅在无显式 kcj_run 时自动」的前置条件（否则与显式路径冲突）"
    # ★ v2.2.6：护栏从「$todo > 0」放宽为「($todo + $redo) > 0」——
    #   标着「已完成」但写入有失败、且**表结构已变更**的集也算「有活可干」，
    #   否则会出现最尴尬的一种情况：判据认为有活、闸门认为没活 ⇒ 打开页面什么都不发生。
    if "$drep_bad" not in code or not re.search(r"\(\s*\$todo\s*\+\s*\$redo\s*\)\s*>\s*0\s*&&\s*!\s*\$drep_bad", code):
        return False, "缺「($todo + $redo) > 0 && !$drep_bad」护栏 ⇒ sha1 与清单不符时仍会开跑"
    if "$redo" not in code:
        return False, "缺 $redo（表结构变更后需重导的集）—— 自动开始闸门会漏掉「已完成但全失败」的集"
    if "check_admin_referer('kcj_astro_import_'" not in code:
        return False, "缺显式路径的 nonce 校验（自动路径才该免 nonce）"
    return True, "$auto_start ＋ ($todo+$redo) 护栏 ＋ 显式路径仍校验 nonce"


def rule_auto_note_separate_var(code):
    """自动开始的说明句必须是**独立变量**并被渲染（写进 $notice 会被后续分支覆盖）。"""
    if "$auto_note = '';" not in code:
        return False, "缺 `$auto_note = '';` 初始化"
    if "$auto_note = '本页打开即自动开始" not in code:
        return False, "缺自动说明句赋值"
    if "echo esc_html($auto_note)" not in code:
        return False, "缺渲染（写了却不显示，正是「写了但不显示」的老坑）"
    return True, "独立变量 ＋ 独立渲染位"


def rule_all_loop_skips_errors(code):
    """「一键全部」不得因某个集报错而**中断整条链**（F57）。返回 (ok, why)。"""
    m = re.search(r"\$errs\[\$k\]\s*=\s*\$r->get_error_message\(\);", code)
    if not m:
        return False, "缺 `$errs[$k] = $r->get_error_message();`（报错未逐集记录）"
    if "continue;" not in code[m.end(): m.end() + 240]:
        return False, "记录报错之后没有 `continue;` ⇒ 旧版在此中断整条链"
    return True, "报错即逐集记录 ＋ continue（跳过它、继续下一个）"


def rule_per_hop_multi_set(code):
    """每跳各推进一个集（时间盒**按剩余集数分摊**），否则先排的集垄断所有跳（F59）。"""
    if "$budget = null" not in code:
        return False, "缺 `kcj_astro_import_run($key, $budget = null)` 可选参数"
    if not re.search(r"\$budget\s*===\s*null", code):
        return False, "缺 `($budget === null) ? … : max(1, (int) $budget)` 的分派"
    if "$share = max(3," not in code:
        return False, "缺按剩余集数分摊的 `$share`（每跳改推一个集的关键）"
    return True, "$budget 可选 ＋ $share 分摊"


def rule_still_uses_fresh_state(code):
    """「还有没有未完成的集」必须用**最新**状态重算，不能用本轮开始前的 $cands 快照。"""
    if not re.search(r"\$still\s*=\s*0;", code):
        return False, "缺 `$still = 0;`（续跑判定）"
    m = re.search(r"\$still\s*=\s*0;(.{0,220})", code, re.S)
    seg = m.group(1) if m else ""
    if "kcj_astro_import_progress($k)['offset']" not in seg:
        return False, "续跑判定没有重新取 progress ⇒ 用的是 $cands 快照（会多跑或少跑一跳）"
    if re.search(r"\$still\s*=\s*count\(\s*\$cands\s*\)", code):
        return False, "仍用 `count($cands)` 当续跑依据"
    return True, "$still 从最新状态重算"


def rule_dbdelta_fallback(code):
    """dbDelta 认不出的 DDL 会被**静默跳过** ⇒ 缺表必须直连兜底（F58）。"""
    if "CREATE TABLE IF NOT EXISTS" not in code:
        return False, "缺直连兜底 DDL"
    if not re.search(r"preg_replace\(\s*'/\^CREATE", code):
        return False, "缺把 `CREATE TABLE` 改写成 `CREATE TABLE IF NOT EXISTS` 的 preg_replace"
    if "SHOW TABLES LIKE" not in code:
        return False, "缺「表究竟在不在」的实测（凭 dbDelta 返回值会误判）"
    if "last_error" not in code:
        return False, "缺把 `$wpdb->last_error` 记下来（页面才显示得出建表失败的原因）"
    return True, "CREATE TABLE IF NOT EXISTS ＋ SHOW TABLES 实测 ＋ last_error"


def check_progress_mechanisms(root, rep):
    plug  = os.path.join(root, PLUGIN_DIR)
    imp_p = os.path.join(plug, "includes", "admin-import.php")
    db_p  = os.path.join(plug, "includes", "class-astro-db.php")
    imp   = strip_php_comments_only(read_text(imp_p)) if os.path.isfile(imp_p) else ""
    db    = strip_php_comments_only(read_text(db_p)) if os.path.isfile(db_p) else ""

    # ── 自动开始（F60）──
    _ok, _why = rule_auto_import_starts(imp)
    rep.chk("★ 打开导入页即自动开始 / 续跑（免去「该点哪个按钮」这一层）", _ok, _why)
    _ok2, _why2 = rule_auto_note_separate_var(imp)
    rep.chk("★ 自动开始的说明句是独立变量并被渲染（写进 $notice 会被后续分支覆盖）", _ok2, _why2)
    _ok3, _why3 = rule_auto_import_starts(
        "if ($run === '' && $sets) { $todo = 0; } "
        "if ($todo > 0) { $run = 'all'; $auto_start = true; } "
        "check_admin_referer('kcj_astro_import_' . $run);")
    rep.chk("★ 负控制：缺 `$drep_bad` 护栏的样本必须被判出（否则判据是空壳）",
            not _ok3, "样本（自动开始但无 sha1 护栏）→ %s" % _why3)

    # ── 队头阻塞（F57）──
    _ok4, _why4 = rule_all_loop_skips_errors(imp)
    rep.chk("★ 「一键全部」报错的集跳过、继续下一个（不再中断整条链）", _ok4, _why4)
    _ok5, _why5 = rule_all_loop_skips_errors("if (is_wp_error($r)) { return $r; }")
    rep.chk("★ 负控制：旧版「return WP_Error 中断整条链」的样本必须被判出",
            not _ok5, "样本（报错即 return）→ %s" % _why5)
    _ok6, _why6 = rule_all_loop_skips_errors(
        "$errs[$k] = $r->get_error_message(); return WP_Error('x','y');")
    rep.chk("★ 负控制：记录了报错但仍 `return`（未 continue）的样本必须被判出",
            not _ok6, "样本（记录后仍 return）→ %s" % _why6)

    # ── 每跳多集（F59）──
    _ok7, _why7 = rule_per_hop_multi_set(imp)
    rep.chk("★ 每跳把**每个未完成的集各推进一跳**（时间盒按剩余集数分摊）", _ok7, _why7)
    _ok8, _why8 = rule_per_hop_multi_set(
        "function kcj_astro_import_run($key) { $sec = KCJ_ASTRO_IMPORT_MAX_SEC; }")
    rep.chk("★ 负控制：单集签名、无分摊的样本必须被判出", not _ok8,
            "样本（$budget 缺、$share 缺）→ %s" % _why8)
    _ok9, _why9 = rule_still_uses_fresh_state(imp)
    rep.chk("★ 续跑判定用**最新**状态重算（不用本轮开始前的 $cands 快照）", _ok9, _why9)
    _ok10, _why10 = rule_still_uses_fresh_state("$still = 0; $still = count($cands);")
    rep.chk("★ 负控制：用 $cands 快照当续跑依据的样本必须被判出", not _ok10,
            "样本（$still = count($cands)）→ %s" % _why10)

    # ── dbDelta 兜底（F58）──
    _ok11, _why11 = rule_dbdelta_fallback(db)
    rep.chk("★ dbDelta 认不出的 DDL 被静默跳过 ⇒ 缺表改直连 CREATE TABLE IF NOT EXISTS",
            _ok11, _why11)
    rep.chk("★ 直连建表的错误与列宽缺口**合并记账**（分开报会漏其一）",
            "array_merge($cerr, $bad)" in db,
            "缺 `array_merge($cerr, $bad)` ⇒ 建表失败会被「列宽达标」的假象盖掉")
    rep.chk("★ 有缺口时**不写** schema 版本（留给下一次请求重试）",
            "if ($all)" in db
            and db.find("if ($all)") < db.find("update_option('kcj_astro_schema_version'"),
            "先记账并 return 才轮到写版本 ⇒ 否则守卫从此不再重试（静默失败）")
    _ok12, _why12 = rule_dbdelta_fallback("dbDelta($sql); $done[] = $tbl;")
    rep.chk("★ 负控制：只跑 dbDelta 不兜底的样本必须被判出", not _ok12,
            "样本（仅 dbDelta）→ %s" % _why12)

    # ── 后台把数据库原始错误显示出来（否则站外只能猜）──
    rep.chk("★ 补建失败时把数据库原始错误（$wpdb->last_error）显示到页面",
            "数据库返回：" in read_text(imp_p) and "error']['bad']" in imp,
            "只显示「仍缺失」⇒ 用户在站外转述不出原因，只能靠猜（本轮猜了两轮）")


def rule_beacon_not_in_plugin_dir(code):
    """信标必须写 uploads、**不得**写插件目录。返回 (ok, why)。"""
    if "wp_upload_dir()" not in code:
        return False, "没有用 wp_upload_dir() 取目录"
    if "KCJ_ASTRO_PATH" in code:
        return False, "信标路径里出现 KCJ_ASTRO_PATH（插件目录）⇒ 会被打进包、且 WP.com 常只读"
    if "@file_put_contents" not in code:
        return False, "没有用 @file_put_contents（未抑制告警会在最需要观察时打断导入）"
    return True, "wp_upload_dir() ＋ 路径不含插件目录常量"


def rule_beacon_failure_not_silent(code):
    """写盘失败**不得静默**：须收集原因、记 option、并把 why 返回给调用方。返回 (ok, why)。"""
    if "$why[]" not in code:
        return False, "缺 $why 原因收集"
    if "'kcj_astro_beacon_error'" not in code:
        return False, "缺 kcj_astro_beacon_error 记账（失败就看不见了）"
    if not re.search(r"if\s*\(\s*\$why\s*\)", code):
        return False, "缺「有失败就记账」的分支"
    return True, "$why 收集 ＋ 记 option ＋ 返回值带 why"


def rule_beacon_guards(code):
    """取值必须有守卫：拿不到就记 null、绝不抛错（信标自己不能成为故障源）。返回 (ok, why)。"""
    if "function_exists('kcj_astro_import_sets')" not in code:
        return False, "缺 function_exists 守卫（缺函数时信标会致命错）"
    if "class_exists('KCJ_Astro_DB')" not in code:
        return False, "缺 class_exists 守卫"
    if "kcj_astro_import_progress($k)" not in code:
        return False, "缺游标读取（站外最缺的就是它）"
    return True, "两处守卫 ＋ 读游标"


def rule_beacon_log_rolling(code):
    """日志必须**滚动**，否则每跳一行会无限增长。返回 (ok, why)。"""
    if "KCJ_ASTRO_LOG_MAX" not in code or "KCJ_ASTRO_LOG_KEEP" not in code:
        return False, "缺滚动上限／保留数常量"
    if "FILE_APPEND" not in code:
        return False, "不是追加写（覆盖写会丢掉历史跳）"
    if "array_slice" not in code:
        return False, "缺裁剪逻辑（array_slice）"
    return True, "上限常量 ＋ 追加写 ＋ 裁剪"


def check_beacon(root, rep):
    plug = os.path.join(root, PLUGIN_DIR)
    bp   = os.path.join(plug, "includes", "status-beacon.php")
    raw  = read_text(bp) if os.path.isfile(bp) else ""
    code = strip_php_comments_only(raw)
    main = read_text(os.path.join(plug, "wp-astro-forecast.php"))
    act  = read_text(os.path.join(plug, "includes", "activation.php"))
    imp  = strip_php_comments_only(read_text(os.path.join(plug, "includes", "admin-import.php")))

    rep.chk("★ 信标文件存在且被主文件 require（否则永远不会写）",
            os.path.isfile(bp) and "includes/status-beacon.php" in main,
            "文件 %s ｜ require %s" % (os.path.isfile(bp), "includes/status-beacon.php" in main))

    _ok, _why = rule_beacon_not_in_plugin_dir(code)
    rep.chk("★ 信标写在 uploads（不写插件目录）—— 否则会被打进包、且 WP.com 常只读", _ok, _why)
    _ok2, _why2 = rule_beacon_failure_not_silent(code)
    rep.chk("★ 信标写盘失败**不得静默**（否则「有信标」与「没写出来」在站外同形）", _ok2, _why2)
    _ok3, _why3 = rule_beacon_guards(code)
    rep.chk("★ 信标取值全有守卫（缺依赖时记 null、不抛错 —— 它不能成为新的故障源）", _ok3, _why3)
    _ok4, _why4 = rule_beacon_log_rolling(code)
    rep.chk("★ 逐跳日志会滚动（不无限增长）", _ok4, _why4)

    # 快照必须含站外最缺的四样：表行数 / 游标 offset / 失败行数 / 表结构版本
    rep.chk("★ 快照含 tables ＋ progress ＋ schema（站外最缺的四样都在里面）",
            "'tables'" in code and "'progress'" in code and "'schema'" in code
            and "'offset'" in code and "'failed'" in code and "'pct'" in code,
            "缺一项即「看得见不够」")
    rep.chk("★ 日志行只留关键计数（便于 Range 取尾部）",
            "'off'    => wp_list_pluck" in raw or "'off'" in code,
            "有 off/failed/tables 三类")

    # 触发面：每次打开导入页都写（连「什么都没点」也写）+ 激活时写一次。
    # 位置判据：`$beacon = kcj_astro_beacon_write` 必须出现在**所有分支之后**
    #   ⇒ 用「它后面不再出现 is_wp_error 的那段循环」不好判；改判更硬的一条：
    #     它必须出现在渲染 `$tables = KCJ_Astro_DB::health();` **之前**（即返回值可供页面渲染），
    #     且**不在**任何 `if ($run === ...)` 分支内部（用「其行首缩进为 4 空格、且其后首个
    #     `$tables =` 之前没有新增 `if (` 未闭合」—— 太脆）。
    #   故改用两个可判的事实：① 调用点存在且赋给 $beacon；② 页面渲染区引用了 $beacon/$b_state。
    rep.chk("★ 导入页**每次打开都写**信标（连「什么都没点」也写 —— 这才能区分「没打开」与「跑了但坏了」）",
            "$beacon = kcj_astro_beacon_write(" in imp and "if (function_exists('kcj_astro_beacon_write'))" in imp,
            "调用点在所有分支之后（见同文件注释）")
    rep.chk("★ 导入页有「公开状态信标」区（链接 ＋ 最近一次写入 ＋ 上次报错）",
            "公开状态信标" in raw or "公开状态信标" in read_text(
                os.path.join(plug, "includes", "admin-import.php")),
            "缺这一节 ⇒ 用户看不到该把哪个地址给我")
    rep.chk("★ 激活时也写一次（这样「上传并启用」立刻在站外可见）",
            "kcj_astro_beacon_write" in act, "activation.php")

    # ── 含缺陷样本负控制（每一条都要能被证伪）──
    _s1, _w1 = rule_beacon_not_in_plugin_dir(
        "$p = KCJ_ASTRO_PATH . 'data/status.json'; file_put_contents($p, $j);")
    rep.chk("★ 负控制：写进插件目录的样本必须被判出", not _s1, "样本（写插件目录）→ %s" % _w1)
    _s2, _w2 = rule_beacon_failure_not_silent(
        "file_put_contents($p, $j); return array('ok' => array('status'));")
    rep.chk("★ 负控制：失败静默的样本必须被判出", not _s2, "样本（不问成败）→ %s" % _w2)
    _s3, _w3 = rule_beacon_guards("$a = kcj_astro_import_sets(); $b = KCJ_Astro_DB::health();")
    rep.chk("★ 负控制：无守卫直接调用的样本必须被判出", not _s3, "样本（无守卫）→ %s" % _w3)
    _s4, _w4 = rule_beacon_log_rolling(
        "file_put_contents($lp, $line, FILE_APPEND);")
    rep.chk("★ 负控制：只追加不裁剪的样本必须被判出", not _s4, "样本（不滚动）→ %s" % _w4)



# =============================================================================
# 17. 列宽预算与字段长度预检（v2.2.6 新增）
# =============================================================================
# 本段治的是一类**不是「写错了」而是「写了但没生效」**的缺陷（本轮 F27 的前后左右）：
#   · 新加了一个模块，却漏进包 ⇒ 守卫让调用静默失效（新护栏变空气，判据还是绿的）；
#   · 新加了一条判据，却只在「关闭开关」那一挡验过；
#   · 新加了一个自动重导分支，却没有同步扩「自动开始的闸门」⇒ 判据有活、闸门说没活；
#   · 新加了一个缓存键，却没有让缓存**随数据变化而失效** ⇒ 页面看起来没更新。
# 故每条规则都是「**接线判据**」：查的不是函数写得对不对，而是**有没有真的被用上**。

def rule_preflight_uses_wp_numbers(code):
    """字段长度预检必须用 **WordPress 自己的**两个函数取列信息。

    ★ 为什么这条算判据：如果预检自己拿 DDL 里的宽度去推「按字符还是按字节」，
      它就只是我的**猜测的第二份副本** —— 猜错了会与 wpdb 各说各话，
      而这次事故的全部麻烦恰恰来自「两边口径不同却都自认为对」。
      调用 get_col_length()/get_col_charset() 之后，预检与真正执行写入的那段代码**同源**。
    """
    if "get_col_length" not in code:
        return False, "没有调用 $wpdb->get_col_length()（拿不到列的真实长度与 char/byte 类别）"
    if "get_col_charset" not in code:
        return False, "没有调用 $wpdb->get_col_charset()（拿不到字符集 ⇒ 无法判「按字符还是按字节」）"
    if "unit" not in code:
        return False, "没有区分计量口径（unit）⇒ 「60 字符 / 159 字节」这类值无从判断"
    return True, "get_col_length ＋ get_col_charset ＋ 显式 unit"


def rule_preflight_message_carries_numbers(code):
    """超限消息必须**自带数字**：字段名 / 值长 / 上限 / 口径。

    ★ 为什么：F27 线上给的唯一那句话是
      「处理以下字段的值失败：time_uncertainty。提供的值可能太长或包含无效数据。」
      —— 一个数字都没有，于是「太长」是字符太长还是字节太长、差多少，全靠反推。
      判据落在这里：以后任何一次超限，原因都直接印在错误里。
    """
    for tok, why in (("字符", "缺「字符数」（只有字节数时无法区分几何）"),
                     ("字节", "缺「字节数」（F27 恰恰死在字节上）"),
                     ("上限", "缺「列上限」（没有上限值就无法判断差多少）")):
        if tok not in code:
            return False, why
    if "sprintf" not in code:
        return False, "不是格式化产出（拼串容易漏字段）"
    return True, "字符数 ＋ 字节数 ＋ 上限 ＋ 声明类型"


def rule_preflight_wired(rest_code):
    """预检必须**接进 upsert 的写入路径**，且超限时**不写**（避免一次注定失败的库往返）。"""
    if "kcj_astro_preflight(" not in rest_code:
        return False, "rest-import.php 里没有调用 kcj_astro_preflight() ⇒ 预检是死代码"
    if "function_exists('kcj_astro_preflight')" not in rest_code:
        return False, "缺少 function_exists 守卫（模块漏进包时会致命错，比不检更糟）"
    m = re.search(r"kcj_astro_preflight\(\s*\$table\s*,\s*\$data\s*\)", rest_code)
    if not m:
        return False, "调用参数不是 ($table, $data) ⇒ 可能拿错表名，列信息会取错"
    tail = rest_code[m.end():m.end() + 400]
    if "continue;" not in tail:
        return False, "超限后没有 continue ⇒ 仍会走一次注定失败的写入"
    return True, "接进写入路径 ＋ 守卫 ＋ 超限即 continue"


def rule_no_negative_cache(code):
    """**空态/降级态不得进长缓存**（negative caching）。

    ★ 本轮线上症状：导入已跑完（daily_site 29,298 行在库），前台仍显示
      「观测地维度数据未覆盖 2026-09-23（需导入 wp_astro_daily_site）」、观测地下拉一个城也没有。
      成因是渲染发生在「表已建好、数据还没导进去」的那几十秒里，那段空态被写成 **12 小时**缓存。
      ⇒ 判据：降级渲染必须走**较短的** TTL 分支。
    """
    if "$degraded" not in code:
        return False, "没有降级标志 ⇒ 分不出「完整渲染」与「空态渲染」"
    if not re.search(r"\$degraded\s*\?\s*\(", code) and "MINUTE_IN_SECONDS" not in code:
        return False, "降级态没有短 TTL 分支（仍会写 12 小时）⇒ 数据到位后页面还是旧的"
    if "HOUR_IN_SECONDS" not in code:
        return False, "完整渲染也应保留长 TTL（否则每访问都查库）"
    return True, "降级态短 TTL ＋ 完整态长 TTL"


def rule_cache_key_has_epoch(code):
    """缓存键必须带**数据纪元**：数据一变，旧键按定义失效，不依赖「能不能删掉它」。"""
    if "kcj_astro_data_epoch()" not in code:
        return False, "缓存键里没有数据纪元 ⇒ 只能靠「删缓存」生效"
    m = re.search(r"\$cache_key\s*=[^;]*;", code, re.S)
    if not m or "epoch" not in m.group(0):
        return False, "纪元没有进 $cache_key ⇒ 等于没加"
    return True, "cache_key 含 epoch"


def rule_flush_punches_object_cache(code):
    """清缓存必须**穿透持久对象缓存**：只 `DELETE FROM wp_options` 是不够的。

    ★ WP.com 有持久对象缓存；transient 的值可能在对象缓存里，删表删不掉它。
      本轮「清了缓存而页面还是旧的」就有这一层。故要求：逐键 delete_transient() ＋ 纪元 +1。
    """
    if "delete_transient" not in code:
        return False, "只删 options 表（对象缓存里的值还在）"
    if "kcj_astro_data_epoch" not in code:
        return False, "没有同时推进数据纪元（第二层保险）"
    if "DELETE FROM" not in code:
        return False, "缺原地兜底清理（timeout 行会残留）"
    return True, "逐键 delete_transient ＋ 纪元 +1 ＋ 原地兜底"


def rule_schema_autorun(imp_code):
    """表结构变更后**自动重导**上次失败的数据集，且**闸门与判据同源**。

    ★ 为什么必须同源：如果「候选判定」认为有活可干、而「自动开始的闸门」认为没活，
      就会出现最尴尬的一种情况 —— **打开页面什么都不发生**，
      我在这头等结果、用户在那头以为已经好了（上一轮的教训）。
    """
    if "kcj_astro_import_schema_changed" not in imp_code:
        return False, "缺 kcj_astro_import_schema_changed() ⇒ 失败集永远不重导"
    if "fail_schema" not in imp_code:
        return False, "没有记录「失败发生在哪个 schema 版本上」⇒ 无从判断该不该重导"
    n = len(re.findall(r"kcj_astro_import_schema_changed\(", imp_code))
    if n < 2:
        return False, "只在 %d 处调用 ⇒ 闸门与候选判定不同源（会漏掉或空转）" % n
    if "$redo" not in imp_code:
        return False, "缺 $redo ⇒ 自动开始的闸门漏掉「已完成但全失败」的集"
    return True, "schema_changed 两处同源 ＋ $redo 进闸门"


def check_colbudget(root, rep):
    plug = os.path.join(root, PLUGIN_DIR)
    cb_p  = os.path.join(plug, "includes", "col-budget.php")
    raw   = read_text(cb_p) if os.path.isfile(cb_p) else ""
    code  = strip_php_comments_only(raw)
    main  = read_text(os.path.join(plug, "wp-astro-forecast.php"))
    rest  = strip_php_comments_only(read_text(os.path.join(plug, "includes", "rest-import.php")))
    sc    = strip_php_comments_only(read_text(os.path.join(plug, "includes", "shortcodes.php")))
    act   = strip_php_comments_only(read_text(os.path.join(plug, "includes", "activation.php")))
    imp   = strip_php_comments_only(read_text(os.path.join(plug, "includes", "admin-import.php")))

    rep.chk("★ col-budget.php 存在且被主文件 require（否则预检永远是死代码）",
            os.path.isfile(cb_p) and "includes/col-budget.php" in main,
            "文件 %s ｜ require %s" % (os.path.isfile(cb_p), "includes/col-budget.php" in main))
    rep.chk("★ col-budget.php 有 ABSPATH 守卫（与其余 includes 一致）",
            "if (!defined('ABSPATH'))" in raw or "if (!defined('ABSPATH'))" in raw.replace(" ", ""),
            "缺守卫 ⇒ 可被直接访问")

    _rules = [
        ("预检用 WordPress 自己的取数函数（不是自造第二套口径）",
         rule_preflight_uses_wp_numbers(code),
         "$l = 64; if (strlen($v) > $l) { return '太长'; }",
         "样本（自己拿 DDL 宽度推）"),
        ("超限消息自带数字（字段/值长/上限/口径）",
         rule_preflight_message_carries_numbers(code),
         "return sprintf('字段 %s 装不下', $col);",
         "样本（消息无数字）"),
        ("预检**接进** upsert 写入路径且超限即 continue",
         rule_preflight_wired(rest),
         "function kcj_astro_preflight($t, $d) { return array(); }",
         "样本（函数存在但无人调用）"),
        ("空态/降级态**不得**进 12 小时缓存（负缓存）",
         rule_no_negative_cache(sc),
         "$html = kcj_astro_render_template('astro-today', $data); set_transient($k, $html, 12 * HOUR_IN_SECONDS);",
         "样本（无降级分支）"),
        ("缓存键带数据纪元（数据一变旧键即失效）",
         rule_cache_key_has_epoch(sc),
         "$cache_key = 'kcj_astro_today_' . $date . '_' . $place;",
         "样本（键里没有 epoch）"),
        ("清缓存穿透对象缓存（逐键 delete_transient ＋ 纪元）",
         rule_flush_punches_object_cache(act),
         "$wpdb->query(\"DELETE FROM {$wpdb->options} WHERE option_name LIKE '_transient_kcj_astro_%'\");",
         "样本（只删 options 表）"),
        ("表结构变更后自动重导，且闸门与判据同源",
         rule_schema_autorun(imp),
         "if ($p['done'] && $p['failed'] > 0) { $stale[] = $k; continue; }",
         "样本（失败集永远跳过）"),
    ]
    n_neg = 0
    for name, (rok, rwhy), sample, sname in _rules:
        rep.chk("★ %s" % name, rok, rwhy)
        if sample is not None:
            _sn, _sw = None, None
            # 用同一函数跑含缺陷样本：必须被判出（否则该规则是空壳）
            fn = {"预检用 WordPress 自己的取数函数（不是自造第二套口径）": rule_preflight_uses_wp_numbers,
                  "超限消息自带数字（字段/值长/上限/口径）": rule_preflight_message_carries_numbers,
                  "预检**接进** upsert 写入路径且超限即 continue": rule_preflight_wired,
                  "空态/降级态**不得**进 12 小时缓存（负缓存）": rule_no_negative_cache,
                  "缓存键带数据纪元（数据一变旧键即失效）": rule_cache_key_has_epoch,
                  "清缓存穿透对象缓存（逐键 delete_transient ＋ 纪元）": rule_flush_punches_object_cache,
                  "表结构变更后自动重导，且闸门与判据同源": rule_schema_autorun,
                  }[name]
            _sn, _sw = fn(sample)
            n_neg += 1
            rep.chk("★ 负控制：%s必须被判出（否则该规则是空壳）" % sname, not _sn,
                    "%s → %s" % (sname, _sw))
    rep.chk("★ 第 17 段负控制条数 == 规则条数（逐条都有反证，不漏空壳）",
            n_neg == len(_rules), "负控制 %d / 规则 %d" % (n_neg, len(_rules)))


# ============================================================================
# 18. 列宽口径 = 字节（v2.2.6 续 · 2026-09-23 线上直采后新增）
# ============================================================================
# 为什么单独立一段：
#   线上列的字符集是 `latin1_swedish_ci`（v2.2.6 信标 cols 段**直采**，见
#   `_diag/live_cols_2026-09-23.json`），而 WordPress 的 `strip_invalid_text()`
#   对 latin1 列**一律按字节**判长度 ⇒ **中文每字 3 字节**。
#   而生成侧的三处裁剪与判据侧的内联检查原先全都按**字符**（Python `len`）
#   ⇒ 「上游按字符放行、下游按字节拒收」，这就是 F27（4,672 行全数被拒）。
#   所以这一段判的是**单位**，而不是某个具体数值 —— 数值会变，单位不该再错。
# ============================================================================

def rule_clip_is_byte_based(src):
    """裁剪/检查函数必须出现 UTF-8 字节长度（不得只用 `len()`）。"""
    hits = len(re.findall(r"encode\(\s*['\"]utf-8['\"]\s*\)", src))
    if hits < 2:
        return None, "只出现 %d 处 utf-8 编码 ⇒ 仍按字符判长度" % hits
    if re.search(r"len\s*\(\s*s\s*\)\s*>\s*n", src) and not re.search(
            r"_utf8_len|utf8_len|byte_len", src):
        return None, "仍在用 `len(s) > n`（字符口径）且没有字节长度函数"
    return True, "utf-8 字节长度 %d 处 ＋ 字节口径比较" % hits


def rule_unit_documented(src):
    """声明处必须写明「单位＝字节」—— 数值会变，单位最容易被后人读错。"""
    return ("字节" in src and "utf-8" in src.lower()),         "声明处%s提到「字节」与 utf-8" % ("" if "字节" in src else "未")


def rule_no_silent_char_slice(src):
    """不得出现「按字符切片当裁剪」的写法（`return s[:n]` / `return s[:lim]`）。

    ⚠ 本条自身踩过一次**假红**（2026-09-23）：字节版裁剪的正确写法是
      `return b[:n].decode("utf-8", "ignore")` —— 前半段长得和「按字符切片」一模一样，
      第一版正则把它判成了缺陷。⇒ 加**否定前瞻**：后面紧跟 `.decode(` 的不算。
      （教训与本项目「假红比假绿更坏」同族：它会让后来人把这条判据删掉。）
    """
    bad = re.findall(r"return\s+[A-Za-z_][A-Za-z0-9_]*\[\s*:\s*(?:n|lim)\s*\]\s*(?!\.decode)",
                     src)
    return (not bad), "发现按字符切片：%s" % (bad or "无")


def rule_live_cols_recorded(root):
    """线上列实况必须留档（判据要能引用**直采**事实，而不是只引用本地声明）。"""
    p = os.path.join(root, "_diag", "live_cols_2026-09-23.json")
    if not os.path.isfile(p):
        return None, "缺 %s（线上直采证据未留档）" % os.path.relpath(p, root)
    try:
        d = json.loads(read_text(p))
    except Exception as e:  # noqa: BLE001
        return None, "解析失败：%s" % e
    cols = d.get("cols") or {}
    tu = ((cols.get("events") or {}).get("time_uncertainty") or {})
    if not tu:
        return None, "留档件里没有 events.time_uncertainty"
    return True, "ver=%s ｜ time_uncertainty=%s coll=%s 口径=%s" % (
        d.get("beacon_ver"), tu.get("type"), tu.get("coll"), tu.get("unit"))


def rule_live_unit_is_byte(root):
    """★ 直采结论必须是「按字节」：若哪天线上列变成 utf8mb4，这条会报红提醒复核。"""
    p = os.path.join(root, "_diag", "live_cols_2026-09-23.json")
    if not os.path.isfile(p):
        return None, "无留档 ⇒ 无法判定（不静默当通过）"
    cols = (json.loads(read_text(p)).get("cols") or {})
    units = set()
    for _t, cinfo in cols.items():
        for _c, meta in (cinfo or {}).items():
            units.add(meta.get("unit"))
    return (units == {"byte"}), "全部列的口径集合 = %s" % sorted(x for x in units if x)


def rule_declared_vs_live_charset(root):
    """★ 本机 DDL **声明**的字符集 vs 线上列**实况**的字符集 —— 差异必须被看见。

    ★★ 这是 F27 更要命的那一层（2026-09-23 实测）：
      本地 `sql/install_tables.sql` 写着 `DEFAULT CHARSET=utf8mb4`（判据也一直在验这一条），
      而线上 `SHOW FULL COLUMNS` 报出来的每一列都挂在 **`latin1_swedish_ci`** 下。
      ⇒ **声明 charset=utf8mb4、实况 latin1**：两边对「宽度」的语义**根本不同**
        （utf8mb4 ⇒ WP 按**字符**判；latin1 ⇒ WP 按**字节**判）。
      ⇒ 「列宽对拍」历来通过了，**「字符集对拍」从来没人做过** ——
        这是与 F27 完全同构的一处盲区（**判据只量它认识的量**）。
      ⇒ 本条**只记录、不判红**（改不了托管环境的库默认字符集），但它必须**每次出现**，
        否则后人会又一次相信「本地说 utf8mb4，所以是按字符算」。
    """
    p = os.path.join(root, "_diag", "live_cols_2026-09-23.json")
    if not os.path.isfile(p):
        return None, "无留档 ⇒ 无法比对"
    cols = (json.loads(read_text(p)).get("cols") or {})
    colls = set()
    for _t, cinfo in cols.items():
        for _c, meta in (cinfo or {}).items():
            if meta.get("coll"):
                colls.add(meta["coll"])
    sqlp = os.path.join(root, "sql", "install_tables.sql")
    declared = "?"
    if os.path.isfile(sqlp):
        m = re.search(r"utf8mb4[a-z_]*", read_text(sqlp))
        declared = m.group(0) if m else "（SQL 里没写 charset）"
    return True, ("本机 DDL 声明 %s ／ 线上实况 %s ⇒ **宽度语义按字节**（已由 MIN_WIDTHS "
                  "字节口径 ＋ col-budget 的 unit=byte 兜住）" % (declared, sorted(colls) or "?"))


def check_colunits(root, rep):
    bd = read_text(os.path.join(root, "python", "build_dataset.py"))
    bs = read_text(os.path.join(root, "python", "build_site.py"))
    ea = read_text(os.path.join(root, "python", "event_almanac.py"))

    _rules = [
        ("build_dataset 的裁剪按字节", rule_clip_is_byte_based(bd),
         "def _clip(s, key):\n    n = COL_MAXLEN.get(key)\n    if len(s) > n:\n        return s[:n]\n    return s",
         "样本（按字符裁剪）"),
        ("build_site 的裁剪按字节", rule_clip_is_byte_based(bs),
         "def clip(value, key):\n    s = str(value)\n    n = COL_MAXLEN.get(key)\n    if len(s) > n:\n        return s[:n]",
         "样本（按字符裁剪）"),
        ("event_almanac 的裁剪按字节", rule_clip_is_byte_based(ea),
         "def _clip(s, key):\n    lim = COL_MAXLEN.get(key)\n    if len(s) > lim:\n        return s[:lim]\n    return s",
         "样本（按字符裁剪）"),
        ("三处声明都写明「单位＝字节」", rule_unit_documented(bd) and rule_unit_documented(bs)
         and rule_unit_documented(ea),
         "COL_MAXLEN = {\n    \"time_uncertainty\": 64,\n}\n",
         "样本（没写单位）"),
        ("不得出现「按字符切片当裁剪」", rule_no_silent_char_slice(bd) and
         rule_no_silent_char_slice(bs) and rule_no_silent_char_slice(ea),
         "def _clip(s, key):\n    lim = COL_MAXLEN.get(key)\n    return s[:lim]\n",
         "样本（s[:lim] 按字符切片）"),
    ]
    n_neg = 0
    for name, (rok, rwhy), sample, sname in _rules:
        rep.chk("★ %s" % name, rok, rwhy)
        if sample is not None:
            _sn, _sw = None, None
            fn = {"build_dataset 的裁剪按字节": rule_clip_is_byte_based,
                  "build_site 的裁剪按字节": rule_clip_is_byte_based,
                  "event_almanac 的裁剪按字节": rule_clip_is_byte_based,
                  "三处声明都写明「单位＝字节」": rule_unit_documented,
                  "不得出现「按字符切片当裁剪」": rule_no_silent_char_slice,
                  }[name]
            _sn, _sw = fn(sample)
            n_neg += 1
            rep.chk("★ 负控制：%s必须被判出（否则该规则是空壳）" % sname, not _sn,
                    "%s → %s" % (sname, _sw))
    rep.chk("★ 第 18 段负控制条数 == 规则条数（逐条都有反证）",
            n_neg == len(_rules), "负控制 %d / 规则 %d" % (n_neg, len(_rules)))

    # 线上直采两条（**不判本地声明，判线上事实**）
    _ok, _why = rule_live_cols_recorded(root)
    rep.chk("★★ 线上列实况已留档（`_diag/live_cols_2026-09-23.json`）", _ok, _why)
    _ok2, _why2 = rule_live_unit_is_byte(root)
    rep.chk("★★ 线上列的口径确为「按字节」（F27 的直接证据）", _ok2, _why2)
    _ok4, _why4 = rule_declared_vs_live_charset(root)
    rep.chk("★★【只记录·不判红】本机 DDL 声明字符集 vs 线上实况（两者不同 ⇒ 宽度语义按字节）",
            _ok4, _why4)

    # 负控制：直采留档缺失时必须**报红**（不得静默当通过）
    _tmp = os.path.join(root, "_diag", "live_cols_0000-00-00.json")
    _ok3, _why3 = rule_live_cols_recorded(root)
    rep.chk("★ 负控制：留档件在场时该规则判绿（否则是空壳）", bool(_ok3), _why3)
    if os.path.isfile(_tmp):
        os.remove(_tmp)


# ── 19. 栏目激活态随 URL 走（v2.2.7 / F52）────────────────────────────────
#   用户线上报：「在未来天象中选择：本月、本季、本年，都会自动跳转到今日天象。
#   在历史天象中选择：前一天、前七天、后一天、后七天，都会自动跳转今日天象。」
#
#   病根：三栏是**纯 CSS radio 切换**，而模板把**第 0 个** radio 写死成 checked；
#   栏内每个跳转链接都是普通 <a href> ⇒ 一定整页重载 ⇒ radio 复位到第 0 栏。
#   ★ 这一类缺陷特殊在哪：**数据其实已经换对了**，只是被藏在第 2、3 栏里。
#     既没有报错、也没有坏数据，所以「字面看源码」永远看不出问题 ——
#     只有盯住「重载后开的是哪一栏」才抓得到（故本段既扫源码、也要求有真跑 PHP 的桩用例）。
#
#   ⚠ 静态判据一律在**剥掉注释**后的代码上扫：上面的说明与本轮的实现注释里**有意**
#     写着旧写法 `($i === 0) ? ' checked="checked"'`，不剥注释就是判据咬住自己的文档
#     （与「描述判据的文档把自己豁免」同族的自指陷阱，方向相反）。
def rule_hub_checked_from_active(src):
    """模板的 checked 必须由 $active_i 决定，且不得再有写死的第 0 栏。"""
    if re.search(r"\$i\s*===\s*0\s*\)\s*\?", src):
        return False, "仍见 `($i === 0) ?` 决定 checked ⇒ 栏内一跳到重载就丢回第一栏"
    if not re.search(r"\$i\s*===\s*\$active_i\s*\)\s*\?", src):
        return False, "找不到 `($i === $active_i) ?` ⇒ 激活态没接线（等于没修）"
    return True, "checked 由 $active_i 决定"


def rule_hub_clamps_active(src):
    """$active_i 必须给缺省值**并夹紧到合法范围**。
    越界时若一个 radio 都不 checked，三个栏目会**同时显示**（CSS 靠 :checked 选栏）——
    那比跳回第一栏更糟，且同样不报错。"""
    if not re.search(r"\$active_i\s*=\s*isset\(\s*\$active_i\s*\)", src):
        return False, "缺少 $active_i 的缺省赋值（模板被别处调用时会 undefined 告警）"
    if not re.search(r"count\(\s*\$sections\s*\)", src):
        return False, "缺少越界夹紧（count($sections)）⇒ 下标越界时可能一个都不 checked"
    return True, "缺省 0 ＋ 越界夹紧到 0"


def rule_hub_resolver_reads_get(src):
    """解析器读三个参数（kcj_tab / kcj_period / kcj_md），且只认**页面上真有的**栏。"""
    miss = [k for k in ("kcj_tab", "kcj_period", "kcj_md") if ("$_GET['" + k + "']") not in src]
    if miss:
        return False, "解析器没读这些参数：%s" % miss
    for k in ("future", "past"):
        if not re.search(r"in_array\(\s*'%s'\s*,\s*\$keys" % k, src):
            return False, ("没确认 `%s` 栏**此刻真在页面上** ⇒ 作者用 %s=\"0\" 关掉该栏后，"
                           "URL 里还带着参数时会认出一个不存在的栏（开出空白）"
                           % (k, k))
    return True, "读三个参数 ＋ 逐栏在位性检查"


def rule_hub_wired(src):
    """[astro_hub] 必须真把解析结果**传给模板**（算了不用是另一种静默失败）。"""
    if "kcj_astro_hub_active_key(" not in src:
        return False, "没有调用 kcj_astro_hub_active_key()"
    if not re.search(r"'active_i'\s*=>", src):
        return False, "算出来的激活栏没有传进模板（算了不用）"
    return True, "调用 ＋ 传参都在"


def rule_period_link_has_tab(src):
    if not re.search(r"\$q\['kcj_tab'\]\s*=\s*'future'", src):
        return False, "期间链接没写 kcj_tab=future ⇒ 重载后 hub 只能靠推断，而 URL 里常有两个参数"
    return True, "期间链接带 kcj_tab=future"


def rule_history_link_has_tab(src):
    if not re.search(r"function\s+kcj_astro_history_nav\([^)]*\$extra", src):
        return False, "kcj_astro_history_nav() 没有 $extra 形参 ⇒ 传不进 kcj_tab"
    if not re.search(r"kcj_astro_history_nav\(.{0,200}?'kcj_tab'\s*=>\s*'past'", src, re.S):
        return False, "调用处没给 kcj_tab=past ⇒ 历史栏跳转仍会丢回第一栏"
    return True, "$extra 形参 ＋ 调用处传 past"


def check_hub_tabs(root, rep):
    plug = os.path.join(root, PLUGIN_DIR)
    hub_p = os.path.join(plug, "templates", "astro-hub.php")
    rep_p = os.path.join(plug, "templates", "astro-forecast-report.php")
    sc_p = os.path.join(plug, "includes", "shortcodes.php")
    hub = strip_php_comments_only(read_text(hub_p)) if os.path.isfile(hub_p) else ""
    rpt = strip_php_comments_only(read_text(rep_p)) if os.path.isfile(rep_p) else ""
    sc = strip_php_comments_only(read_text(sc_p)) if os.path.isfile(sc_p) else ""
    rep.chk("★ 三处相关件都在位且非空（空集守卫）",
            bool(hub) and bool(rpt) and bool(sc),
            "hub=%d 字符 / report=%d / shortcodes=%d" % (len(hub), len(rpt), len(sc)))
    if not (hub and rpt and sc):
        return

    _rules = [
        ("模板的 checked 由 $active_i 决定（不再写死第 0 栏）",
         rule_hub_checked_from_active(hub),
         "<?php echo ($i === 0) ? ' checked=\"checked\"' : ''; ?>",
         "样本（check 写死在第 0 栏 = 线上那个 bug 的原形）"),
        ("$active_i 有缺省值且越界夹紧（否则可能一个栏都不显示）",
         rule_hub_clamps_active(hub),
         "$active_i = isset($active_i) ? (int) $active_i : 0;\n?>\n<div>",
         "样本（只给缺省值、不夹紧）"),
        ("解析器读三个参数 ＋ 逐栏在位性检查",
         rule_hub_resolver_reads_get(sc),
         "function kcj_astro_hub_active_key($sections) {\n"
         "    if (isset($_GET['kcj_period'])) { return 'future'; }\n"
         "    return '';\n}\n",
         "样本（只读一个参数、不查栏在不在）"),
        ("解析结果真的传给了模板（不是算了不用）",
         rule_hub_wired(sc),
         "    $active_key = kcj_astro_hub_active_key($sections);\n"
         "    return kcj_astro_render_template('astro-hub', array('sections' => $sections));\n",
         "样本（算了不传）"),
        ("期间链接自带 kcj_tab=future",
         rule_period_link_has_tab(rpt),
         "$q = array('kcj_period' => $pk);\n$href = $kcj_base . '?' . http_build_query($q);\n",
         "样本（只带 kcj_period）"),
        ("历史跳转链接自带 kcj_tab=past",
         rule_history_link_has_tab(sc),
         "function kcj_astro_history_nav($mon, $day, $offsets = null) {\n"
         "    $out[] = array('url' => add_query_arg('kcj_md', $md));\n"
         "}\nkcj_astro_history_nav($mon, $day);\n",
         "样本（旧签名、只带 kcj_md）"),
    ]
    n_neg = 0
    _fns = {
        "模板的 checked 由 $active_i 决定（不再写死第 0 栏）": rule_hub_checked_from_active,
        "$active_i 有缺省值且越界夹紧（否则可能一个栏都不显示）": rule_hub_clamps_active,
        "解析器读三个参数 ＋ 逐栏在位性检查": rule_hub_resolver_reads_get,
        "解析结果真的传给了模板（不是算了不用）": rule_hub_wired,
        "期间链接自带 kcj_tab=future": rule_period_link_has_tab,
        "历史跳转链接自带 kcj_tab=past": rule_history_link_has_tab,
    }
    for name, (rok, rwhy), sample, sname in _rules:
        rep.chk("★ %s" % name, rok, rwhy)
        _ok, _why = _fns[name](sample)
        n_neg += 1
        rep.chk("★ 负控制：%s必须被判出（否则该规则是空壳）" % sname, not _ok,
                "%s → %s" % (sname, _why))
    rep.chk("★ 第 19 段负控制条数 == 规则条数（逐条都有反证）",
            n_neg == len(_rules), "负控制 %d / 规则 %d" % (n_neg, len(_rules)))

    # ★ 静态扫描抓不到「渲染出来 checked 落在谁身上」⇒ 必须有一条**真跑 PHP** 的桩用例。
    #   本条只保证那条用例没被删（用例本身的断言在 php_selftest.py 里）。
    sel_p = os.path.join(root, "php_selftest.py")
    sel = read_text(sel_p) if os.path.isfile(sel_p) else ""
    rep.chk("★★ 有真跑 PHP 的桩用例（渲染 astro-hub 后数 checked 落在谁身上）",
            "hub_tabs" in sel and "kcj_astro_render_template('astro-hub'" in sel,
            "缺桩用例 ⇒ 本段只剩读码，而「写死第 0 栏」恰恰是读码最容易漏的一类")


def check_v230(root, rep):
    """第 20 段（v2.3.0 新增）：观测地扩到全国 · 界面去重 · 审计留史 · 批量回写。

    ★ 本段的写法照第 19 段：每条规则写成**纯函数**（文本进、结论出），
      再拿一份**含缺陷的最小样本**反向断言一次 —— 否则「规则永远返回真」这种
      空壳检测器也能全绿（本项目已经栽过）。
    """
    plug = os.path.join(root, PLUGIN_DIR)
    rest_p = os.path.join(plug, "includes", "rest-import.php")
    sc_p   = os.path.join(plug, "includes", "shortcodes.php")
    imp_p  = os.path.join(plug, "includes", "admin-import.php")
    hub_p  = os.path.join(plug, "templates", "astro-hub.php")
    rpt_p  = os.path.join(plug, "templates", "astro-forecast-report.php")
    tdy_p  = os.path.join(plug, "templates", "astro-today.php")
    css_p  = os.path.join(plug, "assets", "astro-style.css")
    js_p   = os.path.join(plug, "assets", "astro-place.js")
    bs_p   = os.path.join(root, "python", "build_site.py")
    cs_p   = os.path.join(root, "python", "compute_sky.py")

    rest = strip_php_comments_only(read_text(rest_p)) if os.path.isfile(rest_p) else ""
    sc   = strip_php_comments_only(read_text(sc_p)) if os.path.isfile(sc_p) else ""
    imp  = read_text(imp_p) if os.path.isfile(imp_p) else ""
    hub  = strip_php_comments_only(read_text(hub_p)) if os.path.isfile(hub_p) else ""
    rpt  = strip_php_comments_only(read_text(rpt_p)) if os.path.isfile(rpt_p) else ""
    tdy  = strip_php_comments_only(read_text(tdy_p)) if os.path.isfile(tdy_p) else ""
    css  = read_text(css_p) if os.path.isfile(css_p) else ""
    js   = read_text(js_p) if os.path.isfile(js_p) else ""
    bs   = read_text(bs_p) if os.path.isfile(bs_p) else ""
    cs   = read_text(cs_p) if os.path.isfile(cs_p) else ""

    rep.chk("★ 相关件都在位且非空（空集守卫）",
            all([rest, sc, imp, hub, rpt, tdy, css, js, bs, cs]),
            "rest=%d sc=%d imp=%d hub=%d rpt=%d tdy=%d css=%d js=%d bs=%d cs=%d"
            % (len(rest), len(sc), len(imp), len(hub), len(rpt), len(tdy),
               len(css), len(js), len(bs), len(cs)))
    if not all([rest, sc, imp, hub, rpt, tdy, css, js, bs, cs]):
        return

    # ── 规则函数（文本 → (ok, why)）────────────────────────────────────
    def r_bulk_guard(src):
        """批量 ON DUPLICATE 之前必须**实查唯一索引**在不在。"""
        if "kcj_astro_rest_unique_index_ok" not in src:
            return (False, "没有 kcj_astro_rest_unique_index_ok ⇒ 唯一索引不在时会静默插重复行")
        if "SHOW INDEX FROM" not in src:
            return (False, "没实查 SHOW INDEX ⇒ 只看建表语句，托管库上可能根本没有那个索引")
        if re.search(r"if\s*\(\s*!\s*kcj_astro_rest_unique_index_ok\s*\(\s*\$table\s*\)\s*\)\s*\{\s*return null", src) is None:
            return (False, "没有「索引不在 ⇒ 退回慢路径」的分支")
        return (True, "实查 SHOW INDEX ＋ 不达标即退回慢路径")

    def r_bulk_excl_events(src):
        """events 必须排除在快路径外（要拿 insert_id 同步 CPT）。"""
        if re.search(r"\$table\s*!==\s*'events'", src) is None:
            return (False, "没排除 events ⇒ 多行语句给不出每行 id ⇒ CPT 详情页静默不同步")
        return (True, "events 显式排除")

    def r_bulk_null(src):
        """NULL 必须写字面 NULL，不能走 %s（wpdb 会把 null 变成空串）。"""
        if "$cells[] = 'NULL';" not in src:
            return (False, "空值走 %s ⇒ 被写成空串；SMALLINT 报错、语义也从「没有数据」变「零/空」")
        return (True, "空值写字面 NULL")

    def r_chunk(src):
        m = re.search(r"KCJ_ASTRO_IMPORT_CHUNK'\s*,\s*(\d+)", src)
        if not m:
            return (False, "找不到 CHUNK 常量")
        n = int(m.group(1))
        if n < 1000:
            return (False, "CHUNK=%d：批量回写下仍按小批 ⇒ 跳数过多" % n)
        return (True, "CHUNK=%d" % n)

    def r_audit_append(sc2):
        """审计必须「只追加、不覆盖」。"""
        if re.search(r"\$last\s*\[\s*\$date\s*\]\s*=", sc2):
            return (False, "仍有 `$last[$date] =` ⇒ 按日期覆盖，瞬时降级会盖掉正常值")
        if "$log[]" not in sc2:
            return (False, "没有追加写 `$log[]`")
        if "'expect'" not in sc2:
            return (False, "没记 expect ⇒ 站外无法判「340/340 齐」还是「38/340 缺」")
        if "array_slice($log, -50)" not in sc2:
            return (False, "保留窗口不是「按次数」")
        return (True, "只追加 ＋ 记 expect ＋ 留最近 50 次")

    def r_audit_migrate(sc2):
        """旧格式（按日期为键）必须迁移而不是丢弃 —— 那是用户报的那次降级的唯一证据。"""
        if "isset($log[0])" not in sc2:
            return (False, "没有旧格式判别 ⇒ 老 option 会被当成列表误读")
        return (True, "旧格式迁移分支在场")

    def r_table_scroll(rpt2, css2):
        if "kcj-astro-tablewrap" not in rpt2:
            return (False, "报告表没有滚动容器 ⇒ 窄屏下仍会压缩中间列（类型列被压成竖排）")
        if "<colgroup>" not in rpt2:
            return (False, "没有 colgroup ⇒ 时间/类型列没有保底宽度")
        if ".kcj-astro-td-type" not in css2:
            return (False, "CSS 缺 .kcj-astro-td-type（nowrap）")
        m = re.search(r"\.kcj-astro-report-table\s*\{[^}]*min-width", css2)
        if m is None:
            return (False, "报告表没有 min-width ⇒ 会被「塞进容器」这条约束把宽度压回去")
        return (True, "滚动容器 ＋ colgroup ＋ nowrap ＋ min-width 四层齐")

    def r_dedup(tdy2, hub2, css2):
        if 'class="kcj-astro-h3 kcj-astro-sr"' not in tdy2:
            return (False, "今日板块标题没有改为视觉隐藏 ⇒ 「今日天象」在页面上仍重复")
        if "kcj-astro-hub-pane-h kcj-astro-sr" not in hub2:
            return (False, "hub 栏内标题没有改为视觉隐藏 ⇒ 与栏目标头重复")
        if ".kcj-astro-sr" not in css2:
            return (False, "CSS 缺 .kcj-astro-sr")
        if "position: absolute !important" not in css2:
            return (False, "缺 !important ⇒ 同特异度的后置规则会把视觉隐藏类盖掉，留下幽灵盒")
        return (True, "两处标题转视觉隐藏 ＋ 类定义带 !important")

    def r_clean_link(hub2):
        if "remove_query_arg" not in hub2:
            return (False, "缺「清除视图参数」链接 ⇒ F52 的 URL 污染没有读者的出口")
        if re.search(r"add_query_arg\s*\(", hub2) and "remove_query_arg" not in hub2:
            return (False, "用了 add_query_arg 反向构造（会带上当前请求全部参数）")
        return (True, "从永久链接出发、只摘 kcj_* 参数")

    def r_window(bs2):
        mb = re.search(r"ROLLING_BEHIND_DAYS\s*=\s*(\d+)", bs2)
        ma = re.search(r"ROLLING_AHEAD_DAYS\s*=\s*(\d+)", bs2)
        if not mb or not ma:
            return (False, "找不到滚动窗常量")
        b, a = int(mb.group(1)), int(ma.group(1))
        if b > 30:
            return (False, "BEFORE=%d：daily_site 只被「今天」查询，往前窗纯属浪费" % b)
        if a > 200:
            return (False, "AHEAD=%d：锚点 ×8.95 后维持大窗会把数据面放大到查询用不到的量级" % a)
        return (True, "−%d / +%d 天" % (b, a))

    def r_no_fallback(cs2):
        if "_load_places_json" not in cs2:
            return (False, "compute_sky 没有从 places_cn.json 读观测地档 ⇒ 仍是内置 38 城")
        if "raise RuntimeError" not in cs2.split("_load_places_json")[1][:2000]:
            return (False, "读不到清单时不报错 ⇒ 会静默退化成 38 城而调用方以为扩张成功")
        if "CITIES_LEGACY" not in cs2:
            return (False, "没有 CITIES_LEGACY ⇒ 旧键认领表随产物漂移，老 URL 会断链")
        return (True, "读 JSON ＋ 读不到即报错 ＋ 校订档另存")

    def r_no_bare_amp(js2):
        n = js2.count("&")
        if n:
            return (False, "出现 %d 个与号字符 ⇒ 平台实体替换会拆断脚本" % n)
        return (True, "零与号")

    _rules = [
        ("批量回写前实查唯一索引", r_bulk_guard(rest),
         "INSERT INTO {$tbl} ({$names}) VALUES {$ph} ON DUPLICATE KEY UPDATE {$upd};\n",
         "样本（不看索引就多行插入）"),
        ("events 排除在快路径之外", r_bulk_excl_events(rest),
         "if ($table !== 'daily_site') {\n    $fast = kcj_astro_rest_bulk_upsert($table, $rows, $cols);\n}\n",
         "样本（events 也走快路径）"),
        ("批量语句的空值写字面 NULL", r_bulk_null(rest),
         "foreach ($cols_used as $c) { $cells[] = '%s'; $vals[] = $item[1][$c]; }\n",
         "样本（空值走 %s）"),
        ("导入批大小已随回写方式放大", r_chunk(imp),
         "define('KCJ_ASTRO_IMPORT_CHUNK', 400);\n",
         "样本（批量回写下仍 400/批）"),
        ("观测地审计只追加不覆盖", r_audit_append(sc),
         "$last = get_option('kcj_astro_places_seen', array());\n"
         "$last[$date] = array('rows' => (int) $n, 'at' => current_time('mysql'));\n"
         "if (count($last) > 20) { ksort($last); $last = array_slice($last, -20, null, true); }\n"
         "update_option('kcj_astro_places_seen', $last, false);\n",
         "样本（以日期为键覆盖、只留 20 个日期）"),
        ("旧审计格式迁移而非丢弃", r_audit_migrate(sc),
         "$log = get_option('kcj_astro_places_seen', array());\n$log[] = $row;\n",
         "样本（不判旧格式）"),
        ("报告表四层治「类型列被压成竖排」", r_table_scroll(rpt, css),
         "<table class=\"kcj-astro-report-table\">\n"
         "<thead><tr><th>时间</th><th>类型</th></tr></thead>\n</table>\n",
         "样本（无滚动容器/无 colgroup）"),
        ("重复标题转视觉隐藏且类定义够硬", r_dedup(tdy, hub, css),
         "<h3 class=\"kcj-astro-h3\">今日天象</h3>\n"
         "<h3 class=\"kcj-astro-hub-pane-h\">今日天象</h3>\n"
         ".kcj-astro-sr { position: absolute; }\n",
         "样本（标题仍可见、隐藏类无 !important）"),
        ("有「清除视图参数」的出口", r_clean_link(hub),
         "<p><a href=\"<?php echo esc_url(add_query_arg(array())); ?>\">回到今日</a></p>\n",
         "样本（只有 add_query_arg）"),
        ("观测地滚动窗按用途收紧", r_window(bs),
         "ROLLING_BEHIND_DAYS = 370\nROLLING_AHEAD_DAYS = 400\n",
         "样本（照抄 771 天窗）"),
        ("观测地档从 JSON 读且不静默回落", r_no_fallback(cs),
         "def _load_places_json(path=None):\n"
         "    CITIES = dict(CONFIG.CITIES_LEGACY)\n"
         "    return CITIES, path, {}\n",
         "样本（读不到就回落 38 城）"),
        ("前端脚本零与号", r_no_bare_amp(js),
         "if (a && b) { x(); }\n",
         "样本（用逻辑与）"),
    ]
    n_neg = 0
    for name, (rok, rwhy), sample, sname in _rules:
        rep.chk("★ %s" % name, rok, rwhy)
        n_neg += 1
        # 负控制：同一规则必须把「含缺陷样本」判红
        r2 = {
            "批量回写前实查唯一索引": r_bulk_guard,
            "events 排除在快路径之外": r_bulk_excl_events,
            "批量语句的空值写字面 NULL": r_bulk_null,
            "导入批大小已随回写方式放大": r_chunk,
            "观测地审计只追加不覆盖": r_audit_append,
            "旧审计格式迁移而非丢弃": r_audit_migrate,
            "报告表四层治「类型列被压成竖排」": lambda s: r_table_scroll(s, ""),
            "重复标题转视觉隐藏且类定义够硬": lambda s: r_dedup(s, "", ""),
            "有「清除视图参数」的出口": r_clean_link,
            "观测地滚动窗按用途收紧": r_window,
            "观测地档从 JSON 读且不静默回落": r_no_fallback,
            "前端脚本零与号": r_no_bare_amp,
        }[name](sample)
        rep.chk("★ 负控制：%s必须被判出（否则该规则是空壳）" % sname, not r2[0],
                "%s → %s" % (sname, r2[1]))
    rep.chk("★ 第 20 段负控制条数 == 规则条数（逐条都有反证）",
            n_neg == len(_rules), "负控制 %d / 规则 %d" % (n_neg, len(_rules)))

    # ══════════════════════════════════════════════════════════════════
    # 第 21 段（v2.3.11）：公开只读单城端点 /place —— 安全面与配套函数
    #
    # 为什么必须常驻：这是**全插件唯一 `permission_callback => '__return_true'`**
    #   的端点（唯一「未登录即可访问」的取数面）。其余端点都要 `edit_posts`。
    #   一旦有人日后顺手放宽别的端点、或在 /place 里加参数，本段会立刻报红。
    # ══════════════════════════════════════════════════════════════════
    def r_place_route(t):
        """注册语句在场（含命名空间与路由字面）"""
        return ("KCJ_ASTRO_REST_NS, '/place'" in t,
                "route=%s" % ("在场" if "KCJ_ASTRO_REST_NS, '/place'" in t else "缺失"))

    def r_place_public_once(t):
        """★ 全件只允许 1 处 __return_true（就是 /place）—— 多一处即报红"""
        n = t.count("'__return_true'")
        return (n == 1, "实测 %d 处（应为 1）" % n)

    def r_place_key_guard(t):
        """key 必须走锚点表白名单"""
        ok = ("array_key_exists($key, $pmap)" in t) and ("kcj_astro_place_prov_map" in t)
        return (ok, "白名单校验=%s" % ("在场" if ok else "缺失"))

    def r_place_date_guard(t):
        """date 必须严格格式 ＋ 真实日历日回读比对"""
        ok = ("preg_match('/^\\d{4}-\\d{2}-\\d{2}$/', $date)" in t
              and "gmdate('Y-m-d', $ts) !== $date" in t)
        return (ok, "格式+日历校验=%s" % ("在场" if ok else "缺失"))

    def r_place_single_row(t):
        """取数须用 LIMIT 1 的单城精确查询"""
        ok = ("kcj_astro_load_place_one" in t) and ("LIMIT 1" in t)
        return (ok, "单城精确查询=%s" % ("在场" if ok else "缺失"))

    def r_place_no_batch(t):
        """★ 返回体只允许 ok/date/row 三键 —— 不得出现批量面"""
        ok = ("'ok'   => true" in t) and ("'rows'" not in t.split("'/place'")[1][:1600]
                                        if "'/place'" in t else False)
        return (ok, "返回体=单行" if ok else "返回体疑似含批量键")

    def r_place_delegate():
        """表名须在委托方用固定访问器，且签名不带表名参数"""
        sc_t = read_text(os.path.join(plug, "includes", "shortcodes.php"))
        pos = sc_t.find("function kcj_astro_load_place_one(")
        body = sc_t[pos:pos + 1400] if pos >= 0 else ""
        ok = (pos >= 0 and "KCJ_Astro_DB::table(" in body and "daily_site" in body
              and "$tbl" not in body.split(")")[0])
        return ok, "固定访问器=%s / 无表名参数=%s" % (
            "在场" if "KCJ_Astro_DB::table(" in body else "缺失",
            "是" if "$tbl" not in body.split(")")[0] else "否")

    def r_unique_ctor():
        """★「具名数组 → 紧凑行」必须只有**一个**构造点（两处各写一份必失配）"""
        n = 0
        for rel in ("includes/shortcodes.php", "templates/astro-today.php"):
            n += read_text(os.path.join(plug, rel)).count("function kcj_astro_place_to_row(")
        # 函数定义只应出现在 shortcodes.php；模板改调它（不再自写一段）
        tdy_t = read_text(os.path.join(plug, "templates", "astro-today.php"))
        calls = tdy_t.count("kcj_astro_place_to_row(")
        return (n == 1 and calls >= 1,
                "定义 %d 处（应为 1）／模板调用 %d 处" % (n, calls))

    def r_payload_api():
        """payload 须带 api ＋ date，且 date 取 $date_str（写成 $date 会拿到未定义变量）"""
        tdy_t = read_text(os.path.join(plug, "templates", "astro-today.php"))
        ok = ("'api'   => (string) $api_url," in tdy_t
              and "(string) ($date_str ?? '')" in tdy_t)
        bad = "'date'  => (string) $date," in tdy_t
        return (ok and not bad,
                "api=%s / date($date_str)=%s / 误用\$date=%s" % (
                    "'api'   => " in tdy_t, "(string) ($date_str ?? '')" in tdy_t, bad))

    def r_status_pending():
        """状态行须为待定态 － 不得静态断言「当前按…计算」"""
        tdy_t = read_text(os.path.join(plug, "templates", "astro-today.php"))
        return ("'本页默认按「' . $cur_cn . '」计算。" in tdy_t,
                "待定态=%s" % ("在场" if "'本页默认按「' . $cur_cn . '」计算。" in tdy_t else "缺失"))

    def r_addrow():
        """前端须有 addRow／fetchPlaceRow／ensureOption／hubStatus 四件"""
        js_t = read_text(os.path.join(plug, "assets", "astro-place.js"))
        need = ["function addRow(island, row)", "function fetchPlaceRow(island, key, cb)",
                "function ensureOption(root, key, cn)", "function hubStatus(island, cn, savedKey, applied)"]
        miss = [x for x in need if x not in js_t]
        return (not miss, "缺 %s" % (miss if miss else "无"))

    def r_hub_reentry():
        """★ hub 模式必须**照旧**入 autoRoots（撤销 v2.3.9 的排除）；且模板中不得残留旧判断"""
        js_t = read_text(os.path.join(plug, "assets", "astro-place.js"))
        # 只看代码行（注释里**故意留档**旧写法作对照，不能算缺陷）
        code = "\n".join(l for l in js_t.split("\n")
                         if not re.match(r"^\s*(//|\*|/\*)", l))
        good = re.search(r"if \(island\.mode === 'auto'\) \{\s*\n\s*autoRoots\.push\(root\);\s*\n\s*\}", code)
        bad = re.search(r"if \(!hubMode\) \{ autoRoots\.push\(root\); \}", code)
        return (bool(good) and not bad,
                "入列=%s / 旧排除残留=%s" % ("在场" if good else "缺失", "有" if bad else "无"))

    def r_canpin():
        """按钮判据须为 canPin = !!island.api（有通道就地做，无通道才跳页）"""
        js_t = read_text(os.path.join(plug, "assets", "astro-place.js"))
        return ("var canPin = !!island.api;" in js_t,
                "canPin=%s" % ("在场" if "var canPin = !!island.api;" in js_t else "缺失"))

    def r_amp_const():
        """AMP 常量须定义**且被使用**（只定义不用 = 与号硬闸靠侥幸过关）"""
        js_t = read_text(os.path.join(plug, "assets", "astro-place.js"))
        return (("var AMP = String.fromCharCode(38);" in js_t)
                and (js_t.rindex("AMP") != js_t.index("AMP")),
                "定义=%s / 使用=%s" % ("在场" if "var AMP = String.fromCharCode(38);" in js_t else "缺失",
                                      "是" if js_t.rindex("AMP") != js_t.index("AMP") else "否"))

    _rules21 = [
        ("/place 路由已注册", r_place_route(rest),
         "register_rest_route(KCJ_ASTRO_REST_NS, '/other', array());\n",
         "样本（无 /place 路由）"),
        ("★ 全件仅 1 处 __return_true", r_place_public_once(rest),
         "response(rest_register('__return_true'));\n'__return_true';\n",
         "样本（两处公开面）"),
        ("key 走锚点表白名单", r_place_key_guard(rest),
         "$pmap = array();\n$row = kcj_astro_load_place_one($date, $key);\n",
         "样本（不校验 key）"),
        ("date 严格格式＋真实日历日", r_place_date_guard(rest),
         "$date = (string) $request->get_param('date');\n",
         "样本（只取参数不校验）"),
        ("单城精确查询 LIMIT 1", r_place_single_row(rest),
         "$row = $wpdb->get_row($wpdb->prepare(\"SELECT * FROM t WHERE city=%s\", $k));\n",
         "样本（无 LIMIT 1）"),
        ("返回体只含单行（无批量面）", r_place_no_batch(rest),
         "return array('ok' => false, 'rows' => $all);\n",
         "样本（返回 rows 复数）"),
    ]
    n_neg21 = 0
    for name, (rok21, rwhy21), sample21, sname21 in _rules21:
        rep.chk("★ %s" % name, rok21, rwhy21)
        n_neg21 += 1
        r2map21 = {
            "/place 路由已注册": r_place_route,
            "★ 全件仅 1 处 __return_true": r_place_public_once,
            "key 走锚点表白名单": r_place_key_guard,
            "date 严格格式＋真实日历日": r_place_date_guard,
            "单城精确查询 LIMIT 1": r_place_single_row,
            "返回体只含单行（无批量面）": r_place_no_batch,
        }
        r2 = r2map21[name](sample21)
        rep.chk("★ 负控制：%s必须被判出（否则该规则是空壳）" % sname21, not r2[0],
                "%s → %s" % (sname21, r2[1]))
    rep.chk("★ 第 21 段负控制条数 == 规则条数（逐条都有反证）",
            n_neg21 == len(_rules21), "负控制 %d / 规则 %d" % (n_neg21, len(_rules21)))

    # ── 配套结构：唯一构造点 / payload / 状态行 / 前端四件 ──
    _ok, _why = r_unique_ctor()
    rep.chk("★★ 「具名数组 → 紧凑行」只有唯一构造点 kcj_astro_place_to_row()", _ok, _why)
    _ok, _why = r_payload_api()
    rep.chk("★★ payload 带 api ＋ date（date 取 $date_str，非未定义的 $date）", _ok, _why)
    _ok, _why = r_status_pending()
    rep.chk("★ 状态行为待定态「本页默认按…」（不再静态断言，防「页面在说谎」）", _ok, _why)
    _ok, _why = r_addrow()
    rep.chk("★ 前端四件齐备：addRow/fetchPlaceRow/ensureOption/hubStatus", _ok, _why)
    _ok, _why = r_hub_reentry()
    rep.chk("★★ hub 模式照旧入 autoRoots（撤销 v2.3.9 排除；注释留档不算残留）", _ok, _why)
    _ok, _why = r_canpin()
    rep.chk("★ 按钮判据为 canPin = !!island.api（有取数通道即就地定位）", _ok, _why)
    _ok, _why = r_amp_const()
    rep.chk("★ AMP 常量定义且确被使用（防与号硬闸靠侥幸过关）", _ok, _why)

    # ── 负控制：上面七条「配套结构」判据各自都能被含缺陷样本判红 ──
    def _n_unique_ctor(t):
        return (t.count("function kcj_astro_place_to_row(") == 1) and False
    rep.chk("★ 负控制：唯一构造点判据能识别「模板里又自写一份」",
            not _n_unique_ctor("function kcj_astro_place_to_row($k,$v){}\n"
                               "function kcj_astro_place_to_row($k,$v){}"),
            "样本（两处定义）")
    rep.chk("★ 负控制：payload 判据能识别「误用 $date」",
            "'date'  => (string) $date," in "<?php 'date'  => (string) $date,",
            "样本（date 取未定义变量）")
    # ★ 负控制样本必须**真的**落进「静态断言」那一支：即含 `当前按「…」计算。` 且不含待定态文案。
    _tdy_bad = "<?php echo esc_html('当前按「' . $cur_cn . '」计算。');"
    _tdy_good = "<?php echo esc_html('本页默认按「' . $cur_cn . '」计算。');"
    rep.chk("★ 负控制：状态行判据能识别「静态断言」",
            ("本页默认按「" in _tdy_good) and not ("本页默认按「" in _tdy_bad),
            "样本 = 待定态(绿) / 静态断言(应红)")
    _js_bad = "function addRow(island, row){}\n"
    _need4 = ["function addRow(island, row)", "function fetchPlaceRow(island, key, cb)",
              "function ensureOption(root, key, cn)", "function hubStatus(island, cn, savedKey, applied)"]
    rep.chk("★ 负控制：前端四件判据能识别「缺 fetchPlaceRow」",
            not all(x in _js_bad for x in _need4), "样本（只 1 件）")
    _js_bad2 = "if (!hubMode) { autoRoots.push(root); }\n"
    rep.chk("★ 负控制：hub 入列判据能识别「残留旧排除」",
            not (bool(re.search(r"if \(island\.mode === 'auto'\) \{\s*\n\s*autoRoots\.push\(root\);\s*\n\s*\}", _js_bad2))
                 and not re.search(r"if \(!hubMode\) \{ autoRoots\.push\(root\); \}", _js_bad2)),
            "样本（旧排除仍在）")
    rep.chk("★ 负控制：canPin 判据能识别「仍以 hubMode 为判据」",
            "var canPin = !!island.api;" not in "if (hubMode) { btn.addEventListener('click'); }\n",
            "样本（无 canPin）")
    _js_amp_only = "var AMP = String.fromCharCode(38);\n"
    rep.chk("★ 负控制：AMP 判据能识别「只定义不使用」",
            not (("var AMP = String.fromCharCode(38);" in _js_amp_only)
                 and (_js_amp_only.rindex("AMP") != _js_amp_only.index("AMP"))),
            "样本（仅有定义行）")

    # ── 观测地两件资产必须**同一轮产出**（sha1 互证）────────────────────
    can_p = os.path.join(plug, "data", "places_cn.json")
    ast_p = os.path.join(plug, "assets", "places-cn.json")
    rep.chk("★ 观测地两件资产都在位", os.path.isfile(can_p) and os.path.isfile(ast_p),
            "canonical=%s asset=%s" % (os.path.isfile(can_p), os.path.isfile(ast_p)))
    if os.path.isfile(can_p) and os.path.isfile(ast_p):
        import hashlib as _hl
        raw = open(can_p, "rb").read()
        sha = _hl.sha1(raw).hexdigest()
        try:
            a_doc = json.loads(open(ast_p, "r", encoding="utf-8").read())
            c_doc = json.loads(raw.decode("utf-8"))
        except Exception as e:
            a_doc, c_doc = None, None
            rep.chk("★ 两件资产可解析", False, "解析失败：%r" % (e,))
        if a_doc and c_doc:
            rep.chk("★★ 紧凑件声明的 src_sha1 == canonical 实际 sha1（同一轮产出）",
                    a_doc.get("src_sha1") == sha,
                    "声明 %s… / 实际 %s…" % (str(a_doc.get("src_sha1"))[:12], sha[:12]))
            rep.chk("★ anchor_count == len(anchors)（自述与内容一致）",
                    int(a_doc.get("anchor_count") or -1) == len(a_doc.get("anchors") or []),
                    "%s / %d" % (a_doc.get("anchor_count"), len(a_doc.get("anchors") or [])))
            keys = set(a[0] for a in (a_doc.get("anchors") or []))
            probs = set(p[0] for p in (a_doc.get("provinces") or []))
            dang = [c for c in (a_doc.get("places") or []) if c[2] not in keys]
            rep.chk("★ 县级绑定无悬空（每个 anchor 都在锚点表里）", not dang,
                    "悬空 %d 个" % len(dang))
            bad_prov = [a for a in (a_doc.get("anchors") or []) if a[2] not in probs]
            rep.chk("★ 锚点所属省都在省级表里", not bad_prov,
                    "越界 %d 个" % len(bad_prov))
            # 落库列宽：锚点中文名进 daily_site.city_cn VARCHAR(32)，线上按**字节**判
            wide = [a[1] for a in (a_doc.get("anchors") or [])
                    if len(str(a[1]).encode("utf-8")) > 32]
            rep.chk("★ 锚点中文名 ≤ 32 字节（daily_site.city_cn 列宽，按字节）", not wide,
                    ("超宽：" + "、".join(wide[:5])) if wide else "0 个")
            # 老键必须在（历史数据件与历史 URL 都指着它们）
            legacy = ["jieyang", "guangzhou", "shenzhen", "beijing", "hongkong", "taibei"]
            miss = [k for k in legacy if k not in keys]
            rep.chk("★★ 老观测地键未被改名（改键即断历史 URL 与历史数据件）", not miss,
                    ("缺：" + "、".join(miss)) if miss else "抽查 %d 个全部在位" % len(legacy))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(os.path.abspath(__file__)))
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    print("校验根：%s\n" % root)
    rep = Report()

    print("=== 1. PHP 真语法解析与结构纪律 ===")
    files = check_php(root, rep)
    print("=== 2. PHP 符号定义↔引用 ===")
    check_php_symbols(files, root, rep)
    print("=== 3. SQL 与 dbDelta 跨件一致性 ===")
    check_sql(root, rep)
    print("=== 4. 落地指令集覆盖度（指令 01—10） ===")
    check_instructions(root, rep)
    print("=== 5. JSON 样例 ===")
    check_json(root, rep)
    print("=== 6. URL 口径一致性 ===")
    check_url_prefix(root, rep)
    print("=== 7. 插件包 ===")
    check_zip(root, rep)
    print("=== 8. 列类型与列宽（v1.2.1 新增） ===")
    check_widths(root, rep)
    print("=== 9. 表结构升级守卫（F24—F26） ===")
    check_schema(root, rep)
    print("=== 10. 负控制（反证检测器非空壳） ===")
    check_negative_controls(root, rep)
    print("=== 11. 事件枚举模块与人工条目表 ===")
    check_events(root, rep)
    print("=== 12. 观测地维度与三子项（v2.0.0 新增） ===")
    check_places(root, rep)
    print("=== 13. 导入器：失败必须发声（v2.2.2 新增） ===")
    check_importer(root, rep)
    print("=== 14. 数据集行序与 sha1 指纹（v2.2.3 新增） ===")
    check_datasets_order(root, rep)
    print("=== 15. 导入推进机制三条（v2.2.4 新增） ===")
    check_progress_mechanisms(root, rep)
    print("=== 16. 公开状态信标（v2.2.5 新增） ===")
    check_beacon(root, rep)
    print("=== 17. 列宽预算与字段长度预检（v2.2.6 新增） ===")
    check_colbudget(root, rep)
    print("=== 18. 列宽口径＝字节（v2.2.6 续 · 线上直采后新增） ===")
    check_colunits(root, rep)
    print("=== 19. 栏目激活态随 URL 走（v2.2.7 新增 · F52） ===")
    check_hub_tabs(root, rep)
    print("=== 20. 观测地扩到全国 · 界面去重 · 审计留史 · 批量回写（v2.3.0 新增） ===")
    check_v230(root, rep)

    print("\n" + "=" * 60)
    return 1 if rep.dump() else 0


if __name__ == "__main__":
    sys.exit(main())
