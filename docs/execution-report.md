# 落地指令集执行报告（v1.1.0 → v1.2.0）

- **执行日期**：2026-09-22
- **依据**：《WordPress 站点天象模块落地指令集》指令 01—10；裁定见 `docs/instruction-review.md`
- **交付包版本**：`wp-astro-forecast` **1.1.0 → 1.2.0**（`KCJ_ASTRO_VER`）
- **交付判据**：三处自检全绿 ＋ 打包件结构核对（见 §六）

---

## 零、本轮干了什么（一屏看懂）

| 面 | 改了什么 |
|---|---|
| **指令落地** | 指令 01—10 逐条对拍落地；否决「模板放主题目录」、纠正 3 项事实性错误 |
| **修必崩缺陷** | F20：CPT 注册位置错 ⇒ 详情页/归档页**必然 404** |
| **修功能缺陷** | F17：历史回推把 **UT 当 TT** 喂 Meeus，漏 ΔT ⇒ 公元前 720 年黄经偏 3.41° |
| **修幂等缺陷** | 3 项（daily 判重键错 / relations 无唯一键 / `last_error` 判成功） |
| **修口径缺陷** | F18 示例日期两处不一致；F19 死参数；GB/T 引用超范围 |
| **新增** | 4 个 includes 模块、6 个模板、`data/` 目录、`build_dataset.py`、2 份文档 |

**代码量**：插件 21 个文件（PHP 1,357 行 + CSS 143 行 + 文档 92 行）；Python 2,309 行；SQL 117 行；校验器 830 行。

---

## 一、指令 01—10 处置对照

| 指令 | 要求 | 落点 | 处置说明 |
|---|---|---|---|
| **01** | 独立插件 + 标准插件头 + `includes/` `assets/css/` `data/` 三段目录 | `wp-astro-forecast.php`、`includes/`（8 件）、`assets/astro-style.css`、`data/` | **采纳**，目录名保留 `wp-astro-forecast`（已发布过，改名只有成本）；样式文件按指令命名 `astro-style.css`，旧 `astro.css` 已删 |
| **02** | `dbDelta` 建表 + 激活钩子 | `includes/class-astro-db.php`（建表唯一正本）、`includes/activation.php`（薄壳）、`sql/install_tables.sql` | **采纳并补足**：指令只列 2 张表，实际落 **3 张**（`daily` / `events` / `relations`）；`daily` 补 `special_event_ids` / `created_at` / `updated_at` / `uk_date_str` |
| **03** | Python 批量算 + 插件内导入 | `python/compute_sky.py`、`python/build_dataset.py`、`includes/rest-import.php` | **改通道**：`$wpdb` 直连在 WordPress.com **不可用**（平台不开放外部 MySQL）⇒ 走 REST `POST /wp-json/kcj-astro/v1/import`＋应用程序密码鉴权；事件导入后自动同步为 CPT 文章并回填 `post_id` |
| **04** | CPT + 分类法 + 元字段；URL `/sky-forecast/{slug}/` | `includes/cpt.php` | **采纳**：URL 前缀由两段式 `sky/forecast` 改单段 `sky-forecast`（★ v1.1.0 的旧前缀会被同名页面抢路由）；**CPT 与分类法改挂 `init`**（见 F20）；分类法顶层 5 类＋日月食下挂 2 子项（解指令 04/05 矛盾）；9 个元字段 |
| **05** | 三个短代码 | `includes/shortcodes.php` | **采纳**：`[astro_today]` / `[astro_forecast_list]`（type 全 6 值 + 9 别名 + `limit`）/ `[astro_related_events]`（补参数 `id` `mode` `limit`）；另保留 `[astro_event_detail]` |
| **06** | 2 模板 + 1 样式，放主题目录 | `templates/`（6 件）、`assets/astro-style.css` | **否决「放主题目录」**：WordPress.com **主题目录不可写**，且与指令 01「主题更新不丢失」自相矛盾 ⇒ 改「插件内置 ＋ `template_include` 注入」，主题若有同名模板则主题优先（尊重自定义） |
| **07** | 标题/描述模板；Event / ScholarlyArticle / Calendar+AstronomicalObject；站点地图；焦点关键词 | `includes/rankmath.php`、`docs/rank-math-config.md`、`docs/seo-config.md` | **部分否决**：`Calendar` 与 `AstronomicalObject` **在 schema.org 中不存在**（官方词表 release 29.0 全文 0 次）⇒ 改 `WebPage` + `Dataset`；`ScholarlyArticle` 类型存在但 **Rank Math 免费版无 Custom Schema** ⇒ 由本插件自出 JSON-LD 补位。钩子经查源码确认：`rank_math/json_ld` 是 **filter**，回调须 `return` 合并后数组 |
| **08** | 每月/每季 Cron + 自动内链 | `includes/cron.php`、`includes/compliance.php` | **采纳并降级**：WP.com **默认禁用真实系统 WP-Cron**，且插件内跑不了 Python ⇒ 改为「按时检查新鲜度 → 后台提示 → 发 `kcj_astro_need_recompute` 钩子」，**不假装它能自动算天象**；自动内链默认**关闭**（可后台开），避免不可控改写正文 |
| **09** | `the_content` 挂免责声明 | `includes/compliance.php` | **采纳并收紧**：GB/T 33661—2017 只规范农历编排与二十四节气，**不规定月相公布精度** ⇒ 改为「农历日期与二十四节气的编排符合」；另加**去重签名**防同页两份 |
| **10** | 测试 + 数据校验 + 合规检查 + 提交收录 | `docs/acceptance-checklist.md`（TC 清单） | **采纳**；「误差 ≤1 分钟」需说明**测的是哪一层**：解析月相 vs skyfield 25 个朔望最大偏差 **0.13 min**（自检实测），与紫金山历表比对属另一层 |

---

## 二、修掉的五个真缺陷（F17—F21）

### F17 ｜历史回推把 UT 当 TT 喂进 Meeus 级数（**最高危**）

- **位置**：`python/compute_sky.py` 的 `_daily_analytic()` 与 `back_calc_historical()`。
- **实质**：`_jd_from_calendar()` 返回的是 **UT** 儒略日；而 Meeus 第 25/47/49 章级数与 skyfield 的 `t.tt` 要的是 **TT（JDE）**。二者差 **ΔT**：`TT = UT + ΔT`。原代码直接把 UT 当 JDE 用，**漏了 ΔT 改正**。
- **为什么一直没被发现**：现代 ΔT 只有几十秒，日黄经差约 0.01°，测试全绿。**只有历史回推才暴露**：

| 年代 | ΔT | 漏改正造成的黄经差 | 黄纬差 |
|---|---|---|---|
| 公元前 2000 年 | 46,774 s ≈ **0.54 天** | **5.92°** | 0.551° |
| 公元前 720 年 | 20,689 s ≈ **0.239 天** | **3.41°** | 0.336° |
| 公元 1000 年 | — | 0.20° | 0.018° |
| 公元 2026 年 | ~69 s | 0.01° | 0.001° |

