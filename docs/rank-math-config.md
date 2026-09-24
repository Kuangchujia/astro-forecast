# Rank Math 配置（天象模块专项）

依据：用户《WordPress 站点天象模块落地指令集》指令 07 / 指令 10

站点 kuangchujia.com ｜ 主题 Seedlet ｜ 托管 WordPress.com（**不允许编辑主题文件**）
插件 `wp-astro-forecast/`（主文件 `wp-astro-forecast.php`，Text Domain `kcj-astro`，版本 **1.2.1**）

> 结论先行：**指令集原文有两处事实性错误必须先改，再谈配置。**
> ① Schema.org 词表里**不存在** `AstronomicalObject` 与 `Calendar`，指令要求「今日天象页面启用 Calendar + AstronomicalObject」属事实性错误；
> ② `ScholarlyArticle` **不在 Rank Math 免费版的下拉类型里**，且「Custom Schema（任意类型）」仅 PRO 所有，
> 所以历史天象的结构化数据**不能指望 Rank Math**，改由插件模板自出 JSON-LD（我们完全可控、免费）。
> 配置的正确顺序是：先按 §0 纠正事实，再按 §1 定谳类型，最后按 §2 逐屏落面板。

---

## §0 三条事实纠正

### 纠正 1 —— Schema.org 不存在 `AstronomicalObject`、`Calendar`

| 项 | 内容 |
|---|---|
| 指令原文 | 「今日天象页面：启用 Calendar + AstronomicalObject Schema」 |
| 实测／查证结果 | 下载 schema.org 官方词表 release 29.0 的 TTL 逐字核对：`AstronomicalObject`、`Calendar`、`Planet`、`Star`、`Constellation` **在词表全文中出现 0 次**。词表内**确实存在**的是：`Event`(subClassOf Thing)、`Article`(CreativeWork)、`ScholarlyArticle`(Article)、`Dataset`(CreativeWork)、`Report`(Article)、`CreativeWork`、`Place`、`GeoCoordinates`(StructuredValue)、`Schedule`(Intangible)、`Observation`(Intangible)、`WebPage`(CreativeWork)、`CollectionPage`(WebPage)、`VisualArtwork` |
| 本文采用的替代方案 | 今日天象页用 `WebPage` ＋ 子节点 `Dataset`；未来一次性事件用 `Event`；历史天象用 `ScholarlyArticle`；列表／归档页用 `CollectionPage`。**全站不得出现 `AstronomicalObject`／`Calendar`**（类型不存在，校验器会报错） |

### 纠正 2 —— Rank Math 免费版给不了 `ScholarlyArticle`

| 项 | 内容 |
|---|---|
| 指令原文 | 隐含「用 Rank Math 为历史天象输出 `ScholarlyArticle` 结构化数据」 |
| 实测／查证结果 | 依 Rank Math 官方文档页所列类型清单：**免费版有** Article、Book、CollectionPage、Course、Event、FAQ、HowTo、JobPosting、Music、Person、Person or Organization、Product、ProfilePage、Recipe、Restaurant、Service、SoftwareApplication、Video、WebPage、WebSite、BlogPosting、Breadcrumb、NewsArticle、LocalBusiness、WooCommerce、Sitelinks Search Box、SiteNavigationElement；**仅 PRO 有** Dataset、FactCheck、Movie、PodcastEpisode、About and Mentions、ItemList、Carousel、Q&A、Speakable；**「Custom Schema（任意类型）」仅 PRO**。⇒ `ScholarlyArticle` 免费版下拉里**没有**，且 Custom Schema 要 Pro |
| 本文采用的替代方案 | 历史天象的 `ScholarlyArticle` **改由插件模板自出 JSON-LD**，不依赖 Rank Math；同为 `Dataset` 的今日天象页亦走插件输出（免费版无 Dataset）。Rank Math 只承担它免费版真有的类型与功能（`Event`、`CollectionPage`、标题／描述模板、sitemap、面包屑） |

### 纠正 3 —— GB/T 33661 的效力范围没有覆盖「月相精度」

| 项 | 内容 |
|---|---|
| 指令原文 | 隐含「月相／回推精度符合 GB/T 33661—2017」 |
| 实测／查证结果 | GB/T 33661—2017《农历的编算和颁行》（Calculation and promulgation of the Chinese calendar），发布 2017-05-12、实施 2017-09-01、起草单位中国科学院紫金山天文台、**现行有效**。内容范围为农历的**编排规则、计算模型和精度、表示方法、颁行要求**；附录 A 二十四节气（**规范性**附录）、附录 C 六十干支周（**规范性**附录），附录 B/D 为资料性附录。⇒ 该标准**不规定月相公布精度** |
| 本文采用的替代方案 | 可主张「**农历日期与二十四节气的编排**符合 GB/T 33661—2017」；**不得**主张「**月相精度**符合该标准」。月相精度声明只能引本模块自身的对拍依据（与 skyfield 相位根求解对拍），不得借国标抬高口径 |

---

## §1 Schema 定谳表（四类页面）

