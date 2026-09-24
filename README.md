# 天象预报模块 · Astro Forecast

**中国古天文历法的离线预计算引擎 ＋ WordPress 发布插件。**

把「天文量计算」与「页面渲染」彻底切开：所有天文量在本机由 Python 算完、算准、算成数据集，
再经 REST 端点批量入库；WordPress 插件只读自建数据表，**前端零实时计算**。

面向的场合是「一个非技术背景的作者，想在 WordPress 上长期稳定地发布中国天文历法内容」 ——
所以这套东西的重点不在算法炫技，而在**能把天文数据可靠地送上站、并且错了能查出来**。

- **计算内核**：Skyfield ＋ JPL DE421 星历。二十四节气交节时刻、日月食、行星合冲留逆、大距、
  月相月龄、流星雨极大、日出日落与晨昏蒙影。
- **数据面**：四张自定义表（日 / 事件 / 关联 / 日×城），REST 分批导入，字段白名单与复合判重键。
- **发布面**：八个短代码、八个模板，覆盖「今日天象 / 未来预告 / 历史上今日 / 观测地 / 报告下载」。
- **验证面**：六道校验闸门（含 PHP 语法闸与 WordPress 钩子桩测试），本机离线可跑。

---

## 一、它解决什么问题

做中国天文历法科普，最难的不是算 —— Skyfield 已经算得很准。难的是这三件：

1. **托管环境不可控。** 在 WordPress.com 这类托管站点上，主题目录不可写、外部 MySQL 连接不开放、
   WP-CLI 没有。常规做法（改主题模板、直连数据库）全部走不通。
   ⇒ 本模块把模板放进**插件内部**、用 `template_include` 注入；数据入库走 **REST 端点**，
   不依赖任何数据库直连。

2. **算得对不等于送得对。** 数据被服务端拒写时，如果客户端只读回执里的 `written` 字段、
   丢掉 `failed` 与 `errors[]`，那么「服务端拒绝」会被显示成「写入 0 行」——
   排查时毫无线索。列宽差 4 个字符就能让整批数据静默丢失。
   ⇒ 本模块有一条硬规矩：**每个失败点都必须带得出原因**，并且做成判据。

3. **「包对了」不等于「线上对了」。** 静态校验器查的是包内一致性，PHP 桩测试查的是逻辑，
   两者都跑在本机、都碰不到服务器。真正的线上错误只能靠**看站点真实输出**才能发现。
   ⇒ 另有独立的线上验收脚本，九项判据、含空集守卫与扫描面下限。

---

## 二、快速开始

### 2.1 环境

需要 Python ≥ 3.10、PHP ≥ 7.4（仅用于跑插件语法闸与桩测试，不装也能用插件）。

```bash
pip install -r python/requirements.txt
```

`de421.bsp`（JPL 星历，约 17 MB）由 Skyfield 首次使用时自动下载，也可预先放到工作目录。
**本模块不在仓库内分发星历文件**（JPL 自有其许可条款），首次运行请留出联网下载时间。

### 2.2 算一天的天象

```bash
python python/compute_sky.py --date 2026-09-24
```

### 2.3 验证环境是否正确

```bash
python python/compute_sky.py --selftest        # 预期：通过 31 项，失败 0 项
python python/build_dataset.py --selftest      # 预期：通过 51 项，失败 0 项
```

### 2.4 装插件

把 `wp-astro-forecast/` 整个目录打包为 zip，在 WordPress 后台「插件 → 上传插件」安装并启用。
启用后第一步访问：

```
GET /wp-json/kcj-astro/v1/health
```

核对返回的 `tables`（各表 `exists` / `rows`）与 `freshness`。逐屏可照做的版本见
[`docs/deploy.md`](docs/deploy.md)。

### 2.5 推数据

```bash
python python/build_dataset.py --wp-site https://example.com \
    --wp-user <用户名> --wp-app-password '<应用程序密码>'
```

应用程序密码路径：WordPress 后台「用户 → 个人资料 → 应用程序密码 → 新建」。
**不要用登录密码** —— 登录密码在多数托管环境下无法用于 REST 鉴权。

---

## 三、目录结构