- **量化结论**：公元前 720 年偏 3.41°，**足以让「日食」与「不日食」判断反过来**。而本模块的历史条目正是日食回推（《春秋》隐公三年「春王二月己巳，日有食之」）——**这个缺陷直接打在卖点上**。
- **修法**：新增 `jd_ut_to_jde(jd_ut, year_decimal)` / `jde_to_jd_ut(...)`；`_daily_analytic()` 先折 TT 再喂级数；`back_calc_historical()` 显式分离 `jd_query_ut` / `jd_query_tt`；`compute_daily()` 精算分支记录 `jd_ut`；全链加 `jd_scale: "TT (JDE)"` 自述字段；`CONFIG.DATA_VERSION` 加 `+tt_scale` 后缀。
- **修复后实测**：公元前 720-02-22 算出黄经差 **2.101°**、月黄纬 **0.269°** ⇒ 满足日食几何，**与《春秋》所记相符**。

### F20 ｜CPT 注册写在激活钩子里 ⇒ 详情页/归档页必然 404（**必崩**）

- **实质**：`register_post_type()` 原先写在 `register_activation_hook` 内。该钩子**只在激活那一次执行**，此后每个请求都不再跑；而 WP 必须在**每个请求的 `init`** 上完成注册，才能把 `/sky-forecast/{slug}/` 这类请求路由到 CPT。
- **后果**：激活后**详情页与归档页必然 404**，后台「天象事件」菜单也会消失——正撞指令 04 自己的校验标准（原文漏字写作「正常访问，404 错误」，应为「**无** 404 错误」）。
- **修法**：CPT 与分类法注册移到 `includes/cpt.php` 的 `add_action('init', ..., 5)`；`activation.php` 改薄壳（建表 + 排程 + `flush_rewrite_rules()` + 激活当次手动调一次注册）。**已写成硬判据**：校验器断言「CPT 在 `init` 注册」且「激活钩子内不再注册 CPT」。

### F21 ｜模板想放主题目录（WordPress.com 不可写）

- **实质**：指令 06 要求放 `wp-content/themes/seedlet/`；本站托管在 WordPress.com，**主题目录不可写**，且主题一升级即被覆盖。
- **修法**：模板入插件 `templates/`；`kcj_astro_template_include()` 挂 `template_include`，按 WP 模板层级**先让主题出手**（主题有同名文件就用主题的），没有再落到插件。旧 URL 前缀 `/sky/forecast/` → `/sky-forecast/` 加 **301**（`wp_safe_redirect(..., 301)`），保证指令 10 的「无死链」。

### F18 ｜同一件史事在代码里有两个日期

- **实质**：`selftest()` 用 `(-720, 7, 1)`，`emit_samples()` 用 `parse_era_year("720BC")` 配 `(2, 22)` ⇒ 同一件「鲁隐公三年己巳日食」差**一年半**。另外 `source_ref` 原写杨伯峻《春秋左传注》——属**近现代注本**，与「只引古籍正本」的口径不符。
- **修法**：抽模块常量 `SAMPLE_HISTORICAL`（`era_year=-719 / 2 / 22`，含 `calendar_note` 与 `source_ref="《春秋》[M]. 先秦."`），`selftest()` 与 `emit_samples()` **同引该常量**；自检加两条断言（古籍正本、纪年一致性）。

### F19 ｜死参数

- **实质**：`identify_special_events(y, m, d, city="jieyang")` 的 `city` **函数体从不读取**，两处调用点传了它，给人「按城市算」的错觉。
- **修法**：删参数，两处调用点同步；样例里留注释说明删除理由。

---

## 三、幂等三修

| # | 缺陷 | 后果 | 修法 |
|---|---|---|---|
| 1 | `daily` 表判重键只有 `jd` | `jd` 是**计算量**，算法或 ΔT 修正后同一日期会算出不同 `jd` ⇒ 重导**插出第二行**（F17 修复后**每个历史日期都会触发**） | 加 `uk_date_str`；REST 判重键改 **`date_str`**（稳定业务键） |
| 2 | `relations` 表**无唯一键** | 每次重复导入**无限追加** | 加 `UNIQUE uk_from_to_rel(from_event, to_event, rel_type)`；写入改 `INSERT ... ON DUPLICATE KEY UPDATE` |
| 3 | 用 `$wpdb->last_error === ''` 判成功 | 该变量**不随成功查询复位** ⇒ 上一次的旧错误会被算到这一次头上 | 改判 `$wpdb` 方法的**返回值**（受影响行数/`false`），`last_error` 只作诊断输出 |

> 第 1 项与 F17 有**耦合**：F17 修好后，历史日期的 `jd` 会整体平移，若判重键仍是 `jd`，则**同一次升级即会产生全量重复行**。故 `sql/install_tables.sql` 末尾附**升级前置去重语句**与提醒。

---

## 四、文件变更清单

### 新增

| 文件 | 行数 | 说明 |
|---|---|---|
| `wp-astro-forecast/includes/class-astro-db.php` | 176 | **表结构唯一正本**（`schema()` / `create()` / `health()` / `replace_relations()`） |
| `wp-astro-forecast/includes/cpt.php` | 450 | CPT、分类法、9 元字段、模板注入、旧 URL 301 |
| `wp-astro-forecast/includes/cron.php` | 176 | 月/季排程、新鲜度审计、仪表盘小组件 |
| `wp-astro-forecast/includes/compliance.php` | 281 | 免责声明（去重签名）、可选自动内链 |
| `wp-astro-forecast/includes/rankmath.php` | 333 | Schema 分工、JSON-LD 节点构造、`rank_math/json_ld` 接入 |
| `wp-astro-forecast/templates/`（4 件） | 307 | `astro-related-events` / `single-astro_event` / `archive-astro_event` / （`astro-event-detail` 重写） |
| `wp-astro-forecast/assets/astro-style.css` | 143 | 由 `astro.css` 改名 + 补单页/归档/面包屑/关联/内链/声明块样式 |
| `wp-astro-forecast/data/`（README + 3 样例） | 92 + 3 JSON | 指令 01 的 `/data/`；**插件不读取**，只作结构与样例 |
| `python/build_dataset.py` | 547 | 批量构建 ＋ REST 推送 ＋ `--selftest`（v1.2.0 为 14 项；**v1.2.1 扩到 16 项**） |
| `data/README.md` | 174 | 数据集目录说明（命名、字段、事件集现状、生成、推送、自测、口径提醒） |
| `docs/instruction-review.md` | 157 | 指令集校验报告 |
| `docs/execution-report.md` | 本文件 | 执行报告 |
| `docs/rank-math-config.md` / `docs/acceptance-checklist.md` / `docs/seo-config.md` | 138 / 108 / 75 | Rank Math 配置、验收清单、SEO 配置 |

### 重写