| 页面 | 采用类型 | 关键字段 | 落地位置 |
|---|---|---|---|
| 今日天象（老黄历页内嵌） | `WebPage` ＋ 子节点 `Dataset` | `name` / `dateModified` / `about`(Place+GeoCoordinates) / `temporalCoverage` / `creator` / `license` | 插件模板自出 JSON-LD |
| 未来一次性天象事件 | `Event` | `name` / `startDate`(ISO8601+08:00) / `eventStatus` / `eventAttendanceMode=OfflineEventAttendanceMode` / `organizer`(Person) / `description` / `isAccessibleForFree`；`location` **仅当该条事件确有观测地（`obs_site`）时输出** | ★★ **本插件输出（v1.3.0 起）** —— 2026-09-23 定谳：**面板这条路走不通**，根因是 Rank Math 免费版源码的白名单（只认 Article 家族），见 **§2.5**。⇒ 面板里 `Schema Type` 设 `Event` 或 `Off` **对前台都没有影响**，建议设 `Off`（理由见 §2.1 ⑤）。**不再依赖任何面板配置** |
| 历史天象事件 | `ScholarlyArticle` | `headline` / `datePublished` / `author` / `citation` / `about` / `temporalCoverage` | **只能**插件模板自出 JSON-LD（Rank Math 免费版无此类型） |
| 预告列表／归档页 | `CollectionPage` | `name` / `hasPart`(各事件 `Event`) | **Rank Math 默认已给归档页 `CollectionPage`**（2026-09-23 实测），但**不含 `hasPart`**；插件那份被 `should_emit()` 门控关掉 ⇒ `hasPart` 目前缺。`hasPart` 属加分项，**本轮不动**（要补须改插件 ⇒ 再传包），登记为可选改进 |

**两条红线（写进校验器判据）**

1. JSON-LD 输出中**不得**出现 `AstronomicalObject`／`Calendar` —— 两个类型不存在，校验器会报错。
2. **不得**给每日更新的「今日天象」套 `Event` —— 每日刷新页套 Event 属结构化数据滥用。今日天象一律 `WebPage + Dataset`。

**其余口径**

- ★ **`location` 的取舍（2026-09-23 定，推翻本节旧句）**：旧句写「`location` 必带 `GeoCoordinates`」——**已作废**。天文事件**没有举办场地**，把默认观测地当 venue 是失真 ⇒ **无 `obs_site` 的条目一律不输出 `location`**（`rankmath.php` L151—155 的刻意设计，有 php_selftest 判据守着）。
  **代价（如实记）**：Google 的 Event 富媒体结果**要求** `location`，故 Rich Results Test 会提示「缺少 location」——**这是有意为之，不是配置错误**。若日后要争取该富媒体结果，需用户在两条里选一：① 以「观测地」充 `location`（写明是观测地，不是场地）；② 页面级改 `virtualLocation`。**属待裁定项，本插件不擅自选。**
- 历史天象 `ScholarlyArticle` 的 `citation` 只能挂**可核验**的出处（规范古籍出处或 DOI）；无出处的条目不输出 `citation` 字段，**不得编造**。
- 时刻字段统一北京时间（UTC+8），`startDate` 写成带 `+08:00` 偏移的 ISO8601（含此偏移是 `php_selftest.py` 的判据之一）。
- 写日期的地方（`Dataset`）**取不到日期就不输出**：线上曾出现「首页／每篇博文／老黄历页」各挂一个 `揭阳每日天象数据集（）`（日期为空），2026-09-23 修（F38）。

---

## §2 Rank Math 逐屏操作

> 前提提醒：Rank Math 免费版**只能每页手选类型**，**没有「全局 Schema 模板」**（那是 PRO）。
> ⇒ CPT 级的默认 Schema 由本模块代码在 `rank_math/json_ld` 过滤器里注入（v1.3.0 起；**此前是「以为交给面板」而实际无人输出**，见 §2.5）；
> 面板只负责「元信息（Title/Description）＋ sitemap」，**Schema Type 一项对本插件负责的三种类型已无作用**。

### 2.0 ★ 先看线上现状（2026-09-23 03:2x 实测，未鉴权可复现）

> ★ **状态标记**：下表是 **v1.2.1 线上件**的状态。**v1.3.0 上传后**，第 1 行（单条事件）应变为
> `@type: Event, Person, WebSite, ImageObject, WebPage`，第 4 行（老黄历承载页）的 `Dataset` 会**消失**
> （原先是日期为空的坏节点，见 §1 末条）。验证法：`php_selftest.py`（本地）＋取页面 head 数 `class="rank-math-schema"` 块。

判定法：`<title>` 若等于**全站默认模板**（`{页名} - 邝楚嘉 Chujia Kuang — …`）或 description 等于 title 的复制 ⇒ **该处模板未设**。

| 页面 | 实测 `<title>` | 实测 `meta description` | 实测 JSON-LD `@type` |
|---|---|---|---|
| 单条事件 `/sky-forecast/planet-saturn-opposition-20261004/` | `土星冲日 - 邝楚嘉 Chujia Kuang — …`（**全站默认**） | 自动取摘要（非模板） | **【整页无 JSON-LD】** |
| CPT 归档 `/sky-forecast/` | `天象事件 Archive - 邝楚嘉 …`（Rank Math 默认） | **与 title 逐字相同** | `Person, PostalAddress, ImageObject, WebSite, CollectionPage`（**无 `hasPart`**） |
| 分类归档 `/sky-forecast/planet/` | —— | —— | —— | **路径式不可达，见 §2.3** |
| 预告列表页 `/tianxiang-yugao/` | `天象预告 - …` | —— | `WebPage, Dataset, Place, GeoCoordinates, PropertyValue` |
| 老黄历页 `/tianwen-rili/` | `天文历法_老黄历_…` | —— | `WebPage, Dataset, Place, GeoCoordinates` |

⇒ **前三行即 §2.1 要补救的**（①②③④⑤）；后两行的 `WebPage + Dataset` 已由插件输出，**无需面板干预**。

### 2.1 ★ 要手点的 7 项（原记「6 项」，实测后更正为 7）

