# NOTICE · 第三方材料与例外

本仓库的许可分三层，逐层写明。**本文件是唯一讲例外的地方** ——
`LICENSE`（MIT）与 `LICENSE-DATA`（CC BY 4.0）保持为标准文本、不夹带任何例外条款，
以便机器（GitHub 许可识别、SPDX 工具、引用管理器）能直接读出主许可。

## 一 三层许可

| 层 | 范围 | 许可 | 正本 |
|:---|:---|:---|:---|
| 代码 | `python/`、`sql/`、根目录下的 `.py` 脚本 | MIT | [`LICENSE`](LICENSE) |
| 数据与文档 | `data/`、`samples/`、`docs/`、`README*.md`、插件内 `wp-astro-forecast/data/` | CC BY 4.0 | [`LICENSE-DATA`](LICENSE-DATA) |
| WordPress 插件目录 | `wp-astro-forecast/` | 文件头声明 `GPL-2.0-or-later` | 本文件 §二 |

## 二 关于插件目录的 `GPL-2.0-or-later`

`wp-astro-forecast/` 下每个 PHP 文件的软件头都写着 `License: GPL-2.0-or-later`。
这是 **WordPress 生态的惯例写法**（官方插件目录要求插件为 GPL 兼容许可），
而不是对本仓库其余部分的声明。两者的关系是：

- **本仓库整体以 MIT 释出**（含该插件代码）；
- 该插件目录额外标上 `GPL-2.0-or-later`，供希望按 WordPress 惯例取用的人使用；
- MIT 与 GPLv2+ 兼容 —— 接收方可以把本插件置于 GPLv2+ 之下再分发。

若你只想按一个许可取用，**按 MIT 用即可**。

## 三 不在仓库内的第三方材料

- **`de421.bsp`（JPL 行星历表）** 不在本仓库内分发，
  首次运行由 Skyfield 联网下载，其权利属 JPL / NASA，遵循其自身条款。
- **观测地清单（`places_cn.json`）** 由公开行政区划数据整理而成；
  本仓库对其整理结果适用 CC BY 4.0，不主张对原始行政区划信息本身的权利。
- **天文算法与物理常数** 属公有领域知识，不受本许可约束。
- 本仓库**不包含**任何第三方历表的复制件 —— 计算一律由本仓库代码现场产生。

## 四 引用

引用请用 Zenodo concept DOI：<https://doi.org/10.5281/zenodo.22950007>。