| 文件 | 关键改动 |
|---|---|
| `wp-astro-forecast/wp-astro-forecast.php` | 版本 `1.1.0→1.2.0`；Text Domain 改 `kcj-astro`；Plugin URI 改 `/sky-forecast/`；按依赖顺序 `require_once` **8 个** includes |
| `includes/activation.php` | **改薄壳**（删 `register_post_type`）；停用撤排程（对称清理） |
| `includes/shortcodes.php` | 三短代码重写；`type` 9 别名映射；新增 `kcj_astro_event_permalink()` 等 6 个助手 |
| `includes/rest-import.php` | 白名单扩展；判重键改 `date_str`；relations 走 upsert；**判返回值不判 `last_error`**；新增 `GET /freshness`；导入后同步 CPT |
| `templates/*.php`（5 件） | 链接改走 permalink 助手（不再硬编码 URL）；补 `obs_site` / `measurementTechnique`；修 `**未使用**` 字面量 |
| `sql/install_tables.sql` | `daily` 加 `special_event_ids` / 时间戳 / `uk_date_str`；`events` 加 `obs_site` / 时间戳；`relations` 加 `uk_from_to_rel`；`jd` 注释统一「TT 尺度」；**附升级前置去重语句** |
| `verify_package.py` | 818→830 行：新增 tree-sitter 真语法解析、去注释判据层、指令 01—10 覆盖度、行尾判据；负控制 **7 → 9 项** |
| `python/compute_sky.py` | 1,673→1,762 行：F17 折算、F18 常量、F19 删参、`to_json` 强制 LF、自检 27→31 项 |
| `README.md` / `docs/deploy.md` / `docs/milestones.md` / `docs/feasibility-review.md`（纯追加 F17—F21）/ `docs/verification-report.md` | 同步 v1.2.0 |

### 删除

- `wp-astro-forecast/assets/astro.css`（改名，旧名残留判据已入校验器）
- `data/` 下子代理留下的测试产物（`*.ndjson` / `events_*.json` / `manifest.json`）

---

## 五、如实声明（未做的事，不要当成做了）

> ★ **本节写于 v1.2.0 交付时。其中第 2、3 条已在后续轮次完成，原文保留以示对照，
> 当前状态见 §八（v1.2.1）、§九（事件枚举落地）。**

1. **线上首次激活未验证**。本机**无 PHP runtime**（全盘无 `php.exe`，无 xampp/wamp/laragon）⇒ 无法真跑插件。已用 **tree-sitter 真语法解析**替代（12/12 通过），但**它是解析器，不是 PHP 解释器**：不解析 `include` 图、不做类型检查、不跑运行时。**首次激活请人工盯 500。**（→ 已于 2026-09-23 完成：插件已装、`/health` 返回 200。）
2. ~~**REST 真机导入未验证**。需 WordPress 应用程序密码，本会话没有 ⇒ 端点逻辑经静态判据与 Python 侧自测，**未经真机往返**。~~
   → **已完成**（2026-09-23）：应用程序密码已生成，真机往返成功；日记录 730 行、事件 79 行全部写入。
3. ~~**未来事件集是空数组**。`compute_sky.py` **没有**「区间枚举未来事件」的接口……**缺事件时刻求根、事件级参数模块、去重与 slug 规则、人工史料条目表**四项，缺一不可。~~
   → **四项已全部补齐**（2026-09-23）：`python/event_almanac.py` 提供求根引擎 + 七个生成器 + slug 去重，
   `data/events_manual.json` 提供人工条目表机制。详见 §九。**「不编造事件」红线保持不变。**
4. **历史事件集仍是结构样例**（2 条），日期为**占位值**，`title`/`summary`/`literature`/`source_ref`
   仍为占位文本；`params_json` 内是**真算**的回推值。**这一条仍未完成** ——
   真史料靠人工逐字核录进 `data/events_manual.json`，程序不能代劳。
5. **`daily.special_event_ids` 故意留空**。该列存「指向 `wp_astro_events.event_id` 的 ID 串」，而
   `event_id` 由 MySQL 在插入时生成。要回填得推完事件再读回 slug→event_id 映射、第三轮更新 daily。
   **为了让键齐备而编号，等于伪造事件引用** —— 宁可留 `NULL`。
6. **Cron 不能自动算天象**。插件内没有 Python/skyfield/de421，WP.com 也不给 shell ⇒ 只能「到点提示」，重算推送仍需本地或站点侧执行。
7. **历史回推给的是区间不是唯一时刻**（ΔT 不确定度所致），"±1 分钟" 这类精度主张对历史条目**不适用**。
8. **`traditional`（传统天象）Tab 仍是空的**。它不是可算事件，本库**没有**生成器，只能由人工条目表
   以 `catalog` 型补入。当前前台该 Tab 显示「该类型暂无已发布事件」—— 这是**如实呈现**，不是缺陷。

---

## 六、交付判据（v1.2.0 当时实测）

```
① python/compute_sky.py --selftest          →  通过 31 项 / 失败 0      exit=0
② python/build_dataset.py --selftest        →  通过 16 项 / 失败 0      exit=0   （v1.2.0 为 14 项）
③ verify_package.py                         →  通过 178 项 / 失败 0     exit=0   （v1.2.0 为 150 项）
④ 插件包 wp-astro-forecast.zip              →  20 条目 / 57 KB 级
```

> 当前数值见 §九末「四闸复验」。

校验器 ③ 含 **23 项负控制**（注入缺陷反证检测器非空壳；v1.2.0 为 9 项），其中最关键的两项：

- **负控制⑤**：注入 PHP 真语法错，必须被 AST 检出 → 检出 `[(2, ')')]`
- **负控制⑧⑨**：URL 前缀判据必须**既非恒假也非恒真**——注入真残留会报红、注入「交代了遗留」的记述不误报

> ★ 判据设计上踩过一个坑，已修并留档：`无残留旧前缀` 这条判据起初写成「文件里出现旧前缀就算残留」，结果把它**自己那套判据的记述文档**全判红了（三份文档在描述这次变更，却被变更检测器当成变更残留）。修法不是把那几份文档塞进白名单（那会让它们真正残留时也漏判），而是把判据从**文件级**收紧到**行级**：**提及旧前缀而不同时交代「它是旧的」（旧 / OLD / legacy / 301 / 同现新前缀），才算残留。** 负控制⑧⑨ 专门锁死这个判据两个方向都不失效。

---

## 七、待用户侧动作（本会话做不了）

1. 后台 → 插件 → 上传 `wp-astro-forecast.zip` → **激活**（首次请盯 500）。
2. 访问 `GET /wp-json/kcj-astro/v1/health` 验三表是否建成。
3. 生成**应用程序密码**（用户 → 个人资料 → 应用程序密码，账号须有 `edit_posts`）。
4. 若从 v1.1.0 升级：**先跑 `sql/install_tables.sql` 末尾的去重语句**，再激活（否则历史日期会整体重复一行）。
5. 核心页面提交百度搜索资源平台；抽 10 个日期与紫金山历表交叉比对。
6. Rank Math 侧后台配置按 `docs/rank-math-config.md` 逐项照做（**标题/描述模板源码中未见前端 filter，只能后台配置**）。