| # | 菜单路径 | 字段 | 填什么值 |
|---|---|---|---|
| ① | Titles & Meta → Post Types → **天象事件** → Single | Title | `%title% ｜ 天象预报 · 华夏古天文历法实证记录` |
| ② | 同上 | Description | ★ **建议留空**（**2026-09-23 03:4x 实测后改判**，理由见下）——留空时 Rank Math 回落到 `%excerpt%`，而 `post_excerpt` **就是该条事件的真实摘要**（`cpt.php` L310：`'post_excerpt' => (string) $ev['summary']`）⇒ **79 条各自唯一、含真实数据**，这是**最好的** description。**若填一个固定模板，79 条会变成近似重复 ⇒ 反而更差**。⚠ 若确有「仅供天文观测参考」这类合规要求要逐条追加，须改插件按 `method` 注入（见本节末更正）。 |
| ③ | 同上 → **Archive（天象事件归档）** | Title ＝原表所称「Plural／归档标题模板」 | `天象预报 ｜ 华夏古天文历法实证记录`（建议值；是否与站内既有归档标题口径一致，**需现场核实**） |
| ④ | 同上 → Archive | Description | ★ **要填**（归档页没有 `%excerpt%` 可回落）。现为空 ⇒ 线上实测得到的是一个**与标题重复的短语**（`天象预报`），**回落机制未确证**（如实记：可能是 `%title%` 被分隔符截断，也可能是别处），但「显式填一句真描述」在任何机制下都更好。建议：`华夏古天文历法实证记录 · 天象预报：日月食、行星天象、流星雨等事件的北京时间与观测要点。` |
| ⑤ | 同上 → **Schema Markup** | Schema Type | ★ **改判（2026-09-23 源码级定谳）**：**面板选 `Event` 在前台永远不会出图** —— 根因是 Rank Math 免费版源码的**白名单**（只认 Article 家族），见 **§2.5**。⇒ **建议选 `Off`**。理由：`Off` 与前无差别（都不出图），但可**防止将来某篇在编辑器里打开并保存后**由 Rank Math 写入 `rank_math_schema_Event` 元数据 —— 那份 schema **缺 `startDate`**（免费版不会自动填），会**抢在本插件前面**输出一个不完整的 `Event`，反而更差。★ `Event` 自 v1.3.0 起**由本插件输出**，不依赖此面板项 |
| ⑥ | Sitemap Settings → Post Types | `astro_event` 开关 | ✅ **已完成且已生效（2026-09-23 04:2x 实测）**：用户点了 `Save Changes` ⇒ 索引（查询式 `?sitemap=1`）变 **4 条**，含 `astro_event-sitemap.xml`；事件 sitemap（`?sitemap=astro_event`）**80 条 `<loc>`**（归档 ＋ 79 条事件页）。⚠ 但**漂亮路径仍全 404** —— 那**不是本项的问题**（本项管「生不生成」，那条管「路由通不通」），见 **§2.6** |
| ⑦ | Sitemap Settings → Taxonomies | `event_type` 开关 | ⚠ **暂缓 —— 先保持关闭**（面板截图为关，正确），理由见 §2.3（开了等于把 301／404 交出去） |

**★ ⑥ 的线上判据（两条入口必须分开查，2026-09-23 04:2x 修正）**

`astro_event-sitemap.xml` 是否 **404** 曾经被当作「⑥ 没生效」的证据 —— **这个推论只对了一半**。
真正的判别要**两条入口都试**，因为两者的**结论与修法完全不同**：

| 入口 | 命令 | 04:2x 实测 | 说明 |
|---|---|---|---|
| **生成侧**（查询式） | `https://kuangchujia.com/?sitemap=1` | **200**，4 条 `<loc>`，含 `astro_event-sitemap.xml` | 不受重写规则影响 ⇒ 直接反映「该类型**有没有**注册为 provider」 |
| **生成侧**（查询式） | `https://kuangchujia.com/?sitemap=astro_event` | **200**，**80 条 `<loc>`** | 内容确实生成了 |
| **路由侧**（路径式） | `https://kuangchujia.com/sitemap_index.xml` | **404** | 搜索引擎真正会抓的形态 |
| **路由侧**（路径式） | `https://kuangchujia.com/astro_event-sitemap.xml` | **404** | 同上 |

**判别表**

| 查询式 | 路径式 | 结论 | 修法 |
|---|---|---|---|
| ✅ | ✅ | 正常 | —— |
| ✅ | ❌ | **重写规则没生效**（Rank Math 的 sitemap 路由没进 `rewrite_rules`）。模块与生成都**没问题** | ① `设置 → 固定链接` 页面**直接点「保存更改」**（什么都不改，就是 flush 重写规则）；② 仍不通 → `Rank Math → Dashboard → Database Tools` 清 **sitemap 缓存** |
| ❌ | ❌ | 生成侧有问题 | 查 `Rank Math → Dashboard → Modules` 的 **Sitemap 模块**是否开启；或该类型未启用（＝ ⑥／⑦ 真的没落盘） |

> ⚠ **别把「路径式 404」直接读成「⑥ 没生效」** —— 那会让人反复去点 `Save Changes`，
> 而问题根本不在那儿。`?sitemap=` 这条入口是**免费且免鉴权**的判别器，先用它。
> ⇒ 工具已固化：`python live_verify.py` 的 **B／C（查询式）＋ B2（路径式）** 三项，
> 并在 B2 的报错里**直接写出该走哪条修法**。

