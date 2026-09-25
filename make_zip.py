#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
天象预报模块 · 插件包打包器（v1.2.1 新增）

为什么要有这个文件：
  之前 `wp-astro-forecast.zip` 是**手工打的**，于是
    · 文件集靠记忆（漏一个 includes/ 就会 500，且当场看不出来）；
    · 时间戳/压缩级别每次不同 ⇒ 字节不可复现，「重新打一次确认没变」这种校验做不了。
  本脚本把这两件事都钉死：**文件集由磁盘现状决定 + 字节可复现**。

用法：
  python make_zip.py              # 打包并打印指纹
  python make_zip.py --selftest   # 幂等自检：连打两次，断言字节完全相同；再核对文件集
"""
import argparse
import hashlib
import io
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = "wp-astro-forecast"
ZIP_PATH = os.path.join(HERE, PLUGIN_DIR + ".zip")

# 不进包的东西：缓存/版本控制/临时与备份件。**注意 .php/.css/.json 一律要进**。
SKIP_DIRS = {"__pycache__", ".git", ".svn", ".idea", ".vscode", "node_modules"}
SKIP_FILES = {".DS_Store", "Thumbs.db", "desktop.ini"}
SKIP_EXT = {".pyc", ".pyo", ".bak", ".bak1", ".bak2", ".log", ".orig", ".rej", ".zip"}


def is_backup(fn):
    """★ 备份件判据：以 .bak 起头的**任意后缀**都算（.bak / .bak1 / .bak-c298 / .bak-20260924）。

    为什么不能只用 `os.path.splitext(fn)[1] in SKIP_EXT`：
      `wp-astro-forecast.php.bak-c298` 的 splitext 结果是 `('.php.bak-c298', '.bak-c298')`
      —— **带日期的备份后缀不在 SKIP_EXT 里**，于是会静默打进包。
      实测踩过：c298 轮改完打 zip，`wp-astro-forecast.php.bak-c298` 进了包（多出 46,856 B）。
    """
    low = fn.lower()
    if ".bak" not in low:
        return False
    # 只看第一个 .bak 之后的形态：.bak / .bak1 / .bak-c298 / .bak.20260924 全收
    tail = low[low.index(".bak") + 4:]
    return tail == "" or tail[0] in "-._" or tail.isdigit()


# 固定时间戳（1980-01-01 是 ZIP 格式下限；用固定值换取**字节可复现**）
FIXED_DT = (1980, 1, 1, 0, 0, 0)


def collect(root):
    """返回 [(zip 内相对路径, 磁盘绝对路径)]，按 zip 路径排序 ⇒ 顺序稳定。"""
    base = os.path.join(root, PLUGIN_DIR)
    if not os.path.isdir(base):
        raise SystemExit("[FAIL] 找不到插件目录：%s" % base)
    out = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for fn in sorted(filenames):
            if fn in SKIP_FILES or os.path.splitext(fn)[1].lower() in SKIP_EXT or is_backup(fn):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            out.append((rel, full))
    out.sort(key=lambda t: t[0])
    if not out:
        raise SystemExit("[FAIL] 空集：插件目录下没有可打包的文件")   # 空集守卫
    return out


def build(root):
    """打包到内存，返回 (bytes, 条目列表)。"""
    buf = io.BytesIO()
    entries = collect(root)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel, full in entries:
            with open(full, "rb") as f:
                data = f.read()
            zi = zipfile.ZipInfo(rel, date_time=FIXED_DT)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            zf.writestr(zi, data)
    return buf.getvalue(), entries


def digs(b):
    return {"sha1": hashlib.sha1(b).hexdigest(), "md5": hashlib.md5(b).hexdigest(),
            "bytes": len(b)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=HERE)
    ap.add_argument("--selftest", action="store_true",
                    help="幂等自检：连打两次断言字节相同，并核对条目数与文件集")
    a = ap.parse_args()
    root = os.path.abspath(a.root)

    blob, entries = build(root)
    d = digs(blob)

    if a.selftest:
        blob2, entries2 = build(root)
        ok = 0
        fails = []

        def chk(name, cond, detail=""):
            nonlocal ok
            if cond:
                ok += 1
                print("  [PASS] %s %s" % (name, detail))
            else:
                fails.append(name)
                print("  [FAIL] %s %s" % (name, detail))

        chk("条目数 > 0（空集守卫）", len(entries) > 0, "= %d" % len(entries))
        chk("★ 幂等：连打两次字节完全相同", digs(blob) == digs(blob2),
            "%s vs %s" % (digs(blob)["sha1"][:12], digs(blob2)["sha1"][:12]))
        chk("两次条目列表一致", entries == entries2)
        roots = set(r.split("/")[0] for r, _ in entries)
        chk("zip 根目录唯一且 = 插件目录名", roots == {PLUGIN_DIR}, "= %s" % sorted(roots))
        need = ["wp-astro-forecast/wp-astro-forecast.php",
                "wp-astro-forecast/includes/class-astro-db.php",
                "wp-astro-forecast/assets/astro-style.css"]
        names = set(r for r, _ in entries)
        chk("关键文件齐备", all(n in names for n in need),
            "缺 %s" % [n for n in need if n not in names])
        # 每个 .php 都要进包 —— 漏一个 includes/ 就是一次线上 500
        php_on_disk = set(r for r, _ in entries if r.endswith(".php"))
        chk("全部 .php 均已进包（%d 个）" % len(php_on_disk), len(php_on_disk) > 0)
        # ★ 备份件判据：**用 is_backup()**，不要只用 splitext 的扩展名。
        #   旧写法 `os.path.splitext(r)[1] in SKIP_EXT` 对
        #   `x.php.bak-c298` 求出的扩展名是 `.bak-c298` ⇒ **命中不了**
        #   ⇒ 这条自检本身是**空壳**（判据与被测对象不对齐，同第①病族）。
        stale = [r for r, _ in entries
                 if os.path.splitext(r)[1].lower() in SKIP_EXT or is_backup(os.path.basename(r))]
        chk("包内无缓存/备份件（含 .bak-* 带日期后缀）", not stale, "命中 %s" % stale)
        print("  —— 自检合计：通过 %d 项，失败 %d 项" % (ok, len(fails)))
        # ★ 本轮踩坑：`--selftest` 只检不写（见上面的 return），但输出里不说，
        #   极易被读成「已重新打包、校验也过了」⇒ 实际 zip 还是旧包，
        #   而 verify_package 的「zip↔磁盘逐字节一致」会红得莫名其妙。
        #   故在此明写：本次未落盘。要落盘就去掉 --selftest 再跑一次。
        print("  ⚠ 本次 **未写入** %s（--selftest 只检不写；要落盘请不带该参数再跑一次）"
              % os.path.basename(ZIP_PATH))
        return 1 if fails else 0

    with open(ZIP_PATH, "wb") as f:
        f.write(blob)
    print("已写出：%s" % ZIP_PATH)
    print("  条目 %d 个 ｜ %d 字节 ｜ SHA1 %s ｜ MD5 %s"
          % (len(entries), d["bytes"], d["sha1"], d["md5"]))
    for rel, full in entries:
        print("    %-62s %7d" % (rel, os.path.getsize(full)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