```
astro-forecast/
├── python/                       # 计算内核与数据集构建
│   ├── compute_sky.py            #   单点/区间计算、历史回推、自检
│   ├── event_almanac.py          #   事件枚举：求根引擎 + 七个生成器
│   ├── history_events.py         #   历史天象回推（三族自算）
│   ├── build_dataset.py          #   数据集构建与 REST 推送
│   ├── build_site.py             #   观测地维度数据集
│   ├── build_places.py           #   观测地清单构建
│   ├── gen_astro_report.py       #   月/季/年度报告离线生成
│   └── requirements.txt
├── wp-astro-forecast/            # WordPress 插件
│   ├── wp-astro-forecast.php     #   主文件
│   ├── includes/                 #   八个模块，见下
│   ├── templates/                #   八个模板
│   ├── assets/                   #   CSS ＋ 两个前端脚本 ＋ 观测地清单
│   └── data/                     #   观测地清单 ＋ 三份样例（随包分发）
├── sql/install_tables.sql        # 四张表的建表语句
├── samples/                      # 三份样例（全部由真实计算生成）
├── docs/                         # 部署、验收、评审、校验、SEO 等十二份文档
├── verify_package.py             # 交付件静态校验器
├── php_selftest.py               # PHP 语法闸 ＋ WordPress 钩子桩测试
├── live_verify.py                # 线上验收（上传后跑）
├── make_zip.py                   # 打包器（字节可复现）
└── README-full.md                # 开发全程的完整记录（版本沿革与逐版缺陷）
```

### 3.1 `includes/` 模块职责

| 文件 | 职责 |
|---|---|
| `class-astro-db.php` | 表结构**唯一正本**（`create()` 走 dbDelta；`health()` 供 REST 自检） |
| `activation.php` | 激活/停用/清缓存的薄壳（**不注册 CPT** —— CPT 必须在每个请求的 `init` 上注册，写在激活钩子里会导致详情页必然 404） |
| `cpt.php` | CPT ＋ 分类法 ＋ 九个元字段 ＋ 模板注入 ＋ 旧 URL 301 |
| `shortcodes.php` | 八个短代码 ＋ 事件详情渲染块 |
| `rest-import.php` | REST 导入端点（四个路由） |
| `cron.php` | 定时任务与数据新鲜度审计 |
| `compliance.php` | 免责声明自动挂载 ＋ 可选自动内链 ＋ 设置页 |
| `rankmath.php` | Rank Math 适配与 JSON-LD |

### 3.2 四张表

| 表 | 粒度 | 唯一键 |
|---|---|---|
| `wp_astro_daily` | 日（**地心量**，与观测地无关） | `uk_jd`（TT 尺度）＋ `uk_date_str` |
| `wp_astro_events` | 事件 | `uk_slug` |
| `wp_astro_relations` | 关联（1NF） | `uk_from_to_rel` |
| `wp_astro_daily_site` | **日 × 城**（观测地量十一项） | `uk_date_city(date_str, city)` |

全部 `ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`。
`sql/install_tables.sql` 与插件内 dbDelta **逐列一致**（含列类型与列宽），已由校验器双向对拍。

> 复合唯一键 `(date_str, city)` 缺不得：少了它，「同一天的第二座城会覆盖第一座，且不报错」。

---

## 四、短代码

| 短代码 | 用途 |
|---|---|
| `[astro_hub]` | **三栏目外壳**：把今日 / 未来 / 历史上今日渲染成页内三栏目（纯 CSS 切换、零 `<script>`、打印全展开） |
| `[astro_today date place]` | 今日天象区块，含观测地选择器 |
| `[astro_forecast_list type side]` | 天象事件列表（六类事件 = 六个 Tab） |
| `[astro_history_today date types nav]` | 历史上今日天象 ＋ 汇总报告下载 |
| `[astro_forecast_report period]` | 月/季/年度报告 ＋ 下载（MD / CSV / 打印） |
| `[astro_related_events id mode]` | 事件关联（古今对照） |
| `[astro_event_detail id]` | 事件详情渲染块 |
| `[astro_places_hub]` | **观测地总览页**：省份 Tab ＋ 城市网格 ＋ 原生 `<select>` 兜底（建议独占一页，如 `/observatories/`） |

**八个**短代码，参数总表见 [`docs/deploy-hub.md`](docs/deploy-hub.md)。

### 观测地：为什么单开一页