**③ 为什么「404」可以直接判「设置没落盘」**（源码级，别先怀疑缓存）：
`class-router.php` 的 rewrite 规则是**通用的** —— `([^/]+?)-sitemap([0-9]+)?\.xml$` 对**任意类型名**都会路由；
而 `class-sitemap-xml.php::output()` 只在**该类型确实注册为 sitemap provider**时才建出内容，
建不出就 `set_404() + status_header(404)`。
⇒ **该类型未启用 ⇒ 404**；**缓存（`class-cache.php` 的 transient，索引键为类型 `'1'`）只影响「内容体新旧」，不影响「路由是否存在」**。
⇒ 顺序是：**先点 Save Changes**（Rank Math 的设置页是前端状态，未保存时不落盘）→ 再看上面两条；
仍 404 才去 `Dashboard → Database Tools` 清 **sitemap 缓存**（`/rankmath/v1/toolsAction`）。

> ★ **顺序提醒**：**先把 v1.3.0 包传上去，再让搜索引擎来抓 sitemap** ——
> 否则爬到的 79 条事件页是「无 `Event` 结构化数据」的旧状态（虽会被重抓，但没必要）。
| 编辑单篇 `astro_event` → Rank Math 侧栏 → Schema Tab | Schema 类型 | 未来一次性事件：手选 **Event**；每日天象不在 CPT 内，无需选；历史天象：**不选**（由插件模板输出 `ScholarlyArticle`，面板无此类型） |
| 预告列表／归档承载页 → Rank Math 侧栏 → Schema Tab | Schema 类型 | 手选 **CollectionPage** |
| 老黄历页（今日天象承载页）→ Rank Math 侧栏 → Schema Tab | Schema 类型 | 保持 **WebPage**；`Dataset` 子节点由插件模板另出 |

**描述分流的硬纪律（不得混用）**

- 两版描述**按 `method` 字段分流**，且**不得互相套用**：解析降级页**绝不**沿用「星历回推／基于 JPL DE421」措辞 —— 混用构成**虚假溯源**（见 `docs/feasibility-review.md` F12）。
- 免费版面板内的描述模板为**全站统一值，无法按字段自动分支**；面板内**只填中性兜底版**。
- ★ **更正（2026-09-23 实测）**：本节原写「两版描述的实际注入由插件在判定 `method` 后完成」—— **不成立**。`includes/rankmath.php` L23—25 已明写「标题/描述模板：Rank Math 免费版走后台设置页（Titles & Meta），源码中未见对应的前端 filter，故本插件**不擅自 hook**」⇒ 当前**不存在任何自动分流**，面板里填什么就是什么。要恢复「按 `method` 分流」，须改插件去挂官方 filter `rank_math/frontend/description`（该 filter **确实存在**）——**登记为可选改进，本轮不改包**。
- ★ 由此得一条通用判据：**凡是「交给对方做」的分工，必须有一条端到端判据在跑**（此处＝「单条事件页应出现 `Event` 节点」）。否则两侧都以为自己已让位 ⇒ **无人输出**（详见 `feasibility-review.md` F35／F36）。

### 2.1b ★ 面板改动的线上复核（2026-09-23 03:36—03:40）

用户在面板填了 ①③⑤ 后，我实测线上：

| 项 | 面板状态 | 线上实测 | 判定 |
|---|---|---|---|
| ① Single Title | 已填 | `土星冲日 ｜ 天象预报 · 华夏古天文历法实证记录`（原为全站默认模板） | ✅ **已生效** |
| ③ Archive Title | 已填 | `天象预报 ｜ 华夏古天文历法实证记录`（原为「天象事件 Archive - …」） | ✅ **已生效** |
| ⑤ Schema Type = Event | 面板显示 Event | 单条事件页 **仍然零 JSON-LD**（`application/ld+json` 出现 **0** 次） | ❌ **未生效** |
| ⑥⑦ Sitemap | 面板已置 ⑥ ON／⑦ OFF（截图），**线上未生效** | `sitemap_index.xml` 仅 `post-` / `page-` / `category-` 三个子图；`astro_event-sitemap.xml` **404** | **待点 Save Changes**（判据与源码依据见 §2.1 ⑥） |

**⑤ 的差分实验（决定性）**：同一站点、同一 Rank Math，逐类页面测一遍 —

| 页面 | `application/ld+json` 块数 | `@type` |
|---|---|---|
| 普通文章单页 `/2026/09/22/three-calendars-three-kinds-of-time/` | **1** | `… WebPage, Person, BlogPosting, Dataset, Place, GeoCoordinates` |
| 普通页面单页 `/tianxiang-yugao/` | **1** | `… Article, Dataset, Place, GeoCoordinates, PropertyValue` |
| CPT 归档 `/sky-forecast/` | **1** | `… CollectionPage` |
| 首页 `/` | **1** | `… Article, Dataset, Place, GeoCoordinates` |
| **CPT 事件单页 `/sky-forecast/planet-saturn-opposition-20261004/`** | **0** | **【无】** |

⇒ **不是全局问题，只有 `astro_event` 单页这一类**。且 Rank Math 确实在跑这一页
（该页标题正是它按 ① 的模板渲染出来的）⇒ 问题落在 **Schema 的解析或输出**，不在「Rank Math 没认这个 CPT」。

**head 逐条对照实验（决定性，两页都未鉴权可复现）**

| 证据 | 单条事件页 `/sky-forecast/planet-saturn-opposition-20261004/` | CPT 归档 `/sky-forecast/` |
|---|---|---|
| `<title>` | `土星冲日 ｜ 天象预报 · 华夏古天文历法实证记录`（**Rank Math 按 ① 渲染**） | `天象预报 ｜ 华夏古天文历法实证记录`（按 ③） |
| `meta description` | ＝事件摘要（**② 留空回落 `%excerpt%` 生效**） | ＝手填的那句（**④ 生效**） |
| `og:*` / `twitter:*` | 13 条，**全在** | 12 条，全在 |
| `canonical` / `robots` | **全在** | 全在 |
| `class="rank-math-schema"` 的 `ld+json` | **0 个** | **1 个** |
| `天象事件Feed` 那条 `alternate` | **没有** | 有 |
| `rank-math` 字样出现次数（整页） | **0** | 1（就是那个 schema 块） |

