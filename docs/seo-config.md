# SEO 与结构化数据配置（Rank Math 专项）

依据：用户《WordPress 站点天象模块落地指令集》指令 07 / 指令 10

详细逐屏配置见 docs/rank-math-config.md

站点 kuangchujia.com ｜ 主题 Seedlet ｜ 托管 WordPress.com（不允许编辑主题文件）
本文件只保留**总表与口径**：四类页面的 Schema 定谳、canonical／hreflang／OG 规则、robots、`llms.txt`、meta 规则摘要。

---

## §1 Schema 定谳总表（四类页面）

| 页面 | 采用类型 | 关键字段 | 落地位置 |
|---|---|---|---|
| 今日天象（老黄历页内嵌） | `WebPage` ＋ 子节点 `Dataset` | `name` / `dateModified` / `about`(Place+GeoCoordinates) / `temporalCoverage` / `creator` / `license` | 插件模板自出 JSON-LD |
| 未来一次性天象事件 | `Event` | `name` / `startDate`(ISO8601+08:00) / `eventAttendanceMode=OfflineEventAttendanceMode` / `location`(Place+GeoCoordinates) / `description` | 插件模板自出 JSON-LD，同时可在 Rank Math 面板选 Event |
| 历史天象事件 | `ScholarlyArticle` | `headline` / `datePublished` / `author` / `citation` / `about` / `temporalCoverage` | 只能插件模板自出 JSON-LD（Rank Math 免费版无此类型） |
| 预告列表／归档页 | `CollectionPage` | `name` / `hasPart`(各事件 `Event`) | Rank Math 面板可选 CollectionPage（免费版有） |

**红线**

- **不得**出现 `AstronomicalObject`／`Calendar` —— 经 schema.org 官方词表 release 29.0 的 TTL 逐字核对，两个类型均**不存在**（词表全文出现 0 次），校验器会报错。原指令「今日天象页面启用 Calendar + AstronomicalObject」属事实性错误，已改。
- **不得**给每日更新的「今日天象」套 `Event` —— 属结构化数据滥用。
- `ScholarlyArticle`／`Dataset` 在 Rank Math 免费版均无（Custom Schema 仅 PRO），故一律由插件模板自出 JSON-LD。

---

## §2 URL 与规范链接口径

| 项 | 口径 |
|---|---|
| 归档 | `/sky-forecast/` |
| 详情 | `/sky-forecast/{slug}/` |
| 旧路由 | 旧版双段路由（`/sky` 下的 `forecast` 子路径）及其详情设 **301** 跳转到 `/sky-forecast/` 对应 URL |
| canonical | 每页输出唯一 `canonical`，指向自身规范 URL（不带查询串） |
| hreflang | **由 `includes/hreflang.php` 自动输出**（v2.3.7 起）。三类页面三种处理，见下 §2.1 |
| 历史天象 | 作为同一列表页的一个 Tab 落位，**不另开路由** |
| sitemap 分组 | 只认 `/sky-forecast/` 一套（归档 ＋ 详情）；不另起与 CPT 归档重写规则冲突的第二套路由。中英分图分别提交百度资源平台与 Google Search Console |

---

## §2.1 hreflang 落地口径（v2.3.7）

**为什么由插件做**：Rank Math 免费版没有可编程的 `hreflang` 面（其 hreflang 能力属
PRO 或需后台逐页配置）。本插件直接在 `wp_head`（优先级 1）输出，与同文件的
JSON-LD 输出（优先级 20）互不干扰 —— 两者输出的是不同标签名。

**三类页面三种处理**：

| 页面类型 | 输出 | 理由 |
|---|---|---|
| **语言子页**（同一父页下 slug 为 `zh` / `en` 的两页） | `zh-CN` → 中文页、`en` → 英文页、`x-default` → **中文页** | 站点主受众为中文读者，与 `locale` 一致；这是**口径选择**，非技术必然 |
| **父栏目页 / 列表页** | **只出 `x-default` 指自身** | 它是「同 URL 内双语 Tab 单页」，并非 en/zh 之一。若强行出 `zh` 亦指自身，等于声明「本页是中文版」而它同时是英文版 ⇒ 反向失真 |
| **首页 / 归档 / 普通页** | **只出 `x-default` 指自身** | 不属于任何语言组，出了是噪音 |
| **配对不齐**（只有 zh 没有 en，或反之） | 只出 `x-default` 指自身 | 单侧 hreflang 会被整体忽略，宁缺勿造 |

