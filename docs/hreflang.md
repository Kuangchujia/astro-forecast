# hreflang 双语互指（v2.3.15）

> 面向使用者：本文件说清「哪些页面会输出什么标签」「为什么这么输出」「怎么验」。
> 完整根因与修法见 [`feasibility-review.md`](feasibility-review.md) 与插件头 changelog。
> 2026-09-25 诊断报告：[`hreflang-diagnosis-20260925.html`](hreflang-diagnosis-20260925.html)

---

## 〇、v2.3.15 新增：文章页（post）互指

**此前文章页一条 hreflang 都不出**（`is_page()` 闸挡死全部 post）。
v2.3.15 补上 article 支路，中英文章从此互指。

| 页面类型 | 输出 | 条数 |
|---|---|---|
| **文章页 · 已完成配对**（中↔英双向都写了互译锚） | `zh-CN` → 中文篇、`en` → 英文篇、`x-default` → **中文篇** | 3 |
| **文章页 · 无对手**（纯中文，或对手是草稿） | 只出 `x-default` 指自身，**不出 `zh`** | 1 |
| **文章页 · 单侧声明**（只有一侧写了互译锚） | 同上，只出 `x-default` | 1 |

### 配对怎么建立

两个锚，**都不靠猜**：

1. **分类判侧** —— `中文版`（默认 id `63494103`）／ `英文版`（默认 id `63494104`）。
   只用来判「本页属于哪一侧」，**不用它猜对手是谁**。
2. **互译元字段 `_kcj_translation_of`** —— 存**对手 post 的 id**，中英两篇**各存一条**。

> ★ **为什么不做「按标题/正文相似度自动配」**：本项目纪律是**不猜**。
> 本地篇号命名已实测存在错配（`002` 下中文《立春换岁》配英文
> `Eclipse-Records-on-Oracle-Bones`，二者非互译）⇒ 任何「按命名或相似度推配对」
> 的做法都会复活这个错误。**宁可只出 `x-default`。**

> ★ **为什么必须 `register_post_meta` 注册这个字段**：
> WordPress 的 REST `meta` 是**白名单制** —— 未注册的键即使 PUT 带上去也
> **静默丢弃、且仍返 200**（2026-09-25 实测）。
> 与本项目在 Zenodo 侧记下的同一类坑：**「返 200」不等于「落库了」，只信回读。**

### 怎么填互译锚

REST（字段已 `show_in_rest`）：

```bash
curl -X PUT "https://public-api.wordpress.com/wp/v2/sites/<SITE_ID>/posts/10" \
  -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  -d '{"meta":{"_kcj_translation_of":190}}'
# 中文篇 10 存英文篇 190；英文篇 190 存中文篇 10。★ 必须双向都写。
```

后台亦可（自定义字段 `_kcj_translation_of`，值为对手 post id）。

### 已配对的 5 对（2026-09-25）

| 中文 | 英文 |
|---|---|
| 三本历法·三种时间 `10` | Three Calendars, Three Kinds of Time `190` |
| 十个字配十二个字 `841` | Ten Stems, Twelve Branches `193` |
| 抬头与低头之间 `2422` | Between Looking Up and Looking Down `2425` |
| 尧典四仲中星 `2423` | The Four Fixed Stars of the *Yaodian* `2426` |
| 甲骨文「日有食之」`2424` | The Verifiability of the Oracle-Bone Records `2427` |

---

## 一、为什么由插件做，而不是 SEO 插件

站上装的是 Rank Math **免费版**。其 `hreflang` 能力属 PRO，或需后台逐页配置，
**没有可编程 filter**。故本插件直接在 `wp_head`（优先级 1）输出。

与同插件 JSON-LD 的分工**不冲突**：JSON-LD 走「有 Rank Math 时并进它的 `@graph`／
没有时自打」两条路，输出的是 `<script type="application/ld+json">`；
hreflang 输出的是 `<link rel="alternate">`。两者标签名不同、互不覆盖。

---

## 二、三类页面，三种处理

| 页面类型 | 输出 | 条数 |
|---|---|---|
| **语言子页**（同一父页下 slug 为 `zh` / `en` 两页） | `zh-CN` → 中文页、`en` → 英文页、`x-default` → **中文页** | 3 |
| **文章页 · 已配对**（见 §〇） | 同上 | 3 |
| **父栏目页 / 列表页** | 只出 `x-default` 指自身 | 1 |
| **首页 / 普通页 / 文章（未配对）** | 只出 `x-default` 指自身 | 1 |
| **配对不齐**（只有 zh 没有 en，或反之） | 只出 `x-default` 指自身 | 1 |
| **非页面**（归档、博客列表页） | **不出标签** | 0 |

**为什么父栏目页不出 `zh` / `en`**：它是「同一 URL 内双语 Tab 单页」，
**不是** en/zh 两版中的一版。若强行出 `zh` 指自身，就是在声明「本页是中文版」，
而它同时是英文版 ⇒ **反向失真**。