⇒ 结论：**Rank Math 的元信息层在这一页工作正常，唯独结构化数据块不产出** ⇒ 指向 Schema 环节，
与缓存、与「没保存」、与「没认这个 CPT」都无关。**根因已定位到源码，见 §2.5。**

**排查顺序见 §2.4（现已降级为「万一 v1.3.0 上传后仍无输出」的兜底）。**

### 2.2 面板在哪（照截图对位）

- Rank Math → **Titles & Meta**（左栏第一组）→ 左栏 **`Post Types:`** 分组下点 **「天象事件」**。
  **①②③④⑤ 全在这一页里**（该页顶部的 `Titles & Meta` 页签内，先 Single 区块、再 Archive 区块、再 Schema Markup）。
- ⚠ **别点错**：左栏另有一组 **`Astro_event:`**，其下唯一一项是 **「天象类型」** —— 那是**分类法** `event_type` 的归档设置，**不是**本表要改的地方。
- 截图里当前停在 **Global Meta**（全局设置），所以整页看不到任何 CPT 字段；⑥⑦ 则在 **Sitemap Settings** 页（分 `Post Types` / `Taxonomies` 两个子页）。

### 2.3 ★ 分类归档路径式不可达（F34）⇒ ⑦ 必须暂缓

| 入口 | HTTP | 结果 |
|---|---|---|
| `/sky-forecast/?event_type=planet`（**查询式**） | **200** | 正常渲染，`<h1>行星天象 · 天象事件</h1>` |
| `/sky-forecast/planet/`（**路径式**） | **301** | → `/sky-forecast/planet-jupiter-conjunction-20270831/`（**跳到一条不相干的事件**） |
| `/sky-forecast/meteor/`（**路径式**） | **301** | → `/sky-forecast/meteor-aur-20270901/` |
| `/sky-forecast/eclipse/`（路径式） | **404** | —— |

**根因**：CPT `astro_event` 与分类法 `event_type` 用了**同一个 rewrite slug**（`cpt.php` L31／L33 都取 `KCJ_ASTRO_SLUG`＝`sky-forecast`），而 `register_post_type()` 在 `register_taxonomy()` **之前**调用（L102 vs L130）⇒ CPT 单条规则 `sky-forecast/([^/]+)/?$` 先匹配、**把分类法规则整体遮蔽**；未命中即 404，再由 WordPress 的 `redirect_guess_404_permalink()` 按 `LIKE 'planet%'` 猜出**一条事件**做 301。

**后果**：① 6 类分类归档**路径式全部不可达**，`templates/archive-astro_event.php` L22 的 `is_tax` 分支成为**死路径**（只有查询式能走到）；② 若开 ⑦，交给搜索引擎的就是一批「**301 到不相干文章**」或 404 的 URL —— **比 404 更糟**（错误重定向信号）。

**处置**：⑦ **暂缓**。修法＝把分类法的 rewrite slug 独立成一段（如 `sky-forecast/type`）并 `flush_rewrite_rules()` ⇒ **本轮不改包**（会打断正在做的面板配置；且不影响 79 条事件详情页与 CPT 归档页），登记为 **F34**，随下一次插件改动一并提交。

### 2.4 ★ ⑤「未生效」已定谳（下方原排查顺序已降级为兜底）

**定谳（2026-09-23）**：**面板选 `Event` 在这套 Rank Math（免费版）上前台永远不会出图** ——
根因是源码里的白名单，见 **§2.5**。⇒ 下表四项**逐条都已排除**，留档备查：

| 可能性 | 是否成立 | 判据 |
|---|---|---|
| 没保存 / 改在保存之后 | ✗ | ①③④ 三项**同一页、同一批**保存且均已生效（§2.1b） |
| Schema 模块没开 | ✗ | 若模块关着，普通文章页／灌水页也不会有那个 schema 块；实测**四类页面都有，唯独事件单页没有** |
| 缓存 / CDN 陈旧 | ✗ | 随机查询串 ＋ `Cache-Control: no-cache` 两轮复测结果一致 |
| 79 篇是 REST 程序化创建、从未在编辑器保存 | **不适用** | 这条只在「默认类型属 Article 家族」时才有意义（那时 Rank Math 走 `Singular` 分支出图）；`Event` 在白名单外，**存不存都不出图** |

**兜底（仅当 v1.3.0 上传后事件单页**仍**无 `Event` 时才按序走）**：

1. **先确认新包真的生效**：`https://kuangchujia.com/wp-json/kcj-astro/v1/health` ⇒ 看 `plugin` 字段是否 `1.3.0`。
   ★ **别对旧包排查**（这是本回合最容易白忙的一步）。
2. 清缓存后硬刷新（Rank Math → Dashboard → **Database Tools**，或清 WP.com 缓存），再取 head 数 `class="rank-math-schema"` 块。
3. 确认 `Rank Math → Dashboard → Modules` 里 **Schema (Structured Data) 为 ON**（关着时谁都不输出）。
4. 本地先跑 `python php_selftest.py`：**应 30 项全绿**。本地绿而线上无 ⇒ 问题在「包没生效」或「`rank_math/json_ld` 上还有别的回调覆盖了数组」，按这个方向查。

---

### 2.5 ★★ 根因（源码级）：面板填 `Event` 为什么无效

**一句话**：Rank Math 免费版在 singular 页面读「默认 schema 类型」时**只认 Article 家族五种**，
其余（含 `Event`）一律返回 `false`；于是 `Event` 不输出之外，**连站点级实体也被一并放弃**。

