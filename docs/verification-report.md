# 校验报告 · 天象预报模块 v1.2.1

校验时点：**2026-09-23** ｜ 校验人：本轮实施
校验环境：Windows ／ Python 托管 venv（`C:/Users/chirc/.workbuddy/binaries/python/envs/skills/Scripts/python.exe`）／
skyfield **1.55** + skyfield_data **7.0.0**（内置 `de421.bsp`，**离线可跑**）／ **本机无 PHP runtime**
判据原则：**凡能与权威实现对拍的，一律现场对拍**；不拿记忆里的常数当判据。

---

## 一、结论（先看这个）

| 校验面 | 命令 | 结果 |
|---|---|---|
| 计算内核 + 端到端 | `python/compute_sky.py --selftest` | **通过 31 项，失败 0 项，exit=0** |
| 事件枚举（自检） | `python/event_almanac.py --selftest` | **通过 227 项，失败 0 项，exit=0** |
| 事件枚举（对拍权威值） | `python/event_almanac.py --verify` | **通过 57 / 57 项，exit=0** |
| 交付件静态校验 | `verify_package.py` | **通过 213 项，失败 0 项，exit=0** |
| 数据集契约 | `python/build_dataset.py --selftest` | **通过 51 项，失败 0 项，exit=0** |
| 合计 | — | **579 项断言全绿**（31 ＋ 227 ＋ 57 ＋ 213 ＋ 51），无失败项 |

与上一轮（v1.2.0／v1.2.1）对照：

| 校验面 | v1.1.0 | v1.2.0 | v1.2.1 | 本轮（事件枚举） |
|---|---|---|---|---|
| `compute_sky.py --selftest` | 27 项 | **31 项** | 31 项 | 31 项 |
| `event_almanac.py --selftest` | — | — | — | **227 项**（新增） |
| `event_almanac.py --verify` | — | — | — | **57 项**（新增） |
| `verify_package.py` | 67 项 | **150 → 165 → 178 项** | 178 项 | **213 项**（本轮补 35 项，见 §十） |
| `build_dataset.py --selftest` | 未设 | **14 → 16 项** | 16 项 | **51 项**（本轮补 35 项：事件集契约、空集守卫、人工条目表、发布窗口） |

复验命令（原样可复制）：

```bash
export PATH="/usr/bin:/bin:/mingw64/bin:$PATH"
PY="C:/Users/chirc/.workbuddy/binaries/python/envs/skills/Scripts/python.exe"
cd "D:/OneDrive/文档/Obsidian Vault/公众号/05-工具/astro/astro-forecast"

"$PY" python/compute_sky.py --selftest
"$PY" verify_package.py
"$PY" python/build_dataset.py --selftest
"$PY" python/event_almanac.py --selftest      # 约 1m45s
"$PY" python/event_almanac.py --verify         # 约 1m
```

---

## 二、`compute_sky.py --selftest`（31 项）

### 2.1 覆盖面（十类）

| 类别 | 覆盖内容 |
|---|---|
| ΔT 模型 | 现代值、1900 年负值、公元前大正值 |
| Meeus 教材算例 | Ex47.a 月球黄经/黄纬、Ex25.b 太阳视黄经 |
| 宿度 | 近似表与精算表均覆盖 28/28、段宽合计 ≈360° |
| 升落与晨昏 | 太阳/月亮升落非空、民用晨昏非空 |
| 全流水线 | 日宿/月宿/五星齐备 |
| 越界降级 | 自动降级不崩、`--no-analytic` 时抛 `OutOfRange` |
| 历史回推 | 可跑、给区间而非唯一时刻、覆盖内走精算 |
| **UT↔TT 尺度** | **本轮新增 2 项（F17）** |
| **古籍引用与纪年** | **本轮新增 2 项（F18）** |
| 合规与溯源 | 无择日类字段、输出含 `method` / `ephemeris` |

### 2.2 本轮新增的 4 项（实测）

| 断言 | 实测值 |
|---|---|
| F17 历史回推已做 UT→TT 折算 | `jd_tt − jd_ut = 0.239454 天`（ΔT ≈ 20689 s，应等于 0.239454） |
| F17 尺度字段自述（`jd_scale`） | `jd_scale = TT (JDE)` |
| F18 示例史事只引古籍正本（不引近现代注本） | `《春秋》[M]. 先秦.` |
| F18 纪年解析与示例常量一致（防再次漂移） | `parse_era_year('720BC') = -719`，显示「公元前 720 年」 |

### 2.3 关键对拍值

| 对拍项 | 实测 |
|---|---|
| 解析式 vs DE421（2026 年样本）太阳黄经差 | **0.0025°** |
| 解析式 vs DE421（2026 年样本）月球黄经差 | **0.0019°** |
| 解析式 vs DE421（2026 年样本）月球黄纬差 | **0.0026°** |
| 解析月相 vs skyfield（2026 年 25 个朔望） | **最大偏差 0.13 min** |
| 历史回推（覆盖内） | `method = ephemeris_de421` |
| 历史回推（覆盖外） | `method = analytic_meeus`，给区间不崩 |

> 尺度修正后的历史回推判据（实算）：公元前 720 年 2 月 22 日 **日月黄经差 2.101°、月球黄纬 0.269°** ⇒ 满足日食几何，
> 与《春秋》隐公三年「春王二月己巳，日有食之」相符；最近朔 **720BC-02-22 08:28**，不确定度区间 **06:28 ~ 10:28**。

---

## 三、`verify_package.py`（213 项）

### 3.1 PHP：由「括号配平」升级为真语法解析

| 断言 | 结果 |
|---|---|
| PHP 真语法解析可用（tree-sitter-php） | 通过 |
| PHP 语法正确（AST 无 `ERROR` 节点） | 通过 |
| 括号配平（已剥离字符串/注释，作为辅助判据） | 全部平衡 |
| 无 BOM / 纯 LF | 通过 |
| `includes/` 与 `templates/` 均有 `ABSPATH` 守卫 | 通过 |
| 无危险函数（`eval` / `exec` / `system` / …） | 无命中 |
| **符号定义↔引用双向核对** | 已定义 54 个 `kcj_*` 函数；**无未定义调用、无死函数** |

### 3.2 SQL 与跨件一致性

| 断言 | 结果 |
|---|---|
| 三表齐备且各有 `ENGINE=InnoDB DEFAULT CHARSET=utf8mb4` | 通过 |
| **列集一致（`install_tables.sql` ↔ `class-astro-db.php` dbDelta）** | 三表逐列相同（daily 为 9 列） |
| 唯一键齐备（`uk_jd` / `uk_date_str` / `uk_slug` / `uk_from_to_rel`） | 通过 |
| 含溯源列 `method` / `ephemeris` | 通过 |
| jd 列注释为 **TT 尺度** | 通过 |

> 跨件列集对拍的意义：交付件 A（SQL）与插件内 dbDelta 是**两份手写 SQL**，极易漂移（改一处忘另一处 →
> 线上建表缺列、短代码查列报错）。此判据把这类漂移变成机器可查。

### 3.3 JSON 样例（全部由真实计算生成）

| 断言 | 实测 |
|---|---|
| 历史样例给区间（`earliest < latest`） | `720BC-02-22 06:28 ~ 720BC-02-22 10:28` |
| 纪年口径 | `720BC` → `era_year=-719`，显示「公元前 720 年」 |
| **历史样例已做 UT→TT 折算（F17）** | `jd_tt − jd_ut = 0.239454 天`，ΔT = 20688.84 s |
| **历史样例只引古籍正本（不引近现代注本）** | `《春秋》[M]. 先秦.` |
| **未来样例 `jd_core` 为 TT 尺度（F17）** | `jd_scale = TT (JDE)` |
| 历史样例含 `nearest_phases` | 4 条 |
| 未来样例含 `event_type` / `method` / `ephemeris` / `publish_status` | 通过 |

### 3.4 插件包

| 断言 | 结果 |
|---|---|
| zip 条目数 ≥ 12 | **20** |
| zip 根目录唯一且 == 插件目录名 | `wp-astro-forecast` |
| zip 内含全部必需文件（17 项） | 缺：无 |
| 不含已废弃的 `assets/astro.css` | 命中：无 |
| 体积 | 约 **57 KB** |

### 3.5 指令覆盖度与 URL 口径（本轮新增）

| 断言 | 结果 |
|---|---|
| 指令 01—10 覆盖度逐条对拍 | 通过（10/10 有落点） |
| URL 前缀一致性：扫描到文件 > 0（空集守卫） | 38 个 |
| 无残留旧前缀 `/sky/forecast/`（**行级判据**：不交代遗留即报红） | 命中：无 |
| 301 跳转已实现（旧 → 新） | 通过 |
| 列表模板不再硬编码 URL（改走 permalink 助手） | 通过 |