---

---

## 八、v1.2.1 执行记录（线上首推修复）

**触发**：v1.2.0 安装到 `kuangchujia.com` 后，首次向 `wp_astro_daily` 推送 1 行数据失败。

**一屏看懂**

| # | 缺陷 | 证据 | 处置 |
|---|---|---|---|
| F22 | `data_version` / `dt_model` 列宽 32 < 真值 36（降级行 45） | REST 回执 `written:0, failed:1` ＋ **线上 A/B/C 边界实验**（36 拒 / 32 进 / 34 拒） | 两份正本 → `VARCHAR(64)`；`COL_MAXLEN` 补 `data_version`、`dt_model`→64；`_daily_row` 接 `_clip` |
| — | `push_rest()` 丢 `failed`/`errors[]` ⇒ 服务端拒写显示为「写入 0 行」 | 客户端输出 vs 手动 POST 回执 | 逐批打印 `errors`，`failed>0` 抛错（`exit=2` 分支此前走不到） |
| — | `dbDelta` 只在激活钩子跑 ⇒ 升级后旧列宽没人带上来 | 线上表列宽停在 32 | 新增 `KCJ_ASTRO_SCHEMA` ＋ `init` 守卫 ⇒ 重传后首访自动 ALTER |
| F23 | `event_type` 在 SQL 里 `ENUM`、在 dbDelta 里 `VARCHAR(32)` | 新列类型对拍**首跑即报红** | 统一为 `VARCHAR(32)`（以 dbDelta 为准），ENUM 取值移入 `COMMENT` |
| — | 校验器只对拍列名，不比类型/宽度（**根因**） | 150 项全绿仍上线即错 | 补列类型/列宽对拍、列宽 ≥ 实测最长值、`COL_MAXLEN` 一致性；**顺带补「zip 内容 == 磁盘」**（原先只验「文件在不在」⇒ 源件改了、zip 没重打也查不出）；负控制 9→15 |
| — | zip 手工打，文件集靠记忆、字节不可复现 | —— | 新增 `make_zip.py`（`--selftest` 证字节幂等） |

**第二批（同日 · v1.2.1 尚未上线 ⇒ 并进同一个包，不另升版本号）** —— 修完 F22 后回头审「升级路径」本身：

| # | 缺陷 | 证据 | 处置 |
|---|---|---|---|
| **F24** | `activation.php` 把**插件版本** `KCJ_ASTRO_VER` 写进 option `kcj_astro_schema_version`，而 `create()` 写的是 `KCJ_ASTRO_SCHEMA` ⇒ 同一 option 两处语义不同，取值撞车即**永久跳过 ALTER** | 静态对拍首跑即报红：写入值 `['KCJ_ASTRO_SCHEMA','KCJ_ASTRO_VER']` | 删除该写入点，表结构版本**只由 `create()` 一处落账**；判据「同一 option 的所有写入点语义必须唯一」 |
| **F25** | `create()` 跑完 `dbDelta` 就**无条件落账** ⇒ ALTER 失败也被记成「已升级」，守卫从此不再重试 | —— | 改为**逐列实测列宽**：达标才落账；不达标记 `kcj_astro_schema_error` 且**不写版本** ⇒ 下次请求自动重试（自我修复） |
| **F26** | `/health` 不暴露表结构状态 ⇒ 只能靠「推一行数据看报不报错」试错 | —— | `/health` 新增 `schema` 段（option / expected / ok / **实测列宽** / 缺口清单） |
| — | 两处 `$failed++; continue;` 不记 `$errors[]` ⇒ 只报「失败 N 行」不报原因 | 新判据扫出 2 处 | 补原因文案 ＋ 判据「每个 `$failed++` 都带得出原因」 |
| — | **我自己的两个错**：① `width_shortfalls()` 把达标项也写成缺口 ⇒ 守卫会**每次请求都跑一遍 dbDelta**；② 判据扫到**注释**里的旧写法而假报（自指陷阱） | 等价实现的负控制 ⑯⑰ ＋ 自指负控制 ㉒㉓ | ① 改「达标不加入」独立分支 ② `check_schema()` 先 `strip_php_comments_only()` 再扫 |

★ 旁证：查 WordPress 核心 `dbDelta()` 源码确认**它会改列宽**（取 `DESCRIBE` 的 `Type` 做全串比较，varchar 不命中 text/blob 与整数显示宽度两个例外）⇒ 升级路径成立，不必手工 SQL。校验器负控制由 **15 项再扩到 23 项**，总项数 **165 → 178**。

**三闸复验（本轮实测）**

```
① python/compute_sky.py --selftest         →  通过 31 项 / 失败 0     exit=0
② python/build_dataset.py --selftest       →  通过 16 项 / 失败 0     exit=0
③ verify_package.py                        →  通过 178 项 / 失败 0    exit=0
④ make_zip.py --selftest                  →  通过  7 项 / 失败 0     exit=0（打包幂等）
```

**线上实测（2026-09-23）**

- `/health` → `rows: 1`、`latest_date_str: "2026-09-23"`、`state: "fresh"` ⇒ **导入→表→新鲜度→REST 整链贯通**。
- 归档页 `/sky-forecast/` 200（56,504 B），模板与样式生效；`events: 0` ⇒ 6 组「该类型暂无已发布事件」，属预期。
- 旧 URL `/sky/forecast/` → **301** → `/sky-forecast/`。

**★ 判据设计上的一处自纠（已记入技能）**
修 F22 时第一版补的判据「产出值不超 `COL_MAXLEN` 声明列宽」**是恒真的** —— `_clip` 已先裁过一遍。
负控制当场抓出。改判**上游**：`_clip` **从不该触发**（`CLIP_LOG` 为空），触发即列宽装不下真值。

**用户侧动作 —— 1—3 已办（2026-09-23 01:37 实测）**

1. ~~重传 v1.2.1~~ **已办**：`plugin` 实测 `"1.2.1"`。
2. ~~验 `/health`~~ **已办**：`schema.ok:true`（option='2' expected='2'）、`schema.widths` = `{daily.data_version:64, events.dt_model:64}` **两项均 64**、`shortfalls:[]` —— **`dbDelta` 在 wp.com 上确实执行了 `ALTER TABLE … CHANGE COLUMN`**。
3. ~~重推 2026-09-23~~ **已办**：`written:1, failed:0`；重推一次仍 `written:1` 且 `daily rows` **仍为 1** ⇒ UPDATE 覆盖探针 B 的截断值、未插第二行。**F22 闭环（修前 `written:0, failed:1`）。**
4. ⚠ **改掉已泄露的登录密码** —— 用户 2026-09-22 报告「密码已撤消」（指此前泄露的登录密码）。
   应用程序密码实测**仍有效**（`/health` 200），推送链路未受影响。

---

## 九、事件枚举模块落地（2026-09-23 · 内容面闭环）