证据链（源码＝`rankmath/seo-by-rank-math` master 分支；本机已下载核对，非推测）：

1. `includes/modules/schema/class-jsonld.php :: setup()`
   `$this->action( 'rank_math/json_ld', 'add_context_data' );` ⇒ **默认优先级 10**。
2. 同文件 `can_add_global_entities()` **L379 / L383 / L394**：
   ```php
   if ( is_front_page() || ! is_singular() || ! Helper::can_use_default_schema( $this->post_id ) || ! empty( $data ) ) {
       return true;
   }
   $schemas = DB::get_schemas( $this->post_id );
   if ( ! empty( $schemas ) ) { return true; }
   return $this->do_filter( 'schema/add_global_entities', Helper::get_default_schema_type( $this->post_id, true ), $this );
   ```
   事件详情页：非首页、是 singular、`can_use_default_schema()` 为真、`$data` 为空、无文章级 schema 元数据
   ⇒ 落到 **L394**，取到 **false** ⇒ `$can_add_global = false` ⇒ **Person / WebSite / ImageObject / WebPage 全被跳过**。
3. `includes/helpers/class-schema.php :: get_default_schema_type()` **L70**：
   ```php
   if ( $return_valid && ! in_array( $schema, [ 'Article', 'NewsArticle', 'BlogPosting', 'WooCommerceProduct', 'EDDProduct' ], true ) ) {
       return false;
   }
   ```
   ⇒ **`Event` 在白名单外**。（同方法 **L41** 读的键是 `titles.pt_{post_type}_default_rich_snippet`——正是面板那一项。）
4. `includes/modules/schema/snippets/class-singular.php :: get_default_schema()` **L104**：
   `Helper::get_default_schema_type( $jsonld->post_id, true )` —— **`$return_valid = true`** ⇒ 上面那条白名单生效。
5. `class-jsonld.php :: json_ld()`：
   ```php
   $data = array_filter( $this->do_filter( 'json_ld', [], $this ) );
   if ( empty( $data ) ) { return; }   // ⇒ 一个 <script> 都不输出
   ```
   ⇒ 与实测「整页零 JSON-LD」**逐字吻合**。

**为什么面板里选得到 `Event`**：那个下拉框是**通用**控件（PRO 下同一项服务更多场景），
免费版**没有**把前台取默认类型时的白名单同步收窄 ⇒ **可选 ≠ 生效**。

**修法（v1.3.0 已办）**

- `kcj_astro_schema_should_emit()` 的 `$only_mine` 加入 `'Event'` ⇒ 事件单页由本插件出 `Event`；
- 附一条**让位判据**：该篇若已有 `rank_math_schema_*` 文章级元数据（用户在编辑器里保存过），本插件不出 `Event`，避免同页两个 Event；
- 回调优先级 **20 → 5**：抢在 Rank Math 的 `add_context_data`（10）之前放入节点 ⇒ `! empty( $data )` 成立 ⇒ **站点级实体在事件页恢复输出**；
- 判据：`php_selftest.py`（30 项，**含负控制**：有文章级 schema 时必须让位）。

**通用教训**：**「面板里能选」不等于「前台会输出」**。凡把一件事交给第三方插件的 UI，
必须①再找一条**端到端判据**（此处＝「事件单页 head 里应出现 `Event`」），②**读它的源码**确认那条路真的通。
（同族：`feasibility-review.md` F35；技能 `checker-self-reference-pitfalls` **陷阱五十一**。）

**线上已验（2026-09-23 04:12）**：事件详情页 **79 / 79** 出 `Event`、`startDate` 全带 `+08:00`、
站点级实体缺失 **0** ⇒ 修法生效。命令：`python live_verify.py`（见 `docs/deploy.md` §1b）。

#### 2.5b 「让位判据」安全吗 —— 已定谳：安全，两分支都不出空洞

上面那条「该篇已有文章级 schema 时本插件让位」，当时留了个疑点：**让位之后，Rank Math 到底渲不渲它？**
若不渲，那篇就会静默丢掉全部内容级结构化数据。**已读源码定谳（两路互证）**：

1. `add_schema()` 挂在 `rank_math/json_ld` **优先级 10**（`class-frontend.php` **L47**），
   实例化点是 `class-jsonld.php::setup()` **L58 `new Frontend();`**
   （`class-schema.php` L59 先 `( new JsonLD() )->setup()`）。
   函数体 `array_merge( $data, DB::get_schemas( $post->ID ) )`（`class-jsonld.php` **L218—222**），**无类型白名单**
   ⇒ 与 `get_default_schema_type()` 是两条独立路径。
   ⚠ **`Frontend` 不在 `setup()` 的 `$this->action(...)` 清单里，是靠 L58 的 `new` 挂上的** ——
   只扫 `setup()` 的挂载列表会误判成「没人调用 `add_schema`」。
2. `can_add_global_entities()` 在落到白名单那一步之前有 `if ( ! empty( $schemas ) ) return true;`（**L383—386**）
   ⇒ 有文章级 schema 时直接放行，**站点级实体照出**。

⇒ **两个分支都安全**：有文章级 schema ⇒ 让位（Rank Math 出它那份 ＋ 站点级实体照出）；
没有 ⇒ 本插件出 `Event`（并在优先级 5 撑住 `! empty( $data )`，站点级实体照出）。**不存在「两边都不出声」。**

#### 2.5c 并入 `@graph` 的标量会被 WordPress 核心串化（F39 · 非缺陷 · 无法规避）