### 3.6 负控制（反证校验器非空壳，4 → 23 → **30** 项）

任何校验器最大的风险不是漏判，而是**系统性恒真**。本节用注入法逐条反证：

| 负控制 | 手段 | 结果 |
|---|---|---|
| ① SQL 列集漂移可被检出 | 往 daily 表注入一列 | 原 9 列 → 检出 10 列 |
| ② PHP 括号失衡可被检出 | 注入 `{` 不闭合 | 检出 `{2}/{1}` |
| ③ 字符串内括号已被剔除 | `f('{'); g(')');` | 剥离后 = `'f(); g();'` |
| ④ 合规禁用字段可被检出 | 往样例注入择日类字段 | 检出 |
| ⑤ **PHP 真语法错可被 AST 检出** | 注入真语法错 | 检出 `[(2, ')')]` |
| ⑥ **未定义 `kcj_*` 调用可被检出** | 探针函数名 | `kcj_astro_zzz_undefined_probe` 不在 54 个已定义函数中 |
| ⑦ 旧 URL 前缀豁免白名单不空 | 校验白名单本身 | 通过 |
| ⑧ **真·残留旧前缀会被抓（判据非恒假）** | 喂 `详情页：/sky/forecast/{slug}/` | 命中第 1、2 行 |
| ⑨ **交代了「旧」的记述不误报（判据非恒真）** | 喂「旧前缀 X → Y 加 301」 | 误报 0 行 |

---

## 四、`build_dataset.py`

### 4.1 `--selftest`（51 项，通过 51 / 失败 0 / exit=0；v1.2.1 为 16 项）

临时目录**真跑一遍完整构建**（3 天日记录 + 全年四类事件），校验两侧契约。自测产物写在系统临时目录，不污染仓库。

**日记录侧（原 16 项）**：每行可被 `json.loads`、键集 ⊆ REST `daily` 白名单、`jd` 单调递增、
`date_str` 与 `jd` 互相对应、`date_str` 逐日连续、`data_json` 内层与外壳字段一致、
构建期 `_clip` 从未触发、daily 文本列均已登记列宽。

**事件侧（本轮新增 35 项）**

| 组 | 判据 |
|---|---|
| 非空 | **未来事件必须非空** —— ★ 此前的三项「字段合规」判据在空列表上 `all()` 恒真，一直**假通过**（空集假通过的典型脸） |
| 契约 | 键集 ⊆ REST `events` 白名单、不发 `event_id`/`post_id`、必填键非 None、**slug 全局唯一**（否则 REST 静默覆盖）、`jd_core` 升序 |
| 时刻 | `event_time_bj` ↔ `jd_core` 自洽，**用本文件自己的 Meeus 算式＋固定 TT−UTC 常数**（不复用生成侧任何函数，避免判据恒真）；`|Δ| ≤ 2 s` |
| 跨字段 | slug 末尾 `YYYYMMDD` == `event_time_bj` 的北京日期（两者走**不同**格式化路径，改其一即漂移）|
| 类型 | `event_type` 全落在**现场解析 `cpt.php`** 得到的 6 个规范值内（不写死副本） |
| 明文 | 显示字段无 `**` |
| 发布窗口 | 不限时不剔；生效时「保留 + 剔除 = 总数」；保留行确无早于 cutoff 者；两向负控制 |
| 空集守卫 | 0 条未放行必抛错 + **端到端**验证「抛错且不落文件」（打桩 `ea.build_events` 返回 0 条） |
| 人工条目表 | 行数 == 条目数；发布规则**双向**（`verified ∧ publish_status=1 ⇔ 行 =1`）；**五向负控制**（缺 slug／kind 非法／historical 缺 source_ref／catalog 缺 jd_core／slug 重复）+ **一个正控制**（仓内真表必须通过，否则判据是「一律报错」）|
| manifest | 计数与文件一致、状态不再是旧口径、记录了枚举器与逐类计数、如实记录发布窗口 |

### 4.2 `--limit 3 --dry-run`（真跑）

| 项 | 结果 |
|---|---|
| 日记录行数 | 3 行 |
| 精算 / 降级 / 失败 | **3 / 0 / 0** |
| 用时 | **2.40 s**（4 进程） |

> 读法：3 天时**进程池启动开销主导**，**不能**用 2.40 s ÷ 3 折算日速率。日速率以 §5 的稳态值为准。

---

## 五、星历覆盖与预计算面

| 项 | 值 |
|---|---|
| 星历 | `de421.bsp` |
| 覆盖 | **1899-07-28 — 2053-10-08** |
| 稳态性能 | 约 **0.25 s/日**（单核） |

| 方案 | 天数 | 单核 | 4 进程 |
|---|---|---|---|
| **承诺档 1900-01-01 — 2050-12-31** | ≈5.5 万 | ≈3.9 h | **≈1 h** |
| 星历全覆盖 1899-07-29 — 2053-10-08 | ≈5.6 万 | ≈3.95 h | ≈1 h |
| 5000 年全量（原 v1.0.0 声称） | ≈182 万 | **≈128 CPU·小时（不可行，已废）** | — |

---

## 六、本轮新增的校验能力

| 新增能力 | 说明 | 解决了什么 |
|---|---|---|
| **tree-sitter-php 真语法解析** | 用 PHP 语法树解析每个 PHP 文件，读 AST 的 `has_error` 并定位 `ERROR` 节点到行 | 取代原先只能「数括号」的粗判，能抓出真语法错误（负控制⑤反证） |
| **PHP 符号定义↔引用双向核对** | 收集全部 `kcj_*` 函数定义（本机 54 个），再核对调用处 | 抓「未定义调用」（必然 fatal）与「死函数」（维护债务）（负控制⑥反证） |
| **指令 01—10 覆盖度对拍** | 逐条指令核对代码/文档落点 | 防止「指令说了但没做」被漏过 |
| **URL 口径一致性检查** | 全仓扫描旧前缀残留 + 301 实现 + 模板硬编码 URL | 防旧 URL 死链与口径回退 |
| **负控制 4 → 9 项** | 新增 ⑤AST 真语法错 ⑥未定义调用 ⑦旧前缀豁免白名单 ⑧真残留必被抓 ⑨记述变更不误报 | 让「校验器恒真」这一最危险的假绿更难得逞；⑧⑨ 成对，确保行级判据**既非恒假也非恒真** |
| **负控制 9 → 15 项** | 新增 ⑩列宽过窄必被抓 ⑪列宽充足不误报 ⑫ENUM vs VARCHAR 分岔必被抓 ⑬类型一致不误报 ⑭zip 字节差异必被抓 ⑮一致时不误报 | 每个新判据都配**两向**负控制：既证「缺陷必被抓」，也证「修好了不误报」 |
| **负控制 15 → 23 项**（F24—F26） | 新增 ⑯列宽达标不算缺口 ⑰过窄/读不到必列为缺口 ⑱同一 option 两处语义必被抓 ⑲语义一致不误报 ⑳`$failed++` 无原因必被抓 ㉑有原因不误报 ㉒注释里的旧写法不误报 ㉓同行写在代码里必被抓 | ⑯⑰ 直接锁住「PHP 侧第一版把达标也写成缺口」那个错；㉒㉓ 成对，防**自指陷阱**（判据被自己的说明文字绊倒） |

### 6.1 边界声明：tree-sitter **不等于** PHP 解释器

**必须如实说明**，否则会给人「PHP 已通过解释器校验」的错觉：

| 不做的事 | 后果 |
|---|---|
| 不解析 `include` / `require` 图 | 跨文件依赖错误抓不到 |
| 不做类型检查 | 传参类型错、方法不存在等运行期问题抓不到 |
| 不跑运行时 | 钩子时序、`dbDelta` 实际行为、REST 鉴权等**一律未验** |
| 不执行任何 WordPress 代码 | 无法证明「激活不白屏」 |

**结论**：tree-sitter 只能证明**语法**正确。**「首次线上激活仍需人工盯一次 500」这条不因它而取消。**

---

## 七、本轮修掉的缺陷（复验对应关系）

详见 `docs/feasibility-review.md` 的 F17—F21 一节（含量化表与四段式记录）。摘要：

| 编号 | 缺陷 | 复验依据 |
|---|---|---|
| F17 | 解析降级与历史回推把 **UT 儒略日当 TT** 用，漏 ΔT 改正 | selftest 新增 2 项折算断言；verify 3.3 两项尺度对拍 |
| F18 | 同一史事两份日期互相矛盾；引了近现代注本 | selftest 新增 2 项（古籍正本、纪年一致性）；verify 3.3 古籍正本对拍 |
| F19 | `identify_special_events()` 的 `city` 是死参数 | 符号核对无未定义调用；自检全绿 |
| F20 | `register_post_type()` 写在激活钩子里 ⇒ 详情页/归档页**必然 404** | 校验器「指令 04 覆盖度」对拍；**线上渲染未验** |
| F21 | 指令 06 要求模板放主题目录，但本站在 WP.com 主题目录不可写 | verify 3.5 URL 与 301 对拍；模板内置已核 |
| 幂等 1 | `wp_astro_daily` 只有 `jd` 唯一键 ⇒ 同日重导插重复行 | 新增 `uk_date_str`；verify 3.2 唯一键核对 |
| 幂等 2 | `wp_astro_relations` 无唯一键 ⇒ 无限追加 | 新增 `uk_from_to_rel`；verify 3.2 唯一键核对 |
| 幂等 3 | REST 导入用 `$wpdb->last_error === ''` 判成功 | 改为判返回值 |