**★ 配对按「父页 ＋ slug」自动判定，不写死页面 ID。**
取当前页的 `post_parent`，在其下找 `slug === 'en'` 与 `slug === 'zh'` 的子页；
两者俱全才判为语言对。WordPress 保证同父同级 slug 唯一 ⇒ 配对是确定性的。
写死 ID 表（如 `585/592`）会在站点改版时**静默失效** —— 本项目已因此踩过一次
（某个维护脚本写死 `PAGE_ID = 29`，站点改版后每日定时任务当场断言失败）。

**★ 不得写成「三条 href 同值」。**
`hreflang` 是**双向契约**：A 页声明 B 是它的英文版，B 页也须声明 A 是它的中文版。
三条 `href` 全指同一 URL ＝ 声明「中英两版同 URL」，会被判为自指重复、
**整组忽略**，还可能反过来污染原页的语言判定。本实现按「每页只声明自己所在
那一组」写，天然满足双向。

**边界**：本模块**不写 `canonical`、不写 `robots`** —— 那是 SEO 插件的面，不越界。

**验证**（本机离线，零联网）：
```bash
php _g_harness_c282.php     # 行为级：三类页面 ＋ 单侧残缺 ＋ 非页面，共 9 例
python _verify_c282_hreflang.py   # 结构级：13 条判据
```
⚠ 桩必须给 `ABSPATH`（否则被 require 的插件文件会静默 `exit`，脚本零输出、
退出码却是 0）与 `add_action`（否则致命错误）。这是本项目踩过的坑，第二次。

---

## §3 meta 规则摘要

- **标题模板**：`%title% ｜ 天象预报 · 华夏古天文历法实证记录`
- **描述模板（按 `method` 分流，不得混用）**：
  - 未来页（**星历精算**，`method=ephemeris_de421`）：「{事件名} 将于 {北京时间} 发生；基于 JPL DE421 星历精算，仅供天文观测参考。」
  - 历史页（**星历精算**）：「{文献记载} 现代星历回推与史料对照，附 ΔT 不确定度区间。」
  - 历史页（**解析降级**，`method=analytic_meeus`）：须如实改写为「早于现代星历覆盖区间，以 Meeus 解析式近似回推，附 ΔT 不确定度区间。」
    —— **不得沿用「星历回推」措辞**，否则构成**虚假溯源**（见 `docs/feasibility-review.md` F12）。
- **焦点关键词**：未来天象用「{年份}年{事件名}」，历史天象用「{年份}历史天象回推」；事件名须与 `wp_astro_events.title` 逐字一致。
- **OG / Twitter Card**：全站补 `Open Graph` 与 `Twitter Card`；描述与上述 meta 描述同源，不另写一套口径。

---

## §4 robots 与 llms.txt

| 项 | 口径 |
|---|---|
| robots | `index,follow`（天象模块页面不设 noindex） |
| `llms.txt` | 站点级声明本模块为**天文科普**，不含占星／运势／吉凶／谶纬内容 |
| 合规联动 | 违禁词扫描与免责声明检查见 `docs/acceptance-checklist.md` §3；提交收录前须先过合规 |

---

## §5 校验与收录提交（速查）

| 步骤 | 工具 | 判据 |
|---|---|---|
| 1 | Google Rich Results Test（四类页面各一条 URL） | 无类型报错；无 `AstronomicalObject`／`Calendar` |
| 2 | 百度结构化数据校验 | 同上 |
| 3 | Google Search Console | 提交 sitemap，中英分图各一条 |
| 4 | 百度资源平台 | 重新提交站点地图 ＋ 手动提交核心页 |

> 逐屏字段与菜单路径，一律以 `docs/rank-math-config.md` 为准；本文件不重复其内容。
