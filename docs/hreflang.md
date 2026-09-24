# hreflang 双语互指（v2.3.7）

> 面向使用者：本文件说清「哪些页面会输出什么标签」「为什么这么输出」「怎么验」。
> 完整根因与修法见 [`feasibility-review.md`](feasibility-review.md) 与插件头 changelog。

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
| **父栏目页 / 列表页** | 只出 `x-default` 指自身 | 1 |
| **首页 / 归档 / 普通页** | 只出 `x-default` 指自身 | 1 |
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
# 行为级：三类页面 ＋ 单侧残缺 ＋ 非页面，共 9 例
php _g_harness_c282.php

# 结构级：13 条判据
python _verify_c282_hreflang.py
```

### 线上（上线后）

打开任意语言子页，查看源码 `<head>`：

```
https://<站点>/publications/zh/     → 应见 zh-CN / en / x-default 三条，x-default 指 zh 页
https://<站点>/publications/en/     → 应见 zh-CN / en / x-default 三条，x-default 指 zh 页
https://<站点>/publications/        → 应只 x-default 一条，指自身
```

⚠ **取线上页必须带破缓存参数**（如 `?v=<时间戳>`）：WordPress.com 静态资源有
三层缓存，无参数会取回 CDN 旧副本。但 **HTML 页面本身不受此影响**，直接取即可。

---

## 六、写桩测试时的两个坑（本项目已各踩一次）

1. **桩必须定义 `ABSPATH`。** 插件文件开头都有
   `if (!defined('ABSPATH')) { exit; }`。桩若不定义，被 `require` 的文件会
   **静默 `exit`** —— 脚本零输出、退出码却是 `0`，看上去像「跑通了」。
2. **桩必须定义 `add_action`。** 本模块用 `add_action('wp_head', …)`，
   桩缺这个函数会抛致命错误。

两者都会让「探针找不到」被误读成「代码缺陷」。⇒ **先确认桩全，再判结论。**