---

## 八、本轮**未能**校验的部分（如实声明）

| # | 未覆盖项 | 原因 | 风险与建议 |
|---|---|---|---|
| 1 | **PHP 运行时行为** | 本机无 PHP runtime；tree-sitter 只证明语法 | 线上首次激活若报 500，先停用插件再比对新旧 dbDelta 片段 |
| 2 | **REST 端点真机联通** | 需真实 WordPress + 应用程序密码 | 首次使用先调 `GET /wp-json/kcj-astro/v1/health` |
| 3 | **dbDelta 在 WP.com 的实际行为** | 同上 | 失败回退：手动执行 `sql/install_tables.sql` |
| 4 | **Schema 富媒体测试** | 需线上页面 + Google/百度工具 | 配置已就绪，待线上测 |
| 5 | **线上渲染与短代码** | 同上 | 待线上验 |
| 6 | **食分模块** | 需月交点几何，属独立模块 | 本轮只给「必要条件」判定（\|β\|<1.5°） |
| 7 | **历史事件条目内容** | 需人工逐条核对文献原文与出处 | 脚本已能算，内容工程另计 |

> 本报告不含「大概」「应该」类措辞：能测的都给了实测值，测不了的都列在 §8。

---

## 九、线上安装后实测（2026-09-23，**未经鉴权的可复现证据**）

插件已由用户在后台上传启用。以下结论全部来自**未登录**请求，任何人可复跑核对。

| 校验点 | 方法（未鉴权） | 实测结果 | 判定 |
|---|---|---|---|
| 插件已激活 | `GET /wp-json/kcj-astro/v1` | 返回命名空间路由清单（含 `routes`） | ✅ 已注册 |
| ↑ **对照**（排除假阳） | `GET /wp-json/kcj-astro-nope/v1/health` | **404** `rest_no_route` | ✅ 证明上条非「任何路径都给 401」 |
| REST 端点鉴权生效 | `GET /wp-json/kcj-astro/v1/health`（**无凭据**） | **401** `rest_forbidden`（**不是 404**） | ✅ 路由在、`edit_posts` 在拦 |
| **★ 三张自建表建成** | 同端点**带应用程序密码** | **200**，`ok:true`，三表均 `exists:true`、`rows:0` | ✅ **已验通** |
| CPT `astro_event` | `GET /wp-json/wp/v2/types?cb=<ts>` | 含 `"slug":"astro_event"` | ✅ 已注册 |
| CPT REST 基名 | `GET /wp-json/wp/v2/astro_event` | **200** | ✅ |
| 分类法 `event_type` | `GET /wp-json/wp/v2/taxonomies?cb=<ts>` | 含 `"slug":"event_type"` | ✅ 已注册 |
| **归档页不再 404（F20 线上生效）** | `GET /sky-forecast/` | **200**，56,504 B | ✅ |
| **旧 URL 301（F21 线上生效）** | `HEAD /sky/forecast/` | **301 Moved Permanently** → `Location: https://kuangchujia.com/sky-forecast/` | ✅ |
| 模板真的在用我们的 | 归档页 HTML 类名 | `kcj-astro-archive` / `kcj-astro-tabs` / `kcj-astro-breadcrumb` / `kcj-astro-nodata` / `kcj-astro-wrap` | ✅ `template_include` 生效 |
| 归档页标题 | 归档页 `<h1>` | `<h1>天象预告</h1>` | ✅ |
| 空态文案 | 归档页 HTML | 「该类型暂无已发布事件。」 | ✅ 符合预期（尚无事件数据） |
| 样式可加载 | `GET /wp-content/plugins/wp-astro-forecast/assets/astro-style.css` | **200**，且归档页已 enqueue（带 `?m=` 版本串） | ✅ |
| 无致命错误 | 归档页全文 | 无 `fatal error` / `critical error` | ✅ |

### 9.1 ★ 三张自建表 —— **已验证通过**（2026-09-23 01:10）

```json
{"ok": true, "plugin": "1.2.0", "rest_ns": "kcj-astro/v1", "url_infix": "sky-forecast",
 "tables": {
   "daily":     {"table": "wp_astro_daily",     "exists": true, "rows": 0},
   "events":    {"table": "wp_astro_events",    "exists": true, "rows": 0},
   "relations": {"table": "wp_astro_relations", "exists": true, "rows": 0}},
 "freshness": {"latest_date_str": null, "lag_days": null,
                "state": "empty", "checked_at": "2026-09-23 01:10:14"}}
```

**判定：三表齐备、`rows: 0`（该时点尚未导入数据）；插件版本 `1.2.0` 确认。**

### 9.1.1 ★ 推送 1 行数据 —— **v1.2.0 失败；用 A/B/C 边界实验把根因钉死**

`build_dataset.py --start 2026-09-23 --end 2026-09-23 --daily-only --push` 报
`[push_rest] daily 第 1/1 批：写入 0 行（累计 0/1）`。客户端**只读回执的 `written`**，
把 `failed` 与 `errors[]` 丢了，所以界面上只有「写入 0 行」，看不出原因。
手动 POST 同一 payload 才拿到完整回执：

```json
{"ok":true,"table":"daily","received":1,"written":0,"failed":1,
 "errors":["WordPress 数据库错误：处理以下字段的值失败：data_version。提供的值可能太长或包含无效数据。"],
 "cache_flushed":true}
```

**为确认「就是列宽」而不是别的原因，在线上做了一组只变 `data_version` 长度的对照实验**
（其余字段、日期、鉴权、端点全同；`date_str` 有唯一键 ⇒ 每次都是幂等 UPDATE，不留垃圾行）：

| 探针 | `data_version` 长度 | 内容 | HTTP | 回执 |
|---|---|---|---|---|
| A | **36** | `de421+dt_espenak_meeus_2006+tt_scale`（v1.2.0 真值） | 200 | `written:0, failed:1` |
| B | **32** | 同串截到 32 字符 | 200 | **`written:1, failed:0`** |
| C | **34** | 同串截到 33 字符 ＋ 补 `X` | 200 | `written:0, failed:1` |

**裁定：列宽恰为 32 —— ≤32 进、≥33 拒。诊断成立，且这不是推断，是线上对照实验。**

### 9.1.2 探针 B 写入后，读路径全线贯通（2026-09-23 01:17）

```json
{"ok":true,"plugin":"1.2.0","rest_ns":"kcj-astro/v1","url_infix":"sky-forecast",
 "tables":{"daily":{"table":"wp_astro_daily","exists":true,"rows":1},
            "events":{"table":"wp_astro_events","exists":true,"rows":0},
            "relations":{"table":"wp_astro_relations","exists":true,"rows":0}},
 "freshness":{"latest_date_str":"2026-09-23","lag_days":0,"state":"fresh",
               "checked_at":"2026-09-23 01:17:46"}}
```

**判定：`rows: 1`、`latest_date_str: "2026-09-23"`、`state: "fresh"`** ⇒
「导入 → 自建表 → 新鲜度计算 → REST 输出」整条链**已通**；`events: 0` 致归档页 6 组
「该类型暂无已发布事件」，属预期（事件集尚未导入）。
⚠ 探针 B 留下的这一行 `data_version` 是 32 字符截断值；**重传 v1.2.1 后按 A 的完整值重推即可覆盖**（`uk_date_str` 唯一键 ⇒ 走 UPDATE，不会插第二行）。

以下留档「为什么一度验不到、最后是怎么打开的」：

- 原因：`/wp-json/kcj-astro/v1/health` 硬性要求 `current_user_can('edit_posts')`，
  而本机持有的凭据是 **WordPress.com OAuth 令牌**，它只对 `public-api.wordpress.com` 有效；
  实测拿它去打站点自身的 REST **仍返回 401**。
- 也不能靠归档页反推：`$wpdb->get_results()` 在表不存在时**不抛异常**，只返回空并置 `last_error`，
  渲染结果与「表存在但没有数据」**完全一样**（两种情形都出 `kcj-astro-nodata`）。
- **必须用应用程序密码验**（账号须有 `edit_posts`）：

```bash
curl -u "<用户名>:<应用程序密码>" \
  "https://kuangchujia.com/wp-json/kcj-astro/v1/health"
```