**触发**：线上 `/tianxiang-yugao/`（天象预告）六个 Tab **全部**显示「该类型暂无已发布事件」。
排查后确认**唯一根因**：`wp_astro_events` 表 **0 行**。表结构、模板、短代码、样式都正常 ——
缺的是**内容**。

### 9.1 交付物

| 文件 | 变化 |
|---|---|
| `python/event_almanac.py` | **新增**（约 1.5 千行）：求根引擎 + 七个生成器 + slug 去重 + 白名单行装配 + 自检/对拍 |
| `python/compute_sky.py` | 新增「事件枚举的公开访问器（v1.3.0 · 对外只读）」段：`body_ecl_lonlat(epoch=)`、`sun_body_lon_sep_deg`、`moon_sun_phase_deg`、`body_pair_separation_deg`、`body_view_state`、`calendar_jd` |
| `python/build_dataset.py` | v1.0.0 → **v1.1.0**：`build_future()` 由「输出空数组」改为真调枚举；新增 `--events-range` / `--event-kinds` / `--publish-from` / `--manual-entries` / `--allow-empty-events` / `--push-placeholders` / `--events-batch`；重写 manifest 的 `events` 段 |
| `data/events_manual.json` | **新增**（**输入**表，唯一手工编辑的文件）：人工条目表机制 |
| `data/README.md` | 重写 §二 events 字段、§三「事件集从哪来怎么补」（全新 5 小节）、§四/§五/§七/§八 |

**分工边界（写进代码注释）**：天体量一律走 `compute_sky` 的**公开访问器**；`event_almanac`
只做「求根 → 去重 + slug → 装配」，不自己算星历；`build_dataset` 只做「定区间 → 取事件 → 装配行」。

### 9.2 七个生成器与各自的判据

| 生成器 | 判据（全部可对拍） |
|---|---|
| `planet_sun` | `sin(黄经差)` 过零定根，零处再用 `cos` 别**合/冲**；内行星再以「地心距 < 地日距」分**下合/上合** |
| `planet_station` | 黄经导数**符号翻转** + 二分（不用「序列最小值索引」：平处舍入抖动会造假极值） |
| `planet_elongation` | 取 sep 的**极大**（`rate` 由正转负）；**极小是「合」不是大距** |
| `planet_pair` | 黄经差过零 + **真角距 ≤ 6°** 过滤（黄经相同 ≠ 看上去近） |
| `lunar_eclipse` | **自算**地影几何（`sep` = 月心到影轴角距的**补角口径**）；`eclipselib` 只当**定位器** |
| `meteor` | 太阳**J2000** 视黄经达该群 λ☉（λ☉ 照录 IMO/RASC，非本库自算） |
| `solar_eclipse` | **照录 NASA 目录** + 自算朔做一致性检查（本机 skyfield **无日食函数**，不自算） |

### 9.3 本轮新发现的七项缺陷（F27—F33）

| # | 缺陷 | 证据 | 处置 |
|---|---|---|---|
| **F27** | **显示字段带 Markdown 粗体标记**：2026 年 64 条里 **51 条**中招（summary 21／obs_guide 17／params 39），而 WP 端一律 `esc_html()` 直出 ⇒ 读者会看见两个字面星号 | 逐字段统计 + v1.2.0 模板注释里修过**同一类**写法 | 出口一次清：`to_rows()` 统一过 `_plain()`（含 params 递归）+ 构建期判据 + 两向负控制 |
| **F28** | **流星雨 λ☉ 历元用错**：IMO/RASC 表头明写 **λ 2000**（J2000 黄道），用 `epoch="date"` 求根 ⇒ 2026 年系统性偏 **0.363° ≈ 8.8 小时** | 对拍残差 0.241° 不收敛 | `body_ecl_lonlat` 加 `epoch` 参数；流星雨改 `epoch="j2000"`；修后偏差 **0.000060°** |
| **F29** | **内行星大距一年多出一倍**（水星 12 次，真值 6 次；半数时刻 sep 只有 0.18°—4.9°） | 两向判据（每年恰 6 次 + 所有大距距角 ≥ 17°） | **驻点的种类要另外判**：只取 `rate` 由正转负的**极大**。极小＝合（sep≈0） |
| **F30** | **月食 `sep` 取成补角外的那一侧**（食甚处 3.1353 rad 而非 0.0063）⇒ 食分巨大负数、**接触时刻一个根都找不到**（字段全空） | 食甚处 sep 判据 | `sep = π − sep(moon, sun)`；新增 `refine_greatest()`；`gen_lunar_eclipses` 重写为单一几何 |
| **F31** | **负控制「不触发」暴露出检查的真空洞**：① `import event_almanac` 拿到的是**第二个副本**（直跑时模块名是 `__main__`）；② 日食生成器在 ±2 天找不到朔时**静默放行** | 负控制报「未触发」 | 改 `sys.modules[__name__]`；窗口扩到 ±3 天且**找不到朔直接 raise**；并加**正控制**（复原后必须放行，否则判据恒真） |
| **F32** | **参考值抄错**：土星冲日写成 2026-09-22，真值 **2026-10-04** —— 而**自算值一直是对的** | 对拍报红差 12 天 | 全网检索四源确认（香港天文台／台北天文馆／科普中国／青年日报）后改为官方表 12 条；留档「报红时**先怀疑参考值**，两边都要有出处」 |
| **F33** | **预告列表无「仅未来」过滤**：SQL 只有 `WHERE event_type=%s AND publish_status=1 ORDER BY jd_core ASC` ⇒ 已过去的事件排在最前，页面显得过期 | 读 `includes/shortcodes.php` | 新增**发布窗口** `--publish-from`（默认今天）：窗口外**不落地**，剔除数记入 manifest |

另有四项**自纠**（都发生在动手之后、上线之前），单独记在 `docs/feasibility-review.md`：
① `_hhmm_to_sec` 丢秒位（`'11:34:52'` 读成 `11:34:00`，对拍残差由恒定 −71 s 变成散乱值，**看上去像自算不稳**，实则参考值被读错）；
② docstring 写「与 eclipselib 差 < 1e-6 弧度」，实测 **1.07e-5**（光行时迭代所致）⇒ **声明精度前先量**；
③ 库龄标签写成「同一时点应绝对相同」是**不可达标准**（月食定位依赖搜索区间，跨窗口有 ~1 秒抖动）⇒ 改为「≤3 秒」；
④ `_td_to_bj()` 初稿构造/反解 UTC 的中间量算错（日食 vs 自算朔差 −12.02 小时）⇒ **检查本身按设计拦住了我**。

### 9.4 三个时刻尺度 · 两个历元 · ΔT 双轨（三条最易错的口径）

1. **三个尺度**：`jd_core` 一律 **TT**；`event_time_bj` 一律**北京时间（UTC+8）**；
   与 NASA 目录对拍时要知道它表头写的 **TD = TT**，不是 UT —— 直接当 UT 用会凭空差 **69 秒**。