线上实测与本地源码不一致：本地 `isAccessibleForFree => true`，线上 `"1"`；`geo.latitude` 同为 `"23.55"`。
根因＝Rank Math 渲染前跑 `wp_kses_post_deep( $json )`（`class-jsonld.php` **L164**），
核心实现是 `map_deep( $data, 'wp_kses_post' )`（`wp-includes/kses.php` **L2516—2518**），
`map_deep` 对每个标量都过一遍回调（`wp-includes/formatting.php` **L5225—5240**）。

* `"1"` 表真 **是 schema.org 认可的 Boolean 写法** ⇒ **不算缺陷**。
* 经纬度变字符串不再是 `Number`，但 `Dataset` 不是 Google 富媒体类型 ⇒ **不列为不通过**。
* **不可规避**：并进 `@graph` 就必过这一道。想保原生类型只能自己 `wp_head` 打一份，代价是丢掉实体互链 ⇒ **不值得**。
* ⚠ **只对真值无害**：`false` 会被写成**空串 `""`** ⇒ 本插件布尔**一律只发 `true`**；要发假值就**整个键省略**。
  该约束**只在文档**，未进源码注释（以保住已上线包的指纹）。

---

### 2.6 ★★ 漂亮路径全 404（F41）—— ⑥ 生效了，但搜索引擎拿不到任何 sitemap　【**已修复 · 04:37**】

**实测（2026-09-23 04:2x，全部带随机查询串 ＋ `no-cache`，可复现）**

| 路径 | 状态 |
|---|---|
| `/sitemap_index.xml` | **404** |
| `/post-sitemap.xml` | **404** |
| `/page-sitemap.xml` | **404** |
| `/category-sitemap.xml` | **404** |
| `/astro_event-sitemap.xml` | **404** |
| `/sitemap.xml`（Jetpack 口径） | **404** |
| `/wp-sitemap.xml`（WP 内核口径） | **404** |
| `/main-sitemap.xsl`（XML 里引用的样式表） | **404** |
| `?sitemap=1`（索引·查询式） | **200**，4 条 `<loc>` |
| `?sitemap=post` | **200**，9 条 |
| `?sitemap=astro_event` | **200**，80 条 |
| `/robots.txt` | **200**，里面写着 `Sitemap: https://kuangchujia.com/sitemap.xml`／`sitemap_index.xml` |

**关键对照（用来排除「重写整体坏了」）**

`/feed/` **200**、`/category/uncategorized/` **200**、`/sky-forecast/` **200**、文章固定链接 **200**
⇒ **WordPress 的重写系统本身是好的**。坏的**只有 Rank Math 的 sitemap 那一组路由**。

**结论**：Rank Math 的 sitemap 重写规则**不在 `rewrite_rules` 表里**（或已失效）。
生成侧完全正常（`?sitemap=` 全部 200）⇒ **⑥ 的开关确实生效了**，这一点已经拿到硬证据。

**为什么值得单独记一条**

1. **它把「我们的功能对不对」和「搜索引擎拿不拿得到」分开了**：前者已 ✅，后者已 ❌，且互不因果。
2. **`robots.txt` 还在对外推荐两个 404 的地址** ⇒ 此刻**整站的 sitemap 通道是断的**（不止事件模块，
   `post-`／`page-`／`category-` 一起 404）⇒ **这是本站当前最该先修的一条**。
3. **无法判定「是这次 Save Changes 引起的、还是本来如此」**：04:12 那次路径式曾返回 3 条 `<loc>`，
   但那**极可能是 WordPress.com 边缘缓存**里更早的一份（当时索引用的是「3 条」的旧版本，
   而现在查询式是「4 条」的**新**版本）⇒ 缓存被这次的保存动作清掉后，露出的是**源站真实状态**。
   **如实记录，不下断言。**

**修法（按顺序，都在用户侧）**

1. **`设置 → 固定链接` → 什么都不改，直接点「保存更改」** —— 这就是 `flush_rewrite_rules()`，标准做法。
2. 仍不通 → **`Rank Math → Dashboard → Database Tools` → 清 sitemap 缓存**。
3. 仍不通 → 看 **`Rank Math → Sitemap Settings → General`** 是否有「Sitemap 基名／索引文件名」一类设置被改过。
4. 每做一步，**复跑 `python live_verify.py`** 看 **B2** 那一项转绿没有（它会直接说出该走哪一步）。

> **兜底（若平台不允许 flush）**：`robots.txt` 也可直接写**查询式**地址
> （`Sitemap: https://kuangchujia.com/?sitemap=1`）—— 搜索引擎接受带查询串的 sitemap 地址，
> 但**只作为最后手段**：索引里的 `<loc>` 仍然是漂亮路径，Google 顺着抓依然 404 ⇒ **治不了根**，只是把入口气延长。
> 真正的修法只有一条：**让重写规则进表**。

#### ★★ 修复实录（2026-09-23 04:37）—— **第一步就够了，B2 已转绿**

**用户执行第 1 步**（`设置 → 固定链接` → 什么都不改 → 点「保存更改」）后复跑 `python live_verify.py`：
**通过 9 ／ 跳过 1 ／ 不通过 0**，`B2` 从 `404/404` 变成 **`200/200`**。
⇒ **F41 的定性得到确证**：确实是**重写规则没进 `rewrite_rules`**（生成侧一直正常），
一次 `flush_rewrite_rules()` 即解决；**不需要动 Rank Math 的任何设置**（第 2、3、4 步都没走到）。

**核过的路径式产物**（`curl` ＋ 随机查询串 ＋ `no-cache`）：