判据：返回 JSON 内三表均 `exists: true`。**这一步没过之前，不要开始推数据**——
表没建成的话，推送会全批失败。

### 9.1.3 重传 v1.2.1 后怎么验（**第二批起不必再拿真数据当探针**）

v1.2.0 部署后，「ALTER 到底生效没有」只能靠**推一行数据看报不报错**判断 —— 那是拿生产数据当探针。
v1.2.1 第二批给 `/health` 加了 `schema` 段，**直接读实测列宽**：

```json
"schema": {"option":"2", "expected":"2", "ok":true,
           "widths":{"daily.data_version":64, "events.dt_model":64},
           "shortfalls":{}, "error":null}
```

| 看到什么 | 说明 | 下一步 |
|---|---|---|
| `plugin:"1.2.1"` ＋ `schema.ok:true` ＋ 两个 widths 都是 **64** | 增量 ALTER 已生效 | 直接推全量数据 |
| `plugin:"1.2.0"` | 后台没真换上新包（WP.com 有时需手动停用→删除→重传） | 重传 |
| `schema.ok:false`，`shortfalls` 写明缺口 | ALTER 未生效；守卫**没有落账**，下次访问会再试 | 再访问一次；连试不成用 `docs/deploy.md` 第 6 步的兜底 ALTER |
| `schema.error` 非空 | 上一次尝试的失败原因（含时间与缺口清单） | 同上 |

设计要点：**落账与实测绑定** —— 实测达标才写 `kcj_astro_schema_version`；不达标就保持旧值，
`init` 守卫下一次请求继续尝试（自我修复，不会卡死，也不会「以为升级了、其实没有」）。

**★ 本节判据已在线上兑现（2026-09-23 01:36，重传后首访）**：

```json
"plugin": "1.2.1",
"schema": {"option":"2", "expected":"2", "ok":true,
           "widths":{"daily.data_version":64, "events.dt_model":64},
           "shortfalls":[], "error":null}
```

⇒ 落在「**两个 widths 都是 64**」那一行 ⇒ **增量 ALTER 已在 wp.com 上生效**。
随后推送 2026-09-23（`data_version` **36 字符**）→ `written:1, failed:0`；
重推一次仍 `written:1`、`daily rows` **仍为 1** ⇒ UPDATE 覆盖，未插第二行。
**同一行数据，v1.2.0 时是 `written:0, failed:1`。**
（注：无法直接读回 DB 里的 `data_version` 值。判「完整写入」的依据是：列宽实测 64 ＋ F22 的报错文本系 MySQL **严格模式**对超长的反应（严格模式不静默截断、只报错）＋ 本次未报错 —— 属间接证据链。）

### 9.2 观察到的待办（非缺陷）

- 归档页 `<title>` 现为「**天象事件 Archive** - 邝楚嘉…」，中英混排。
  这是主题／Rank Math 的归档标题模板所致，**不是插件问题**；
  修法已列在 `docs/rank-math-config.md`（Rank Math → Titles & Meta → Post Types → astro_event →
  **Archive → Title**，即原表所称「Plural／归档标题模板」）。
  ★ **2026-09-23 03:2x 复核后更正**：待手点的**不是 6 项而是 7 项**，且其中一项**改为暂缓**；
  另有**两个比「字段没填」严重**的问题（分类归档路径式不可达、单条事件页零 JSON-LD）
  —— 详见**新增的 §十二**与 `docs/feasibility-review.md` F34—F36。
- ~~归档页现在显示 6 组「该类型暂无已发布事件」——因为 `publish_status = 1` 才展示，
  而事件集尚未导入。**属预期状态，不是错误。**~~
  → **已解决（2026-09-23）**：事件集已导入 79 条，「暂无」由 **6 处降到 2 处**
  （剩 `traditional` 与 `historical` 两 Tab：前者无生成器、后者未核录，**属如实呈现**）。
  详见 §十一。

---

## 十、`verify_package.py` 本轮新增的 35 项（事件枚举模块）

### 10.1 新增判据（check_events，28 项）

| 组 | 判据 | 为什么值得单列 |
|---|---|---|
| 交付件 | 模块存在 / **可编译** / 有 `SCRIPT_VERSION` | 可编译这一条用 `compile()` 真编译源码，不是「文件在不在」 |
| 白名单 | `EVENTS_WHITELIST` 是字面量元组 → 与插件 `rest-import.php` 的 `kcj_astro_rest_columns('events')` **逐项且同序**对拍 | ★ 客户端与服务端各一份正本，**必须机器对拍**；F22（列宽）/F23（列类型）都是这个病 |
| 白名单 | `NEVER_SEND` 恰为 `{event_id, post_id}` 且 ⊆ 白名单 | 发 `event_id` 等于指定主键 |
| 白名单 | `COL_MAXLEN` 的键全在白名单内 | 拼错键＝既不裁剪也不设防（静默） |
| 列宽 | **8 项**：`COL_MAXLEN` 不宽于 SQL 列宽 | F22 的同族判据，扩到事件表 |
| 接线 | `import event_almanac`／`build_future` 真调 `ea.build_events`／**已无空数组桩** | 回归守卫：空数组桩一旦回来，前台六 Tab 会一起「暂无」而无人报错 |
| 接线 | ★ **空集守卫装在写盘之前**（AST 取函数源码后比位置） | 判据装在写盘之后会留下空文件＝静默失败（F25 的教训） |
| 接线 | 应用发布窗口／manifest 无旧状态串／占位过滤按 slug 前缀 | 末一条防「硬编码名单」这种会漂移的写法 |
| 人工条目表 | JSON 合法／含 `entries`／有 `schema`+`red_line`／`kind` 合法／`slug` 唯一／**按 kind 分别校必填**／**每条都有 `source_ref`** | 末两条是红线「不编造」的机器化 |
| 文档口径 | ★ **行级**判据：过期口径串若出现必须带 `~~` 或位于引用块 | 文件级判据会被**它自己的留档**绊倒（自指陷阱，本项目踩过两次） |

### 10.2 负控制（23 → **30 项**）

本轮新增 ㉔—㉙（含一条 b）：

- **㉔ / ㉔b**：白名单比较器**真喂**一份篡改过的表 ⇒ 必报红；只调顺序也报红。
  （★ 初版写成「断言某常量不等」——**那是恒真的**，当场改掉。）
- **㉕**：守卫若装到写盘之后，位置判据必报红。
- **㉖**：空数组桩若回归，判据必报红。
- **㉗**：人工条目缺 `source_ref` 必被必填判据抓出。
- **㉘**：未划线的旧口径行必被认出，**同时留档行不误报**（两向）。
- **㉙**：常量名写错时 `_module_literal()` 返回 `None` 而非静默给默认值 ——
  防「取不到就当通过」这个真空洞。

---

## 十一、线上实测：事件枚举上线（2026-09-23 02:24）

**推送回执**

```
daily  第 1/4 批：写入 200 行      events 第 1/4 批：写入 25 行（累计 25/79）
daily  第 2/4 批：写入 200 行      events 第 2/4 批：写入 25 行（累计 50/79）
daily  第 3/4 批：写入 200 行      events 第 3/4 批：写入 25 行（累计 75/79）
daily  第 4/4 批：写入 130 行      events 第 4/4 批：写入  4 行（累计 79/79）
cache_flush: {"ok": true, "flushed": true}
```

**读回验证（全部带 `?cb=<ts>` 绕过 CDN）**

| 面 | 命令 / 探针 | 结果 |
|---|---|---|
| 表行数 | `GET /wp-json/kcj-astro/v1/health`（Basic 鉴权） | `events.rows = 79`（推前 **0**）、`daily.rows = 730`、`schema.ok = true` |
| 列表页 | `GET /tianxiang-yugao/` | **200**，**92,598 B**（推前 53,410 B）|
| 空组数 | 计数「该类型暂无已发布事件」 | **6 → 2**（剩 `traditional`／`historical`）|
| Tab 分组 | 解析 `data-tab` + 事件链接 | 日食 4／月食 5／行星天象 84／流星雨 30；**79 个唯一事件链接** |
| 详情页 | `/sky-forecast/solar-eclipse-annular-20270206/`、`…/lunar-eclipse-penumbral-20270817/` | **均 200**（44.5 KB）；H1／北京时间／计算口径／天文参数表／观测指南／免责声明齐备 |
| 假 slug | `/sky-forecast/planet-venus-mars-conjunction-19990101/` | **404**（证真路由） |
| CPT 文章 | `GET /wp-json/wp/v2/astro_event?status=publish`（读 `X-WP-Total`） | **79 篇已发布 / 0 草稿**（占位条目按设计未推送） |
| 明文纪律 | 详情页正文查字面 `**` | **无**（F27 闭环）|