2. **两个历元**：**绝对黄经**必须 `epoch="date"`；而「黄经**差**」里岁差**会抵消**（实测 ≤0.0006°），
   流星雨 λ☉ 表头是 J2000 ⇒ 必须 `epoch="j2000"`。
3. **ΔT 双轨**：项目自带模型（Espenak-Meeus 2006）在 2026—2030 给 **63.0 s**，skyfield 时刻尺度
   实际 TT−UT1 是 **69.1 s**，差 6.1 s ⇒ 事件模块**只走一条路**，不与 `compute_sky.delta_t_seconds()` 混用。

### 9.5 线上实测（2026-09-23 02:24）

```
推 送：daily 730/730 行（4 批）｜events 79/79 行（4 批，25 行/批）｜cache_flush ok
/health        →  events.rows = 79（此前 0）｜daily.rows = 730｜schema.ok = true
预告页          →  HTTP 200（92,598 B，此前 53,410 B）｜「暂无」由 6 处降到 2 处
                  Tab 渲染：日食 4／月食 5／行星天象 84／流星雨 30／传统天象 暂无／历史天象 暂无
事件详情页      →  HTTP 200（44.5 KB）：H1、北京时间、计算口径、天文参数表、观测指南、免责声明齐备
                  正文**无字面 `**`**（F27 已闭环）
CPT 文章        →  X-WP-Total: publish = 79、draft = 0（占位条目按设计未推送）
假 slug 探测    →  HTTP 404（真路由）
```

**发布窗口**：区间 2026—2027 共枚举 **123** 条，窗口（`2026-09-22` 起）外剔除 **44** 条 ⇒ 落地 **79** 条。

### 9.6 本轮**不做**的事（如实声明）

1. **`traditional` 仍无生成器** —— 它不是可算事件，只能由人工条目表以 `catalog` 型补入。该 Tab 仍空。
2. **历史事件仍是 2 条占位样例**，未推送。真史料靠人工逐字核录。
3. **`daily.special_event_ids` 仍留空**（理由见 §五 第 5 条）。
4. **不做全量 5.5 万天** —— 是否推送全量历史日记录需先确认 wp.com 数据库配额，未验。
5. **事件详情页「天文参数」表的键名仍是英文**（`catalog_date_ut`、`contact_bj`…）。
   这是 v1.1.0 模板既有设计（机器可读、跨语言稳定），本轮**未改**：
   改键名要动插件模板 ⇒ 用户须再传一次包。**记为可选改进项。**

### 9.7 四闸复验（本轮实测）

```
① python/compute_sky.py --selftest             →  通过  31 项 / 失败 0    exit=0
② python/build_dataset.py --selftest           →  通过  51 项 / 失败 0    exit=0（v1.2.1 时 16 项）
③ python/event_almanac.py --selftest           →  通过 227 项 / 失败 0    exit=0
④ python/event_almanac.py --verify             →  对拍  57/57 项通过      exit=0
⑤ verify_package.py                            →  见下节（本轮已补事件判据）
```

**对拍 57 项**＝甲 月食 12 条×3（NASA）＋乙 流星雨 λ☉（IMO/RASC 三源）＋丙 日食（NASA 目录 vs 自算朔）
＋丁 行星 12 条同日（香港天文台 2026 行星观测资料）＋戊 月食七阶段接触时刻（台北天文馆，残差 +92…−110 秒，
**恒定偏移正是 TT−UTC 的 69 秒**，证明是尺度差而非算法差）。

**本轮的插件包未变** ⇒ `wp-astro-forecast.zip` 指纹不变，**用户无需重传**。

### 9.8 面板配置前的线上 SEO 复核（2026-09-23 03:2x）

用户问「这 6 项在面板哪里」⇒ 先抓五张真实页面的 `<title>`／description／JSON-LD 做对照，结果：

- **`Dataset` 那一路已通**：预告列表页与老黄历页均输出 `WebPage + Dataset`（插件自出，符合分工）。
- **`Event` 一路全缺**：单条事件页**整页零 JSON-LD** —— 根因是**分工协议双方都以为对方在做**
  （文档说插件自出，代码 `kcj_astro_schema_should_emit('Event')` 在 Rank Math 启用时返回 `false`）。记 **F35**。
- **描述模板也无人分流**（文档说插件按 `method` 注入，代码明写「不擅自 hook」）。记 **F36**。
- **分类法归档路径式不可达**（`?event_type=planet` 200，`/sky-forecast/planet/` **301** 到不相干事件）。记 **F34**，
  根因＝CPT 与分类法共用 rewrite slug，`register_post_type()` 遮蔽 `register_taxonomy()`。

**面板清单据此由 6 项更正为 7 项**（−1「两份 Description」＋2「Archive Description」「Schema Type = Event」），
且 **taxonomy sitemap 一项改为暂缓**（开了等于把 301／404 交出去）。

**本轮的插件包仍未变** ⇒ `wp-astro-forecast.zip` 指纹不变，**用户无需重传**；
F34 的修法（分类法 slug 独立成段）登记为**随下次插件改动一并提交**。

### 9.9 结构化数据归属修正（2026-09-23 · v1.3.0 · **包已改，须重传**）

**起因**：用户在 Rank Math 面板把 `Titles & Meta → Post Types → 天象事件 → Schema Type` 选成 `Event` 并保存，
但取线上事件详情页 head，`ld+json` 块数仍是 **0**。

**排查（四路排除 → 差分 → 源码定谳）**

1. 排除「没保存 / 改在保存之后」：① Single Title、③ Archive Title、④ Archive Description **同批保存且均已生效**。
2. 排除「缓存 / CDN」：随机查询串 ＋ `Cache-Control: no-cache` 两轮复测一致。
3. **逐类页面差分**（`application/ld+json` 块数）：普通文章单页 **1** ／ 普通页面单页 **1** ／ CPT 归档 **1** ／ 首页 **1** ／ **CPT 事件单页 0** ⇒ 只限 `astro_event` 单页这一类。
4. **两页 head 逐条对照**：事件页 `og:*`(13) / `twitter:*` / `canonical` / `robots` **全在**、`<title>` 正是 Rank Math 按 ① 渲染的，**独缺 `class="rank-math-schema"` 那个块**（归档页有）⇒ 问题在 **Schema 输出环节**，与「Rank Math 没认这个 CPT」无关。
5. **读源码定谳**（下载 `rankmath/seo-by-rank-math` master 分支核对，非推测）：
   `helpers/class-schema.php::get_default_schema_type()` **L70** 在 `$return_valid` 为真时**只认 Article 家族五种**
   ⇒ `Event` 返回 `false`；而 `snippets/class-singular.php::get_default_schema()` **L104** 传的正是 `true`；
   又 `class-jsonld.php::can_add_global_entities()` **L379/L394** 因此在事件页判负
   ⇒ **连 Person / WebSite / ImageObject / WebPage 一起消失**；最后 `json_ld()` 的 `if ( empty( $data ) ) { return; }`
   ⇒ **一个 `<script>` 都不输出**，与实测逐字吻合。