| 路径 | 状态 | `<loc>` | Content-Type |
|---|---|---|---|
| `/sitemap_index.xml` | **200** | **4** | `text/xml; charset=UTF-8` |
| `/astro_event-sitemap.xml` | **200** | **80** | `text/xml; charset=UTF-8` |
| `/post-sitemap.xml` | **200** | **9** | `text/xml; charset=UTF-8` |
| `/page-sitemap.xml`／`/category-sitemap.xml` | **200** | — | — |
| `/main-sitemap.xsl` | **200** | — | （XML 引用的样式表，同步恢复） |
| `/sitemap.xml` | **404** | 0 | `text/html` |
| `/news-sitemap.xml` | **404** | 0 | — |

**残留 2 条（轻 · 与 F41 同族但不同因 · 非本模块）**：`/robots.txt` 里一共声明了**三条** sitemap ——
`sitemap.xml`（Jetpack 口径，404）、`news-sitemap.xml`（Rank Math 新闻 sitemap，未开模块，404）、
**`sitemap_index.xml`（200 ✅，这条覆盖全站）**。
⇒ 收录不受影响；要清干净就二选一：**开 News Sitemap 模块** 或 **删掉那两行**。

> ★ **给未来省时间**：若遇到「**sitemap 漂亮路径全 404，而查询式 `?sitemap=` 全 200**」⇒
> **不要去翻 Rank Math 设置、不要先清缓存，先去「固定链接」按一次保存**。
> 判别顺序错了会绕一大圈（本轮第一轮就绕错了）。

---

## §3 焦点关键词

| 场景 | 命名规则 | 示例 |
|---|---|---|
| 未来天象 | `{年份}年{事件名}` | 2026年双子座流星雨极大 |
| 未来天象 | `{年份}年{事件名}` | 2026年月全食 |
| 未来天象 | `{年份}年{事件名}` | 2027年日全食 |
| 历史天象 | `{年份}历史天象回推` | 公元前720年历史天象回推 |
| 历史天象 | `{年份}历史天象回推` | 1054年历史天象回推 |

**约束**

- 事件名必须与 `wp_astro_events.title` **逐字一致**，不得为贴合搜索另起名。
- **不得**添加数据未支撑的可见性形容词（如「中国可见」「全国可见」）——除非该条目的 `params_json` 确有相应判定。数据给不出就让关键词停在事件名。
- 上表 5 条为**格式示例**，实际投用的事件名以数据表实际录入为准。

---

## §4 校验与提交

> ★ **前置（2026-09-23 更新）**：①③④ 面板项已生效；**`Event` 自 v1.3.0 起由本插件输出**（§2.5）
> ⇒ 上传 v1.3.0 并确认 `/wp-json/kcj-astro/v1/health` 的 `plugin = 1.3.0` **之后**再走本表；
> 否则单条事件页**整页无 JSON-LD**，Rich Results Test 会直接报「未找到结构化数据」——那是**未配置**，不是配置错误。
> ★ **本阶段不提交**分类归档 URL（`/sky-forecast/{term}/`，见 §2.3）；
> 历史事件详情页当前**无数据**（0 条），该项留待人工条目录入后再测。
> ★ **预期告警（不是错误）**：`Event` 条目 Rich Results Test 会提示**缺少 `location`** —— 天文事件无举办场地，
> 插件**有意不填**（见 §1 末「`location` 的取舍」）。此告警**不列为不通过**。

| 步骤 | 工具 | 动作 | 通过判据 |
|---|---|---|---|
| 1 | Google Rich Results Test | 对四类页面各测一条 URL（今日天象页／未来事件详情／历史事件详情／归档页） | 无「无法识别的类型」；JSON-LD 内**无** `AstronomicalObject`／`Calendar` |
| 2 | 百度结构化数据校验 | 同上四条 URL | 无类型报错；`Event` 的 `startDate` 可解析 |
| 3 | Google Search Console | 提交站点 sitemap；**中文分图与英文分图分别提交** | 状态「成功」，已发现 URL 数 ≥ 预期 |
| 4 | 百度资源平台 | 提交站点地图；核心页走手动提交 | 提交成功，无「校验失败」条目 |

**补充说明**

- Google 对 `ScholarlyArticle` **无专属富结果样式**，其价值在语义标注与引用关系，不以富结果呈现为验收项。
- 提交前先跑一遍站内合规扫描（见 `docs/acceptance-checklist.md` §3），避免带违禁词页面被提交。

---

## §5 免费版能力缺口与对策

| 能力 | Rank Math 免费版 | 本模块对策 |
|---|---|---|
| `ScholarlyArticle` | 无（PRO 亦需 Custom Schema） | 插件模板自出 JSON-LD |
| `Dataset` | 无（仅 PRO） | 插件模板自出 JSON-LD（今日天象 `WebPage` 子节点） |
| Custom Schema（任意类型） | 无（仅 PRO） | 不需要：类型全部落在「WebPage／Event／CollectionPage／ScholarlyArticle」四者内，前三者有面板或代码落地，第四者纯代码 |
| 全局 Schema 模板（条件分支） | 无（仅 PRO） | 由代码经 `rank_math/json_ld` 过滤器按 CPT／`method` 注入 |
| `FactCheck` / `ItemList` / `Q&A` / `Speakable` / `Carousel` | 无（仅 PRO） | 本模块不使用这些类型，无缺口 |
| `Event` | **有** | 面板可手选；同时保留代码注入作一致性兜底 |
| `CollectionPage` | **有** | 面板手选 |
| 标题／描述模板、sitemap、面包屑 | **有** | 按 §2 配置 |
| 多语言 hreflang | 需现场核实（免费版是否含多语言模块） | 由站点构建侧统一输出 `hreflang`，不依赖 Rank Math |

**一句话**：Rank Math 免费版在本模块里只做三件事 —— 标题／描述模板、sitemap、`Event`／`CollectionPage` 手选；**其余结构化数据全部由插件自己出**。