**发布窗口实测**：区间 2026—2027 枚举 **123** 条，窗口（`2026-09-22` 起）外剔除 **44** 条 ⇒ 落地 **79** 条。

**未变项**：本轮**未改插件任何文件** ⇒ `wp-astro-forecast.zip` 指纹不变，**用户无需重传**。

---

## 十二、线上 SEO / 结构化数据实测（2026-09-23 03:2x）

> 取数方式：对真实 URL 发 GET（带 `?cb=` 绕 CDN 缓存），逐字读回 `<title>`／`meta description`／
> `og:*`／`script[type=application/ld+json]` 的 `@type`。全部**未鉴权、可复现**。

### 12.1 五张页面现状

| 页面 | `<title>` | `meta description` | JSON-LD `@type` | 判定 |
|---|---|---|---|---|
| 单条事件 `/sky-forecast/planet-saturn-opposition-20261004/` | `土星冲日 - 邝楚嘉 Chujia Kuang — …`＝**全站默认模板** | 自动取摘要（非模板） | **整页无** | ✗ 未设（①⑤） |
| CPT 归档 `/sky-forecast/` | `天象事件 Archive - 邝楚嘉 …`＝Rank Math 默认 | **与 title 逐字相同** | `Person, PostalAddress, ImageObject, WebSite, CollectionPage`（**无 `hasPart`**） | ✗ 未设（③④） |
| 分类归档 `/sky-forecast/planet/` | —— | —— | —— | ✗ **301 到不相干事件**（F34） |
| 预告列表页 `/tianxiang-yugao/` | `天象预告 - …` | —— | `WebPage, Dataset, Place, GeoCoordinates, PropertyValue` | ✅ 插件 daily 节点已出 |
| 老黄历页 `/tianwen-rili/` | `天文历法_老黄历_…` | —— | `WebPage, Dataset, Place, GeoCoordinates` | ✅ 同上 |

⇒ **`Dataset` 那一路（插件自出）线上已达**；缺的**全在 Rank Math 面板侧**，与「谁负责」的分工一致。

### 12.2 三个新发现

| # | 发现 | 判据 | 级别 |
|---|---|---|---|
| **F34** | 分类法归档**路径式不可达**：`?event_type=planet` 200，而 `/sky-forecast/planet/` **301** 到一条不相干事件、`/sky-forecast/eclipse/` **404** | 查询式 vs 路径式**两入口对照**（只看一侧必误判） | 中（URL 层） |
| **F35** | `Event` **无人输出**：文档说插件自出，代码 `kcj_astro_schema_should_emit('Event')` 在 Rank Math 启用时返回 false ⇒ 单条事件页零 JSON-LD | 线上单条页应出现 `Event` 节点 | **高**（结构化数据全缺） |
| **F36** | 描述模板**无人分流**：文档说插件按 `method` 注入，代码明写「不擅自 hook」 | 面板 Description 的取值来源 | 中（口径/溯源） |

### 12.3 面板清单更正

| 原记 | 现记 | 变更原因 |
|---|---|---|
| 6 项 | **7 项** | 「两份 Description」实为**同一字段的两种候选文本**（免费版无法分支）⇒ −1；新增 **Archive Description** 与 **Schema Type = Event** ⇒ +2 |
| Taxonomies sitemap **开** | **暂缓（保持关闭）** | 见 F34：开了等于把 301／404 交出去 |
| Event「插件自出，面板可选」 | **面板必设（CPT 级默认）** | 见 F35：插件已让位 |

### 12.4 面板改动后的线上复核（2026-09-23 03:36—03:40）

用户在面板填了 ① Single Title、③ Archive Title、⑤ Schema Type = Event。实测：

| 项 | 线上结果 | 判定 |
|---|---|---|
| ① Single Title | `土星冲日 ｜ 天象预报 · 华夏古天文历法实证记录` | ✅ 已生效 |
| ③ Archive Title | `天象预报 ｜ 华夏古天文历法实证记录` | ✅ 已生效 |
| ⑤ Schema Type = Event | 单条事件页 `application/ld+json` 块数 **0** | ❌ **未生效** |
| ⑥⑦ Sitemap | `sitemap_index.xml` 仅 `post-` / `page-` / `category-`；`astro_event-sitemap.xml` **404** | **面板已置 ⑥ ON／⑦ OFF（截图），线上仍未生效** ⇒ 待点 Save Changes（判据见 `rank-math-config.md` §2.1 ⑥） |

**差分实验（决定性）**：逐类页面测 `ld+json` 块数 —— 普通文章单页 **1**、普通页面单页 **1**、
CPT 归档 **1**、首页 **1**、**CPT 事件单页 0**。
⇒ 问题**只限 `astro_event` 单页这一类**；且该页标题由 Rank Math 按 ① 渲染 ⇒ Rank Math 确实在跑该页，
缺的是 **Schema 的输出环节**。排查顺序见 `docs/rank-math-config.md` §2.4。

逐项操作见 `docs/rank-math-config.md` §2.0—§2.4。

### 12.5 ★ 定谳：⑤ 不是「没保存」也不是缓存，而是 Rank Math 免费版源码的白名单（2026-09-23 03:4x）

**取证手段：head 逐条对照**（两页都未鉴权可复现，脚本见 `php_selftest.py` 同目录的取证思路；随机查询串 ＋ `no-cache` 两轮一致）

| 证据 | 单条事件页 | CPT 归档页 |
|---|---|---|
| `<title>` | 按 ① 渲染（Rank Math 在跑） | 按 ③ 渲染 |
| `meta description` | ＝事件摘要（② 回落生效） | ＝手填句（④ 生效） |
| `og:*` / `twitter:*` / `canonical` / `robots` | **全在** | 全在 |
| `class="rank-math-schema"` 的 `ld+json` | **0 个** | 1 个 |
| `天象事件Feed` 的 `alternate` | **没有** | 有 |
| 整页出现 `rank-math` 字样 | **0 次** | 1 次（就是那个 schema 块） |

⇒ **Rank Math 的元信息层工作正常，唯独结构化数据不产出** ⇒ 与缓存、与「没保存」、与「没认这个 CPT」都无关。

**根因（读源码定谳，证据链全文见 `docs/rank-math-config.md` §2.5）**

1. `class-jsonld.php::setup()` 把 `add_context_data` 挂在 `rank_math/json_ld` 的**默认优先级 10**；
2. `can_add_global_entities()` **L379/L394**：事件单页上 `can_use_default_schema()` 为真、`$data` 空、无文章级 schema 元数据
   ⇒ 落到 L394 取 `get_default_schema_type( $id, true )` ⇒ **false** ⇒ **Person / WebSite / ImageObject / WebPage 全被跳过**；
3. `includes/helpers/class-schema.php::get_default_schema_type()` **L70**：
   `$return_valid` 为真时**只认** `Article / NewsArticle / BlogPosting / WooCommerceProduct / EDDProduct`
   ⇒ **`Event` 在白名单外**，直接 `return false`；
4. `snippets/class-singular.php::get_default_schema()` **L104** 传的正是 `$return_valid = true`；
5. `json_ld()`：`$data = array_filter( do_filter( 'json_ld', [], $this ) ); if ( empty( $data ) ) { return; }`
   ⇒ **一个 `<script>` 都不输出**，与实测逐字吻合。

⇒ **面板里「能选到 `Event`」≠「前台会输出 `Event`」**：那个下拉是通用控件，免费版没有把前台取默认类型的白名单同步收窄。

**同日另有一处线上坏数据（F38）**

| 页面 | 修复前实测 `Dataset` 节点 | 修复后预期 |
|---|---|---|
| 首页 `/` | `name` = `揭阳每日天象数据集（）`、`@id` 以 `-` 结尾、`temporalCoverage` **缺失** | **不再输出** |
| 每篇博文（如 `/2026/09/22/three-calendars-…/`） | 同上（坏节点） | **不再输出** |
| 老黄历页 `/tianwen-rili/` | 同上（坏节点） | **不再输出**（该页数据由前端脚本渲染，未声明日期 ⇒ 不声明数据集） |
| 预告列表 `/tianxiang-yugao/` | `2026-09-23`（正常） | 维持 |
⇒ 违反插件自己的硬约束「不得为不可见内容声明结构化数据」；修法＝daily 上下文**先确认取到日期**才建节点。

**同回合交付（v1.3.0，**尚未上传**）**

| 交付物 | 内容 | 判据 |
|---|---|---|
| `includes/rankmath.php` | Event 归本插件；回调优先级 20 → 5；daily 加日期守卫 | `php_selftest.py` 30 项全绿 |
| `wp-astro-forecast.php` | 版本 1.2.1 → **1.3.0**（表结构版本仍为 2，升级**无需重新激活**） | `/wp-json/kcj-astro/v1/health` 的 `plugin` 回 `1.3.0` |
| `php_selftest.py`（新） | 语法闸 ＋ WordPress 钩子桩测试，**含负控制** | 30 / 30 |
| `wp-astro-forecast.zip` | **63,657 B ｜ SHA1 `615314a71f38f62b77e768997e948e339b90e579`** | `make_zip.py --selftest` 幂等；`verify_package.py` **214 / 0** |