**改了三处（v1.3.0）**：① `$only_mine` 加入 `'Event'` ＋「已有 `rank_math_schema_*` 时让位」判据；
② 回调优先级 **20 → 5**（抢在 `add_context_data` 的 10 之前 ⇒ `! empty( $data )` 成立 ⇒ 站点级实体恢复）；
③ `daily` 分支加**日期守卫**（原来会输出日期为空的 `Dataset`，线上首页/博文/老黄历页各挂一个，**F38**）。

**新增本机能力**：便携 PHP CLI（解压即用）＋ **第五闸 `php_selftest.py`**
（`php -l` 语法闸 15 个文件 ＋ WordPress 钩子桩测试 **30 项**，含 3 项负控制与 6 项回退路径断言）。
—— 本项目此前**没有任何 PHP 层判据**，插件代码从未被执行过一次。

**复验（五闸 + 打包幂等，全部 exit=0）**

| 闸 | 结果 |
|---|---|
| `php_selftest.py` | **30 / 0**（语法 15 个文件全过） |
| `verify_package.py` | **216 / 0**（本回合 +1：PHP 层判据落点存在性；**同日线上验收轮再 +2**：`live_verify.py` 落点 ＋ 其语法闸） |
| `build_dataset.py --selftest` | **51 / 0** |
| `event_almanac.py --selftest` | **227 / 0** |
| `make_zip.py --selftest` | **7 / 0**（连打两次字节相同） |

**包指纹**：`wp-astro-forecast.zip` **63,657 B ｜ SHA1 `615314a71f38f62b77e768997e948e339b90e579`**（上一版 61,190 B ／ `8351956…`）。
**本轮插件包已改 ⇒ 用户须重传一次**；表结构未变（`KCJ_ASTRO_SCHEMA` 仍为 2），**无需重新激活、无需 SQL**。
上传后验收见 `docs/deploy.md` §1b（**改成跑一条 `python live_verify.py`**，九项判据 A—I）。
**同日线上三轮实测**：D—I 全绿（事件页 `Event` **79/79**、`startDate` 全带 `+08:00`、站点级实体缺失 0、
扫描面 **100 页**无空日期 `Dataset`、`/tianxiang-yugao/` 的完好 Dataset 仍在、归档页 `CollectionPage` ✅）。
第一轮曾报 **B／C 事件 sitemap 404**，**第二轮查明是「查询式通、路径式不通」**（⑥ 其实已生效；
**F41**＝Rank Math sitemap 重写规则未进 `rewrite_rules`，全站漂亮路径全 404）；
**第三轮用户按一次「固定链接 → 保存更改」（flush 重写规则）后 B2 转 200/200** ⇒
**`live_verify.py` 通过 9 ／ 跳过 1 ／ 不通过 0（exit=0）**。另新增 F39（标量被核心串化）、
F40（「让位」安全性定谳）、F41（已修复）、**第四处自纠**（探针 URL 拼接 bug 造出 79 条假红）与
**第五处自纠**（判据扫描面取自坏索引 ⇒ 静默缩水仍报绿）→ `docs/feasibility-review.md`。
**本轮不动插件代码 ⇒ 包指纹不变**（仍 `63,657 B`／`615314a7…`）。

**同轮未做（如实声明）**：F34（分类法 rewrite slug 独立成段）**仍随下次改动一并提交** —— 它要动 rewrite 规则，
而本机无法验证 WordPress 的重写解析，收益（分类归档路径式可达）此刻又不成立（⑦ 已暂缓），故不冒这个险；
`CollectionPage` 的 `hasPart` 同理留待下次。

---

*指令集校验见 `docs/instruction-review.md`；核对明细见 `docs/verification-report.md`；可行性复盘见 `docs/feasibility-review.md`。*

---

## 十、v2.0.0 执行记录（2026-09-23 · 观测地维度与三个子项）

### 10.1 用户令与拆解

> 「**进行新任务：天象预告为父项，下设3个子项：子1：今日天象，观测地默认为IP当地并可选，
> 子2：未来天象预告，需求汇总月、季、年度天象报告，供我下载，子3：历史上今日天象，
> 历史上当天的天象显示在页面上，并汇总报告，供我下载。现在执行，遇到不决的问题，
> 你自行检索后决定，不必问我。**」
>
> 后追加：「**3个子项以三个栏目的样式体现，不能做成菜单**」

### 10.2 四条自行裁定（用户授权「自行检索后决定」）

| # | 问题 | 裁定 | 依据 |
|---|---|---|---|
| 1 | 报告「供我下载」怎么落地 | **浏览器内即时生成**（MD/CSV/打印），零后端零凭据 | 站点 REST 一律 **401**（凭据已撤消）⇒ 后端生成不可行 |
| 2 | 观测地怎么扩 | **另开第 4 张表**，而非给日表加列 | 日表 40 余项里**只有 11 项**与观测地有关，其余是地心量 |
| 3 | IP 定位在哪做 | **前端**做，且只从页面已嵌的 38 城坐标里取最近 | 前端零硬编码、零天文计算 ⇒ 与 Python 侧不会漂移 |
| 4 | 历史天象能自算什么 | **只做月食**；日食**必须照录、不得自造** | 本机 skyfield 无日食函数，目录只覆盖 2026—2030 |

### 10.3 顺带修掉的三个真缺陷（详见 `feasibility-review.md`）

| 编号 | 缺陷 | 一句话 |
|---|---|---|
| **F42** | 升落窗口把 **UTC 日**当北京日 | 口径错 ＋ 西陲城市（乌鲁木齐/拉萨）**静默返回 `None`** |
| **F43** | 地平线口径少了**太阳视半径** | 全体系统性偏移 **1.4 分钟**（−0.5667° 应为 −0.8333°） |
| **F44** | 「未来十二个月」两处实现**差一天** | 闰日附近分岔（`+365 天` / `strtotime` 各错一半） |

外加 **F45**：**一条判据自己写错了**（「最长月全食 = 2018-07」）——
自算 106.6 分钟与 NASA 的 106.4 分钟只差 0.2 分钟，**是判据错，不是代码错**。

### 10.4 文件变更

**新增**：

| 文件 | 行数/大小 | 作用 |
|---|---|---|
| `python/build_site.py` | 约 460 行 | 观测地维度数据集（38 城 × 北京日，出 NDJSON ＋ SQL） |
| `python/history_events.py` | 415 行 | 历史天象回推（**只做月食**） |
| `python/gen_astro_report.py` | 391 行 | 月/季/年度报告离线生成（md ＋ 单文件 HTML） |
| `wp-astro-forecast/templates/astro-history-today.php` | 7.7 KB | 历史上今日天象版式 |
| `wp-astro-forecast/templates/astro-forecast-report.php` | 6.5 KB | 报告版式 |
| `wp-astro-forecast/templates/astro-hub.php` | 约 4 KB | **三栏目外壳（无脚本）** |
| `wp-astro-forecast/assets/astro-place.js` | 8.4 KB | 观测地切换（IP → 最近城） |
| `wp-astro-forecast/assets/astro-report.js` | 6.4 KB | 报告下载（MD / CSV / 打印） |
| `docs/deploy-hub.md` | 169 行 | **三栏目装配说明 ＋ 可粘贴正文** |