**为什么 `x-default` 指中文页**：站点主受众为中文读者，与 `locale` 一致。
这是**口径选择，非技术必然** —— 换成指英文页在技术上也成立，但与本项目的
读者定位不符。

---

## 三、两个必须避开的坑

### 坑一：三条 `href` 写同一个 URL

常见错法：

```html
<link rel="alternate" hreflang="zh"        href="https://example.com" />
<link rel="alternate" hreflang="en"        href="https://example.com" />
<link rel="alternate" hreflang="x-default" href="https://example.com" />
```

问题不在标签写法，在 **`href` 三条同值** —— 等于声明「中英两版都在同一个 URL」。
搜索引擎会判为**自指重复**、**整组忽略**，还可能反过来污染原页面的语言判定。

`hreflang` 是**双向契约**：A 页声明 B 是它的英文版，B 页也**必须**声明 A 是它的
中文版；缺一侧则整组作废。本模块按「每页只声明自己所在的那一组」实现，
双方各自输出、天然成对。

### 坑二：写死页面 ID 表

曾有一版维护脚本写死 `PAGE_ID = 29`，站点改版把内容下移到语言子页后，
该脚本当场断言失败 —— **不是网络问题、不是令牌问题，是工具与站点未同批改指**。

本模块改为**按「父页 ＋ slug」自动判定**：

1. 取当前页的 `post_parent`；
2. 在该父页之下找 `slug === 'en'` 与 `slug === 'zh'` 的子页；
3. 两者俱全 ⇒ 判为语言对，按 slug 归位。

WordPress 保证**同父同级 slug 唯一** ⇒ 该配对是确定性的，不需要任何 ID 表。
站点改版（只要语言子页仍叫 `zh` / `en`）不会失效。

---

## 四、边界（本模块不做的事）

- **不写 `canonical`** —— 那是 SEO 插件的面，越界会与它打架。
- **不写 `robots`** —— 同上。
- **不臆造第三语言** —— 只输出自身语言与配对语言。
- **不为「配对不齐」补假链接** —— 单侧 hreflang 会被整体忽略，宁缺勿造。

---

## 五、怎么验

### 本机离线（零联网）

```bash
# v2.3.15 文章支路（含 page 支路零回归），共 41 项判据
"C:/Users/chirc/.workbuddy/binaries/php/8.4.26-nts/php.exe" \
  _harness_hreflang_article_v2315.php

# 行为级：三类页面 ＋ 单侧残缺 ＋ 非页面，共 9 例
"C:/Users/chirc/.workbuddy/binaries/php/8.4.26-nts/php.exe" _g_harness_c282.php

# 结构级：13 条判据
python _verify_c282_hreflang.py
```

### 线上（上线后）

```bash
python _hl_full_matrix.py     # 全类型矩阵：逐页抓 <head> 数条数
```

| # | 判据 | 取样 |
|---|---|---|
| 1 | 5 对文章页**各自**出齐 3 条且 `x-default` 指中文篇 | 10/190 · 841/193 · 2422/2425 · 2423/2426 · 2424/2427 |
| 2 | **双向成立**：中篇指英篇、英篇指中篇，href 互为对方 | 同上 10 页 |
| 3 | 纯中文文章只 1 条 `x-default` 指自身，**不出 `zh`** | 23 · 69 · 834 等 |
| 4 | **零回归**：16 个语言子页仍 3 条、8 个父栏目页仍 1 条 | 全量 24 页 |
| 5 | 无 `hreflang` href 指向 404 或指向自身组之外 | 全量扫 href |
| 6 | 首页组双向齐备（`/` ↔ `/en/` 互指） | 2 页 |

⚠ **取线上页要带破缓存参数**（如 `?cb=<时间戳>`）：WordPress.com 静态资源有
三层缓存。但 **HTML 页面本身不受此影响**，直接取即可。

⚠ **首页那三条不属本插件**（实测属性顺序不同：首页 `rel→href→hreflang`，
本插件 `rel→hreflang→href`）⇒ 来自主题或 Rank Math。且 `/en/` 侧实测 0 条
⇒ **单侧声明，整组作废**。此项**另案处理**。

---

## 六、写桩测试时的两个坑（本项目已各踩一次）

1. **桩必须定义 `ABSPATH`。** 插件文件开头都有
   `if (!defined('ABSPATH')) { exit; }`。桩若不定义，被 `require` 的文件会
   **静默 `exit`** —— 脚本零输出、退出码却是 `0`，看上去像「跑通了」。
2. **桩必须定义 `add_action`。** 本模块用 `add_action('wp_head', …)`，
   桩缺这个函数会抛致命错误。

两者都会让「探针找不到」被误读成「代码缺陷」。⇒ **先确认桩全，再判结论。**