**上传后验收**：不再手抄三条，改成**跑一条命令** —— `python live_verify.py`（九项判据 A—I，见 §12.6 与 `docs/deploy.md` §1b）。
手工兜底三条仍是：① `health` 回 `1.3.0`；② 事件详情页 head 内出现 `class="rank-math-schema"` 且 `@graph` 含 `Event`＋`startDate`（带 `+08:00`）；③ 首页／博文／老黄历页**不再**出现 `揭阳每日天象数据集（）`。

---

## 12.6 线上验收实录（2026-09-23 04:12 实测）

**命令**：`python live_verify.py`（免凭据；本机时间 2026-09-23 04:12:03，逐条带随机查询串 ＋ `no-cache`）

| 项 | 判据 | 实测 |
|---|---|---|
| A | `health` 的 `plugin` == `1.3.0` | **⏭ 跳过**（免访问 ⇒ HTTP 401；需应用程序密码） |
| B | `sitemap_index.xml` 列出 `astro_event-sitemap.xml` | **❌** 索引只有 `post-`／`page-`／`category-` 三条 |
| C | `astro_event-sitemap.xml` 状态码 200 | **❌ 404**（＝该类型未启用，即 ⑥ 的设置未落盘） |
| D | 事件详情页都出 `Event` | **✅ 79 / 79** |
| E | `startDate` 都以 `+08:00` 结尾 | **✅ 异常 0** |
| F | 事件页都还有 `WebSite` ＋ `WebPage` | **✅ 缺失 0**（F37 连带丢的那批已回来） |
| G | 全站无空日期 `Dataset` | **✅** 扫 21 页，坏节点 0 |
| H | 含 `[astro_today]` 的页仍出**完好** Dataset | **✅** `/tianxiang-yugao/` 命中 1（`2026-09-23`，非空） |
| I | 事件归档 `/sky-forecast/` 为 `CollectionPage` | **✅**（节点：`Person, WebSite, CollectionPage`） |

**全站 21 页的节点分布**（sitemap 18 条 ＋ 事件归档 ＋ 事件详情页）

| 页面 | 节点 | 说明 |
|---|---|---|
| 事件详情页（任一条） | `Event`・`Organization/Person`・`WebSite`・`ImageObject`・`WebPage` | ✅ 目标形态 |
| `/sky-forecast/`・`/articles/` | `Person`・`WebSite`・`CollectionPage` | ✅ |
| 博文 ×8 | `Organization/Person`・`WebSite`・`ImageObject`・`WebPage`・`Person`・`BlogPosting` | ✅ 无坏 Dataset |
| 首页・`/tianwen-rili/`・`/publications/`・`/chinese/`・`/glossary/`・`/calendar-reform/`・`/about/`・`/contact/` | 同上（`Article` 收尾） | ✅ **坏 Dataset 已全消** |
| `/tianxiang-yugao/` | 多一个 `Dataset`（`揭阳每日天象数据集（2026-09-23）`） | ✅ **唯一该出的一页，完好** |

### （1）新包是否生效：三条独立特征（不靠版本号也能判）

`health` 要凭据、现场拿不到，于是用**行为差异**判定。以下三条**只有 v1.3.0 的代码才可能产生**：

1. **事件页出现 `Event`** —— 修复前 Event 属「让位给 Rank Math」，而 Rank Math 免费版因白名单不出；现在出，且 `name` ＝ `土星冲日`、`description` 逐字来自本插件 `data/events_future.json` 的 `summary` 字段（`地心距 8.434 AU` 那句）、`eventAttendanceMode`／`eventStatus`／`isAccessibleForFree` 三键逐字对应 `includes/rankmath.php` L186—188。**Rank Math 不可能产出这些字段。**
2. **事件页同时有 `WebSite`／`WebPage`** —— 只有回调优先级 < 10（`! empty( $data )` 短路）才会发生，旧版是 20。
3. **首页／博文／老黄历页的坏 Dataset 全消，而 `/tianxiang-yugao/` 的好 Dataset 仍在** —— 正是 daily 日期守卫「抑制无效、放行有效」的预期形态（旧版无守卫，处处照挂）。

⇒ **判定：v1.3.0 的代码已在线上运行。** 唯一没拿到的硬证据是版本号本身，故 A 项仍记「跳过」而非「通过」。

### （2）新发现 F39：并入 Rank Math `@graph` 的标量会被 WordPress 核心串化

线上实测与本地源码**不一致**：本地 `'isAccessibleForFree' => true`（布尔），线上是 `"1"`（字符串）；同一节点里 `geo.latitude` 也被写成 `"23.55"`。

**根因（源码级）**：Rank Math 渲染前跑 `wp_kses_post_deep( $json )`（`includes/modules/schema/class-jsonld.php` L164），该函数在 WordPress 核心里的实现是
`map_deep( $data, 'wp_kses_post' )`（`wp-includes/kses.php` L2516—2518），而 `map_deep` 对**每一个非数组/非对象标量**都调一次回调（`wp-includes/formatting.php` L5225—5240）⇒ 布尔 `true` → `"1"`、浮点 `23.55` → `"23.55"`。

**影响与处置**：`isAccessibleForFree` 用 `"1"` 表真 **是 schema.org 认可的 Boolean 表达法**（官方允许 `"1"`／`"0"`／`"true"`／`"false"`），**不算缺陷**；`geo` 的经纬度被串化后不再是 `Number`，但 `Dataset` 不是 Google 的富媒体类型、`Rich Results Test` 不校验它，**不列为不通过**。**无法规避**：只要把节点并进 Rank Math 的 `@graph`，就会过这一道。详见 `docs/feasibility-review.md` F39。

### （3）遗留（未完成，如实记录）

| # | 事项 | 现状 | 谁做 |
|---|---|---|---|
| B／C | 事件 sitemap | `astro_event-sitemap.xml` 仍 **404** ⇒ ⑥ 的设置在面板里是 ON，但**没点 `Save Changes`**（＝未落盘） | 用户：`Sitemap Settings` 任一页点 `Save Changes`；仍 404 才走 `Dashboard → Database Tools` 清 sitemap 缓存 |
| ⑤ | CPT 默认 `Schema Type` 仍为 `Event` | 当前**无害**（我们的节点在优先级 5 已把 `! empty( $data )` 撑住），改 `Off` 是**防将来重复**——若某版 Rank Math 让该设置真的生效，同页会出现两个 `Event` | 用户：`Titles & Meta → Post Types → 天象事件 → Schema Markup` 设 `Off` |
| A | 版本号直读 | 需应用程序密码 | 用户（可选） |

> **「让位」判据的安全性已定谳**：文章自带 `rank_math_schema_*` 时我们让位，不会造成空洞 ——
> `add_schema` 挂在 `rank_math/json_ld` 优先级 10（`includes/modules/schema/class-frontend.php` L47，由
> `class-jsonld.php::setup()` L58 `new Frontend()` 实例化），函数体是 `array_merge`，**不看白名单**；
> 且 `can_add_global_entities` 的 `DB::get_schemas()` 短路（`class-jsonld.php` L383）会保住站点级实体。

### （4）本轮自纠（第四处，发生在探针里）

| # | 症状 | 真因 | 教训 |
|---|---|---|---|
| 4 | 全量扫 79 条事件页，**79 条全报「取页失败」** | 探针把随机查询串**无条件**拼成 `u + "&_=…"`；事件页 URL 本来**没有**查询串 ⇒ 拼成了 `…/slug/&_=123`，路径被弄坏 | ① 破缓存的拼接必须按「有无 `?`」分支（已在 `live_verify.py::_bust()` 固化）；② **「全红」先怀疑探针**，别先怀疑站点 —— 本轮若照单全收，会得出「Event 全丢」的反向错误结论 |

**修后复跑：79 / 79 全绿**（见上表 D—F）。

---

## 12.7 第二轮：⑥ 已生效，但漂亮路径全 404（2026-09-23 04:2x）

**用户两条回报**：⑤ 面板 `Schema Type` **只有 `NONE`**；⑥ **已点 `Save Changes`**。

### （1）⑥ 确实生效了 —— 拿到硬证据

| 入口 | 结果 |
|---|---|
| `/?sitemap=1`（索引·查询式） | **200**，**4 条 `<loc>`**，含 `astro_event-sitemap.xml`（`lastmod 2026-09-22T18:24:24+00:00`） |
| `/?sitemap=astro_event` | **200**，**80 条 `<loc>`**（`/sky-forecast/` 归档 ＋ 79 条事件页） |