340 个预置观测地若全部渲染进首页，实测首页 HTML 有近一半体积是城市标记，
把「今天是什么天象」挤到很下面。**推荐做法**：首页只放
`[astro_today]`（它自带「当前观测地」显示、自动定位按钮、以及一个指向总览页的
「切换观测地」小链接），网格另用 `[astro_places_hub]` 单开一页。

两页之间用浏览器 `localStorage` 承接选择结果（键名 `kcj_astro_place`），
**不用 URL 参数** —— 观测地是访客的居住地，不该出现在地址栏、浏览器历史与
服务器日志里。总览页的地址由插件自动发现（正文含 `[astro_places_hub]` 的页面），
也可用 `kcj_astro_places_hub_url` 选项显式指定。

---

## 五、验证闸门

六道本机离线闸门（另有第七道线上验收，见下）：

```bash
python python/compute_sky.py --selftest        # 预期：通过 31 项
python verify_package.py                       # 预期：通过 470 项
python php_selftest.py                         # 预期：通过 48 项
python python/build_dataset.py --selftest      # 预期：通过 51 项
python python/event_almanac.py --selftest      # 预期：通过 228 项
python python/event_almanac.py --verify        # 预期：对拍 57/57
python make_zip.py --selftest                  # 预期：通过 7 项（证打包幂等）
python python/history_events.py --selftest     # 三族真算 11 年 ＋ 7 条负控制
```

**上传之后**再跑线上验收：

```bash
python live_verify.py --base https://example.com
KCJ_WP_USER=<用户名> KCJ_WP_APP_PASSWORD='<应用程序密码>' \
    python live_verify.py --base https://example.com    # 连版本号一起验
```

它只看站点真实输出，含**空集守卫**（扫到 0 条即报红，不放行）与**扫描面下限**
（`MIN_SCAN_PAGES`，页面数缩水即报红）。

### 关于「负控制」

校验器里每一条判据都配了**负控制** —— 一条被故意写坏、必须报红的样本。
一条判据若是空壳（恒真），它给出的「全绿」只是心安，不是证据。
本仓库现有负控制 **五十余条**，含若干条**变异测试**：把规则本身改坏，验证判据确实会红。

---

## 六、已知缺口（如实）

| 缺口 | 性质 |
|---|---|
| **日食不自算** | 本模块**照录** NASA GSFC 日食目录，不做自算。不是能力不足，是取舍：自造的日食时刻看起来很像真的，但错得无法察觉。目录覆盖范围外须人工补录 |
| **传统天象无生成器** | 传统天象（客星、彗孛等）不是可计算事件，只能由人工条目表逐条录入史料 |
| **食分模块** | 现只给「必要条件」判定，精确食分与见食带属独立模块 |
| **历史段族级覆盖非 100%** | 已实测三族并集覆盖 366/366，但「这一天确实没有」与「还没录入」仍要靠族级 `coverage` 逐族读，不能只看条数 |
| **PHP 桩测试覆盖一条链** | `php -l` 语法闸覆盖全部 23 件 PHP，但钩子桩测试只覆盖 `rankmath.php` 一条链；CPT / 短代码 / REST 仍无运行时判据 |
| **大数据集不入库** | 全量观测地数据集（数十 MB 量级）由 `build_site.py` 现场产出，不进仓库 —— 算法公开，数据自产 |

完整缺口清单与逐条证据见 [`docs/feasibility-review.md`](docs/feasibility-review.md) 与
[`docs/verification-report.md`](docs/verification-report.md)。

---

## 七、引用与许可

- **代码**：MIT，见 [`LICENSE`](LICENSE)。
- **数据与文档**：CC BY 4.0，见 [`LICENSE-DATA`](LICENSE-DATA)。
- **星历**：`de421.bsp` 来自 JPL，**不在本仓库内**，请遵循 JPL 自身条款。
- 观测地清单由公开行政区划数据整理。

---

## 八、Star History

如果这套东西对你有用，欢迎引用其配套的数据集与预印本（见
<https://github.com/Kuangchujia/chinese-calendar-dataset>）。

> **开发全程记录**（版本沿革、逐版缺陷与修法）见 [`README-full.md`](README-full.md) —— 那份是
> 面向维护者的，记录了每一次「线上跑真数据才暴露」的缺陷及其根因。本文件是面向使用者的。