**改动**：`compute_sky.py`（38 城、别名表、F42/F43、观测地维度层）、
`class-astro-db.php`（+第 4 张表）、`sql/install_tables.sql`（+表 4）、
`rest-import.php`（+白名单、**复合判重键**）、`shortcodes.php`（+3 个短代码、
+2 个属性、`[astro_hub]` 栏目外壳）、`astro-style.css`、`verify_package.py`、
`php_selftest.py`、`make_zip.py`、四份 docs、三份 README/data-README。

### 10.5 交付物

| 件 | 状态 |
|---|---|
| `wp-astro-forecast.zip` | **25 条目 / 91,490 B / SHA1 `b8d07da7…`** |
| 建表 SQL / NDJSON | `python/build_site.py` 与 `history_events.py` 产出（**待推库**） |
| 三栏目装配说明 | `docs/deploy-hub.md`（含可粘贴正文 `[astro_hub]`） |

### 10.6 待用户侧动作

1. **重传插件 zip**（后台 → 插件 → 上传 → 替换）。
2. **打开「天象预告」页，正文整段换成 `[astro_hub]`**。
3. **不要**为三个子项新建菜单项。
4. **数据入库**：重新签发应用密码（推荐）或手工导 SQL。


---

## 十一、v2.1.0 执行记录（2026-09-23 · 三栏目装配 ＋ 历史栏目扩族）

### 11.1 用户令与拆解

| # | 原话 | 落地 |
|---|---|---|
| 1 | 「**3个子项以三个栏目的样式体现，不能做成菜单**」 | 该外壳（`[astro_hub]` ＋ `astro-hub.php` ＋ 纯 CSS 切换）**在 v2.0.0 轮已落地**（见 §10.4）；**v2.1.0 沿用**，并纳入本轮判据 |
| 2 | 「遇不决的问题，你自行检索后决定，不必问我」 | 五处自行裁定（见 §11.2） |

### 11.2 五条自行裁定

| # | 问题 | 裁定 | 依据 |
|---|---|---|---|
| 1 | 栏目切换用 JS 还是 CSS？ | **纯 CSS**（隐藏 `radio` ＋ `label` ＋ `:checked ~`） | 平台后处理会拆断内联脚本（`wpautop` 换空行、裸 `&` 换实体引用）⇒ JS 随时整块失效 |
| 2 | 三栏内容 JS 按需加载还是全在 DOM？ | **全在 DOM**，只 `display:none` | 搜索引擎与「页面内查找」都能看到另两栏 |
| 3 | 「历史上今日」只盖 36.3% 的日子，怎么办？ | **扩族**到月食＋流星雨＋行星天象 | 覆盖率是**产品判据**；先量后改（F46） |
| 4 | 历年重现的同类天象（如 126 条英仙座）怎么排？ | **成组折「年份清单」＋ 最近一次明细**（组内 ≥6 条才折） | 逐条列卡片会把页面刷爆；月食一天最多 4 条 ⇒ 逐条、明细不丢 |
| 5 | 日食既然是 0 条，要不要从默认族里删掉？ | **保留在默认族** | 保留才会打出「该族未录入 ⇒ 不能据此说这一天没有」这句如实说明；删了等于把「没查」藏回「没有」 |

### 11.3 本轮修掉的五处缺陷

见 `feasibility-review.md` 的 **F46—F50**（覆盖率 36.3% / 年率判据用印象值 / 分组键一刀切 / 跳转非闰年基准 / 模板写 markdown 粗体）。

### 11.4 文件变更

| 文件 | 变更 |
|---|---|
| `python/history_events.py` | v1.0.0 → **v1.1.0**：`FAMILIES` 三族 ＋ `FAMILY_GENERATORS` ＋ `unc_and_site()` ＋ `--types`；`check()` 改逐族年率、加 ⑥⑦ 两条；`selftest()` 三族真算 ＋ 7 条负控制 |
| `wp-astro-forecast/includes/shortcodes.php` | 新增 `[astro_hub]`；抽出 `kcj_astro_history_group_key()` / `kcj_astro_history_nav()` 两个模块级函数；`[astro_history_today]` 默认族扩到四族、加 `?kcj_md` 与 `nav` |
| `wp-astro-forecast/templates/astro-hub.php` | **v2.0.0 轮建**（三栏目外壳，无脚本）；v2.1.0 **沿用** |
| `wp-astro-forecast/templates/astro-history-today.php` | 成组渲染（`$GROUP_MIN = 6`）＋ 跳转条 |
| `wp-astro-forecast/assets/astro-style.css` | 新增 `.kcj-astro-history-nav*` / `.kcj-astro-history-group*`；`@media print` 加隐藏跳转条与 `break-inside: avoid` |
| `wp-astro-forecast/wp-astro-forecast.php` | 版本 **2.0.0 → 2.1.0**（`KCJ_ASTRO_SCHEMA` 仍 `3`） |
| `php_selftest.py` | 桩加 `add_query_arg()`；新增 `history_helpers` case ⇒ **34 项** |
| `verify_package.py` | 新增三个规则谓词 ＋ **＋20 条判据**（历史栏目扩族 ＋ 三栏目外壳）＋ 负控制 ㉞㉟㊱ ⇒ **308 项** |
| `docs/*` | `deploy-hub.md`（＋§九 v2.1.0）、`feasibility-review.md`（＋F46—F50）等同步 |

### 11.5 交付物

| 件 | 状态 |
|---|---|
| `wp-astro-forecast.zip` | **25 条目 / 95,379 B / SHA1 `596d5d491de485d12f03d5f4f066d2015cf0143e`** |
| `data/events_past.json` | v2.0.0 月食版 **288 条**；**v2.1.0 三族版已完成：4,672 条 / 1,831 s / sha1 `0fc2acdb01ec`（**正文口径**；整档 `f6686d52ab69`）**（8,158,089 B） |
| 三栏目装配说明 | `docs/deploy-hub.md`（含可粘贴正文 `[astro_hub]` 与 **10 条**页面验收判据） |

### 11.6 待用户侧动作

1. **重传插件 zip**（后台 → 插件 → 上传 → 替换）—— 本轮的短代码／模板／CSS 都在包里。
2. 「天象预告」页正文整段换成 `[astro_hub]`（若 v2.0.0 已换过，**本次无需再改**）。
3. **不要**为三个子项新建菜单项。
4. **数据入库**：重新签发应用密码（推荐）或手工导 SQL（**历史事件待三族全量算完后一次性推**）。

### 11.7 本轮一条教训

**判据的数值必须来自实测，不能来自注释里的印象。**
（F47：行星年率按旧注释的印象估成 `[20, 60]`，实测 **19.66** ⇒
若照此跑 126 年全量，会在**算完 38 分钟后**当场报红、拒绝写盘。）