⇒ **「开启该类型 sitemap」这件事已经完成**。上一轮把它判为「未落盘」，是因为只看了**路径式**那一条入口（见下）。

### （2）同时发现：**所有 sitemap 的漂亮路径都 404**（F41）

| 路径 | 状态 |
|---|---|
| `/sitemap_index.xml`、`/post-sitemap.xml`、`/page-sitemap.xml`、`/category-sitemap.xml`、`/astro_event-sitemap.xml` | **全 404** |
| `/sitemap.xml`（Jetpack 口径）、`/wp-sitemap.xml`（WP 内核口径）、`/main-sitemap.xsl` | **全 404** |
| `/robots.txt` | **200**（里面写着 `Sitemap: …/sitemap.xml` 与 `…/sitemap_index.xml`） |

**关键对照**：`/feed/` 200、`/category/uncategorized/` 200、`/sky-forecast/` 200、文章固定链接 200
⇒ **重写系统本身是好的，坏的只有 Rank Math 那一组 sitemap 路由** ⇒ 重写规则不在 `rewrite_rules` 表里。

**影响面**：`robots.txt` 推荐的两个地址此刻都是 404 ⇒ **全站 sitemap 通道断**（不止本插件）。
**修法**：`设置 → 固定链接` 直接点「保存更改」（flush 重写规则）→ 仍不通再清 Rank Math sitemap 缓存。详见 `docs/rank-math-config.md` §2.6。

### （3）⑤ 的答复：**不用动**

面板该项**只有 `NONE`** ⇒ 无需再操作。这与 F37 的方向一致（该下拉在本站这条路上给不出 `Event`），
且 `Event` 自 v1.3.0 起**由本插件输出**，**不依赖**此面板项。
（附注：Rank Math 源码 `includes/helpers/class-choices.php` L436—451 的 `choices_rich_snippet_types()` 里**是列了 `event` 的**，
若面板确实只见 `None`，多半是站在了**分类法**那一组（左栏 `Astro_event:` 下的「天象类型」）—— 但**两种情况都不影响前台**。）

### （4）工具升级与一处**工具自咬**（当场修）

第二节那两条判据原先只查**路径式**，导致：①「⑥ 未生效」的误判；② 更危险的一处 ——
`check_datasets` 的 URL 清单**是从那个已 404 的索引里取的**，索引一坏，扫描面就从 **21 页静默缩到 2 页**，
而它**照样报绿**（「2 页无坏 Dataset」）。**扫描面缩水比没有扫描面更危险**。

**修法（已固化进 `live_verify.py`）**

* **两条入口分开报**：`B`／`C`（查询式＝生成侧）、`B2`（路径式＝路由侧），
  B2 的报错文本里**直接写出该走哪条修法**（判别表见 `docs/rank-math-config.md` §2.6）。
* **清单来源回落 ＋ 翻译**：路径式索引不通时回落查询式，并把子 sitemap 文件名翻成 `?sitemap=<name>`
  （否则索引里的漂亮 URL 同样 404，清单还是空的）。
* **扫描面下限守卫**：`MIN_SCAN_PAGES = 15`（当日实测正常面 ≈21 → 现 ≈100 页），低于下限**直接报红**。

**修后复跑（2026-09-23 04:24）**：**8 通过 ／ 1 跳过 ／ 1 不通过**

```
✅ B  索引·查询式 4 条（含 astro_event-sitemap.xml）
✅ C  事件 sitemap·查询式 80 条 <loc>
❌ B2 漂亮路径 404 / 404  ⇒ 重写规则未进表（修法已写在报错里）
✅ D  事件页 Event ............ 79/79
✅ E  startDate ＋08:00 ........ 异常 0
✅ F  站点级实体 .............. 缺失 0
✅ G  全站无坏 Dataset ........ 扫描面 100 页，坏 0   ← 扫描面已恢复
✅ H  /tianxiang-yugao/ 好 Dataset 仍在
✅ I  归档页 CollectionPage
⏭ A  版本号（缺应用程序密码）
```

---

*其余证据见 §九（安装后实测）／§十一（事件枚举上线）。*

---

## 12.8 第三轮：**B2 已修复，九项全通过**（2026-09-23 04:37 实测）

**动作**：用户侧执行 `设置 → 固定链接`（Permalinks）→ 什么都不改、直接点「保存更改」（＝ `flush_rewrite_rules()`）。

**复跑 `python live_verify.py`（2026-09-23 04:37:43）**：**通过 9 ／ 跳过 1 ／ 不通过 0**，**exit=0**

```
⏭ A  插件版本号（缺应用程序密码）——唯一「跳过」
✅ B  索引·查询式 4 条（post／page／astro_event／category）
✅ C  事件 sitemap·查询式 80 条 <loc>
✅ B2 漂亮路径 200 ／ 200        ← 本轮修复项，已转绿
✅ D  事件页 Event ............ 79/79
✅ E  startDate ＋08:00 ........ 异常 0
✅ F  站点级实体 .............. 缺失 0
✅ G  全站无坏 Dataset ........ 扫描面 100 页（路径式索引），坏 0
✅ H  /tianxiang-yugao/ 好 Dataset 仍在（命中 1）
✅ I  归档页 CollectionPage（Person, WebSite, CollectionPage）
```

**★ 复跑结果自带两条判据过硬的旁证**：

1. **扫描面来源自动切回「路径式」** —— G 的详情从上一轮的「查询式 `/?sitemap=1`」变成
   **「路径式 `/sitemap_index.xml`｜4 个子 sitemap」**，说明 `sitemap_urls()` 的**双入口回落逻辑按预期工作**
   （路径式通了就优先用路径式）—— 这是**修复生效**的直接证据，不是我们改了口径。
2. **扫描面仍为 100 页**（未因入口切换而缩水）⇒ 下限守卫没被触发，面是**真的**。

**路径式产物逐一核过（`curl`，带随机查询串 ＋ `no-cache`）**

| 路径 | 状态 | `<loc>` 条数 | Content-Type |
|---|---|---|---|
| `/sitemap_index.xml` | **200** | **4** | `text/xml; charset=UTF-8` |
| `/astro_event-sitemap.xml` | **200** | **80** | `text/xml; charset=UTF-8` |
| `/post-sitemap.xml` | **200** | **9** | `text/xml; charset=UTF-8` |
| `/page-sitemap.xml` | **200** | — | — |
| `/category-sitemap.xml` | **200** | — | — |
| `/main-sitemap.xsl` | **200** | — | （XML 里引用的样式表，同步恢复） |
| **`/sitemap.xml`** | **404** | 0 | `text/html` ← 仍不通（见下） |
| **`/news-sitemap.xml`** | **404** | 0 | — ← 仍不通（见下） |
| `/wp-sitemap.xml` | 404 | 0 | （WP 内核口径；Rank Math 默认接管后不提供，属正常） |

索引实际内容：
```
<loc>https://kuangchujia.com/post-sitemap.xml</loc>
<loc>https://kuangchujia.com/page-sitemap.xml</loc>
<loc>https://kuangchujia.com/astro_event-sitemap.xml</loc>
<loc>https://kuangchujia.com/category-sitemap.xml</loc>
```

**残留（新发现 · 轻 · 与 F41 同族，但**不是**本模块的事）**

`/robots.txt`（200）里声明了**三条** sitemap：

```
Sitemap: https://kuangchujia.com/sitemap.xml          ← 404（Jetpack 口径）
Sitemap: https://kuangchujia.com/news-sitemap.xml     ← 404（Rank Math 新闻 sitemap，未开）
User-agent: *
Disallow: /wp-admin/
Allow: /wp-admin/admin-ajax.php

Sitemap: https://kuangchujia.com/sitemap_index.xml     ← 200 ✅
```

⇒ **真正的主 sitemap（`/sitemap_index.xml`，含事件 sitemap）已经通了**，Google 能拿到全站。
剩下两条是**对不存在的地址的声明**，Google 抓取时会记「Sitemap could not be read」，
**不影响收录**（第三条已覆盖全站）。处理二选一：① 开 Rank Math 的 **News Sitemap** 模块（若确实要新闻 sitemap）；
② 把这两行从 `robots.txt` 里去掉。**属可选项，不列为阻断项。**

**行尾**：本轮**未改插件代码**，包指纹仍 `63,657 B ／ SHA1 615314a71f38f62b77e768997e948e339b90e579` ⇒ **用户无需重传**。

---

## 十三、v2.0.0 轮（2026-09-23 · 观测地维度与三个子项）

> 用户令：「3个子项以三个栏目的样式体现，不能做成菜单」

### 13.1 三层判据的实测结果

| 层 | 工具 | 结果 |
|---|---|---|
| ① 包内一致性 | `verify_package.py` | **288 项通过 / 0 失败**（v1.3.0 轮为 259 项，本轮 +29） |
| ② PHP 层逻辑 | `php_selftest.py` | **32 项通过 / 0 失败**（v1.3.0 轮为 30 项，本轮 +2） |
| ③ 线上产物 | `live_verify.py` | 待重传插件后跑（见 §13.4） |

★ **PHP 语法闸**：插件内 **17 个 `*.php`** 全部通过 `php -l`。

### 13.2 本轮新增的判据（第 12 节 A—J 十组）

| 组 | 判据数 | 内容 |
|---|---|---|
| A | 5 | 观测地表 `daily_site`：SQL ↔ dbDelta、复合唯一键 `uk_date_city`、最小列宽守卫 |
| B | 6 | 升落口径（F42 北京日窗口 / F43 地平线 −0.8333°）＋ 观测地量恰为 11 项 |
| C | 14 | 七个短代码注册 ＋ 三个新模板 ＋ 两个外置脚本 ＋ 三个栏目 key 与开关参数 |
| D | 2 | 外置脚本**零裸与号** |
| E | 2 | 插件版本 ≥ 2.0.0、表结构版本 = 3 |
| F | 7 | REST 白名单含 `daily_site`、判重键支持**复合键**、四个数值列 |
| G | 3 | 三个新 Python 脚本存在、观测地白名单**客户端 == 插件且同序** |
| H | 5 | 期间口径的两条错路（静态哨兵，**先剥注释再扫**） |
| I | 1 | `make_zip.py --selftest` 明示「未落盘」 |
| J | 11 | 三栏目外壳：模板存在、**不含脚本标签**、按 key 动态渲染、打印全展开、**未加错误的默认显示兜底** |

### 13.3 负控制：34 条，且**编号唯一**（新增一条元判据）

负控制由 30 条扩到 **34 条**（㉚ 静态哨兵非恒真 / ㉛ 注释不误报 / ㉜ `strtotime` 代码里必被抓 / ㉝ 最小列宽覆盖面空集守卫）。

★ **另加一条「对判据自身记账」的判据**：**负控制编号唯一**。
本轮它**当场抓出两处重号** —— 新加的三条误用了事件模块轮已占用的 ㉔㉕㉖，
以及一条派生编号「㉖-前置」又占了一次本体号。重号 = 账目不清，故做成判据。
实现上只统计**定义行**（含 `rep.chk(`），不要求 `★` 前缀（早期 ①—④ 没有），
注释里的引用自然排除。

### 13.4 诚实声明：本轮**没做**的校验

1. **`live_verify.py` 本轮未跑** —— 它要在**重传 v2.0.0 插件之后**才有意义。
   本轮只做到「包内一致 ＋ PHP 层逻辑」两绿。
2. **四个表的数据都还没进线上库** —— 站点 REST 一律 **401**（应用密码已撤消）。
   `build_site.py` 与 `history_events.py` 产出的是 NDJSON/SQL，
   **能不能入库不由本模块决定**。故「页面显示内容」这一层**本轮无法验证**。
   页面在无数据时的表现（显示「未覆盖」而非报错）**有判据、无实测**。
3. **月食判据只有三条外部对拍**（2000-07-16 / 2011-12-10 / 2018-07-28），
   其中只有两条核到了时长（106.4 / 102.95 分钟）。
   2011-12-10 的时长本轮**未核到一手值** ⇒ 参考值里留 `None`，**不猜数**。
4. **`gen_huangli.py` 的同族缺陷（F42/F43）本轮只记不改** —— 该页面不显示日出日落，
   改动收益未知而回归风险真实存在。

### 13.5 三处「判据自己出错」（本轮的主要教训）

| # | 现象 | 根因 | 修法 |
|---|---|---|---|
| 1 | 两条新哨兵一起误报，而代码已改对 | **自指陷阱**：禁用的旧写法**必然写在注释里做警示** | 哨兵**先剥注释再扫** |
| 2 | 三条栏目判据误报「模板缺栏目名」 | 模板按 `$s['key']` **动态**渲染，本就不该有字面量 | 判据改扫**短代码**，并反过来要求模板用 `$s['key']` |
| 3 | 两条开关参数判据误报 | 判据**写死了对齐空格**（`'today'  => '1'` vs `'future' => '1'`） | 一律用 `\s*` 容错 |

★ **共同点**：都是**判据**错，不是代码错。判据报红时**先查判据自己**。


---

## 十四、v2.1.0 轮（2026-09-23 · 三栏目装配 ＋ 历史栏目扩族）

### 14.1 本轮判据增量

| 闸 | 上轮 | 本轮 | 增量 |
|---|---|---|---|
| `verify_package.py` | 288 / 0 | **308 / 0** | **＋20**（新增判据围绕**历史栏目扩族**与**三栏目外壳**两块） |
| `php_selftest.py` | 32 / 0 | **34 / 0** | **＋2**（分组键只剥日期形 ＋ 跳转闰年基准） |
| `python/history_events.py --selftest` | —— | **全过** | 三族真算 11 年 ＋ 7 条负控制（★ 本轮新增该闸） |
| 负控制 | 34 条 | **36 条** | ＋㉞㉟㊱（**编号唯一**这条元判据当场复核无重号） |

### 14.2 本轮三条判据的**规则谓词抽成模块级函数**

`verify_package.py` 新增三个**模块级谓词**，判据与负控制**调同一份代码**：

```
rule_history_group_key_date_only()   # 分组键只剥「（YYYY-MM-DD）」，不剥任意括号
rule_history_nav_leap_base()         # 日期跳转基准年必须是闰年
rule_no_markdown_bold()              # 输出 HTML 的模板不得写 markdown 粗体（先剥注释）
```

**为什么必须这样写**：此前负控制里**重抄一遍正则**，证明的只是「我抄的那份会报红」——
**产品里真正跑的那一份，谁也没验过**。抽成函数后，负控制验的是产品本身。

### 14.3 负控制变异测试（证明判据非空壳）

| 编号 | 变异动作 | 预期 | 实测 |
|---|---|---|---|
| ㉞ | 把分组键正则放宽成「剥任意末尾括号」 | 必报红 | ✅ 报红（并点名会并组的两类标题） |
| ㉟ | 把跳转基准年 `2028` 改成 `2026` | 必报红 | ✅ 报红（`02-28 +1` 落到 `03-01`） |
| ㊱ | 在模板里**代码位置**写 `**加粗**` | 必被检出 | ✅ 检出（写在注释里则不误报 —— 两向都验） |

★ 三条都对**同一份规则函数**做变异，不重抄实现。

### 14.4 数据面实测（本轮）

| 项 | 实测值 | 说明 |
|---|---|---|
| 族年率（12 年样本） | 月食 **2.29** / 流星雨 **15.00** / 行星 **19.66** | `probe_family_rate.py`；F47 即因此改了判据区间 |
| 「月-日」覆盖率（只月食） | **133 / 366 = 36.3%** | F46 的直接依据 |
| `history_events` 月食全量 | **288 条 / 676 s** | 1900—2025；产物 sha1 `38ebacd0…` |
| 三族全量 | **已完成**：**4,672 条**（月食 288 ／ 流星雨 1,890 ／ 行星 2,494）、**1,831 s**、sha1 `0fc2acdb01ec`（**正文口径**；整档 `f6686d52ab69`） | **三族并集覆盖「月-日」＝ 366 / 366 ＝ 100%**（原 36.3%） |

### 14.5 诚实声明：本轮**没做**的校验

1. **三族全量的线上渲染未验** —— 数据仍在生成；覆盖率与成组渲染的实际观感未经真浏览器确认。
2. **`[astro_hub]` 未在线上站点实装** —— 插件已改，**须重传一次包**；本轮只做到「包内判据全绿」。
3. **日食仍是 0 条** —— 非本轮新增缺口，但**必须在页面上如实说「未录入」**，
   而不是让读者以为「这一天没有日食」。
4. **`gen_huangli.py` 的 F42／F43 同族缺陷本轮仍未动**（理由见 §13.4 第 4 条）。

### 14.6 三族全量产出后的回填项（清单）

- [x] `data/events_past.json` 条数 / 族分布 / sha1 —— **4,672 条；288／1,890／2,494；sha1 `0fc2acdb01ec`（**正文口径**；整档 `f6686d52ab69`）**
- [x] 三族的「月-日」覆盖率 —— **366 / 366 ＝ 100%**（已替换 §14.4 的样本外推值）
- [x] `_diag/history3.log` 的实测耗时 —— **1,831 s（≈30.5 分钟）**
- [x] README §九 缺口表第 10 条 —— 已改为「**366 / 366 ＝ 100%**」

### 14.7 本轮的主要教训

**一条**：**判据的数值必须来自实测，不能来自注释里的印象**（F47）。
判据写错的下场与 F45 一样 —— **它会把正确的计算结果判成错的**，
而且**报错信息看起来非常权威**，足以让人去改代码而不是改判据。
