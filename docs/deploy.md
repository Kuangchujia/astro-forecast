# 部署上线说明（交付物 G · **v2.0.0**）

**先结论**：本站托管在 **WordPress.com**，因此三条「常规做法」在此**不可用**，已按可行路径改道：

1. **不开放外部 MySQL** ⇒ 不能用 `mysql <` 直连、也不能 `--db` 直连，数据一律走插件 REST 端点导入。
2. **主题目录不可写且升级会覆盖** ⇒ 模板不能放进 `wp-content/themes/seedlet/`，改为**插件内置模板 + `template_include` 注入**（F21）。
3. **站外 Python 进程触发不了 WP action** ⇒ 「构建后调用 `do_action('kcj_astro_refresh_cache')`」作废，改为**导入成功后服务端自动清缓存**。

按本文顺序执行即可；每一步都给了**可复制的命令**与**验证判据**。

---

## 0. 前置条件

| 项 | 要求 | 说明 |
|---|---|---|
| 站点 | kuangchujia.com（WordPress.com 托管） | **★ 已实测（2026-09-23）具备第三方插件安装能力**：站上 Rank Math 正在运行（首页第 39 行 `class="rank-math-schema"`，REST 根暴露 `rankmath/v1` 及 5 个子命名空间）⇒ 计划为 **Business／Commerce 级**（WP.com 装插件的最低门槛）。WP.com 无 SFTP，**只能走后台 UI 上传** |
| 主题 | Seedlet | **主题目录不可写**，故模板内置在插件里 |
| PHP | ≥ 7.4 | — |
| MySQL | ≥ 5.7（InnoDB / utf8mb4） | 由 `dbDelta` 建表 |
| Python | ≥ 3.10 + skyfield 1.55 + skyfield_data 7.0.0 | 解释器用本机托管 venv 绝对路径（见 §5） |
| ACF | **不需要** | 数据存自建三表 |
| 应用程序密码 | 需具备 `edit_posts` 的账号 | 见 §5 |

---

## 1. 上传插件并启用

**WP.com 没有 SFTP／文件管理器，上传只能走后台 UI。**

1. 登录 `https://kuangchujia.com/wp-admin/` → **插件 → 安装插件 → 上传插件**
   （直达：`https://kuangchujia.com/wp-admin/plugin-install.php?tab=upload`）
   → 选 `wp-astro-forecast.zip` → **现在安装** → **启用**。
   ★ **直接传 zip，不要解压**（后台自己解）。
2. 激活钩子执行：`dbDelta()` 建三表 + 排程定时任务 + `flush_rewrite_rules()`。
   **注意**：CPT 注册**不在**激活钩子里，而是在每个请求的 `init` 上（v1.1.0 的 404 必崩缺陷即由此而来，见 F20）。
3. 验证包完整性：zip 共 **20 条目**、**63,657 字节**；根目录唯一且为 `wp-astro-forecast/`。
   指纹（**v1.3.0**，2026-09-23，含结构化数据归属修正 F37/F38）：SHA1 `615314a71f38f62b77e768997e948e339b90e579` ／ MD5 `a6644d57f2eb7e2247ed0e8c95340e9f`。
   （上一版 v1.2.1 为 61,190 B ／ SHA1 `835195641e5ba80a399141ac6fff290a53b761d7`。）
   本包由 `make_zip.py` 生成：**文件集由磁盘现状决定、时间戳固定 ⇒ 连打两次字节完全相同**（`python make_zip.py --selftest` 可自证）。
4. ★ **本站当前状态（2026-09-23 实测，已更新）**：本插件 **v1.2.0 已安装并运行中** ——
   `/health` 返 `ok:true, plugin:"1.2.0"`，三表 `exists` 全 `true`；归档页 `/sky-forecast/` 200 且模板生效；
   旧件 `wp-astro-cpts` 未启用 ⇒ **不存在双重注册冲突**。
   ⚠ **但 v1.2.0 有列宽缺陷（F22）**：`data_version` 列宽 32 而真值 36 字符，导入该行会被 MySQL 拒收。
   ⇒ **必须重传 v1.2.1**（见第 6 步）。§3 的「升级前置去重语句」仍**无需执行**（那条只针对「从 v1.1.0 升到 v1.2.0」的历史重复行）。
5. **兜底**：若启用后白屏／500，WP.com 会向管理员邮箱发 **Recovery Mode** 链接；
   也可直接访问 `https://kuangchujia.com/wp-admin/plugins.php` 停用本插件。
6. ★ **从 v1.2.0 升到 v1.2.1（本次必做）**：同一个上传入口，选新版 zip → **替换**（WP 会自动停用再启用）。
   **不需要手动执行任何 SQL**：插件新增了表结构版本守卫 —— `KCJ_ASTRO_SCHEMA`（与插件版本解耦）
   与 option `kcj_astro_schema_version` 不符时，**在 `init` 上自动跑 `dbDelta` 增量升级**，
   首访即把 `data_version` / `dt_model` 由 `VARCHAR(32)` ALTER 成 `VARCHAR(64)`。
   **验证判据**（重传后跑一次）：
   ```bash
   curl -s -u "<用户名>:<应用程序密码>" \
     "https://kuangchujia.com/wp-json/kcj-astro/v1/health"
   ```
   要看的三个地方：
   1. `plugin` 应为 `"1.2.1"`。若仍是 `"1.2.0"`，说明后台没真换上新包（WP.com 有时需手动停用→删除→重传）。
   2. `schema.ok` 应为 `true`，且 `schema.widths` 里 `daily.data_version` 与 `events.dt_model`
      都应为 **64**。⇒ 这是**直接读实测列宽**，比「推一行数据看报不报错」可靠得多
      （v1.2.1 第二批新增，F26）。
   3. 若 `schema.ok` 为 `false`：`schema.shortfalls` 会写明缺口；此时守卫**不会落账**，
      下一次访问仍会自动重试（自我修复，不会卡死）。连试仍不成 ⇒ 用下面的兜底 ALTER。
   最后再推一次数据，确认端到端：`written` = 行数、`failed` = 0。

   **兜底 ALTER（仅当上面第 2 条始终不达标时）** —— 用数据库管理工具手动执行：
   ```sql
   ALTER TABLE wp_astro_daily  MODIFY COLUMN data_version VARCHAR(64) NOT NULL DEFAULT 'v1';
   ALTER TABLE wp_astro_events MODIFY COLUMN dt_model     VARCHAR(64) NULL;
   ```
   （`wp_` 换成实际前缀。执行后访问任意页，`schema.ok` 应转为 `true`。）

**兜底（若托管环境拒绝程序建表）**：用数据库管理工具手动执行 `sql/install_tables.sql`（把字面量 `wp_` 换成实际前缀）。此方式不会自动建 CPT 相关数据，但 CPT 注册仍由插件负责。

### 1b. ★ 升级到 v1.3.0（2026-09-23 · 本轮必做）

**为什么必须传**：`Event` 结构化数据在 v1.2.x 上**一条都不输出**，且事件详情页连
Person / WebSite / WebPage 都没有（根因是 Rank Math 免费版源码的白名单，见
`docs/rank-math-config.md` §2.5）。**表结构没变** ⇒ `KCJ_ASTRO_SCHEMA` 仍为 `2`，**无需重新激活**、
**无需执行任何 SQL**。**从 v1.2.0 或 v1.2.1 上来都可以，同一个包。**

同一个上传入口 → 选新 zip → **替换**。**上传后跑一条命令，缺一不算完成**：

```bash
# 免凭据也能跑；拿不到版本号的那一项会记「跳过」而不是「通过」
python live_verify.py

# 有应用程序密码时，连版本号一起验（推荐）
KCJ_WP_USER=<用户名> KCJ_WP_APP_PASSWORD='<应用程序密码>' python live_verify.py
```

九项判据（A—I）与「不想跑脚本时手工怎么看」对照：

| 项 | 判据 | 手工怎么看 |
|---|---|---|
| A | `health` 的 `plugin` 回 **`1.3.0`**（旧值 ⇒ 新包没生效，**别对旧包排查**） | `curl -u "<用户名>:<应用程序密码>" https://kuangchujia.com/wp-json/kcj-astro/v1/health` |
| B | **`/?sitemap=1`** 的索引里**列出** `astro_event-sitemap.xml` | 浏览器开 `https://kuangchujia.com/?sitemap=1` → `Ctrl+F` 搜 `astro_event-sitemap`。**查询式入口不受重写规则影响 ⇒ 它通＝类型已注册为 provider** |
| C | **`/?sitemap=astro_event`** 返回 **200** 且 `<loc>` 非空（现为 **80 条**） | 开 `https://kuangchujia.com/?sitemap=astro_event` |
| **B2** | **路径式** `/sitemap_index.xml` 与 `/astro_event-sitemap.xml` 均为 **200**（搜索引擎真正抓的形态） | 浏览器开 `/sitemap_index.xml`。**404 ＝ 重写规则没进 `rewrite_rules`** ⇒ 见下方修法；⚠ 面板里的开关是 ON **不代表**路径可用 |
| D | 79 条事件详情页**每一条**都出 `Event` | 开任一条事件页（如 `/sky-forecast/planet-saturn-opposition-20261004/`）→ `Ctrl+U` → `Ctrl+F` 搜 `"@type": "Event"` |
| E | 每条 `startDate` 都以 **`+08:00`** 结尾 | 同页搜 `"startDate"` |
| F | 事件页都**还有** `WebSite` 与 `WebPage` | 同页搜（F37 曾把它们连同 `Event` 一起弄丢） |
| G | 首页／博文／`/tianwen-rili/` 等**都不再**出现 `揭阳每日天象数据集（）` | `Ctrl+F` 搜 `数据集（）`，应搜不到（F38） |
| H | 含短代码的页（`/tianxiang-yugao/`）**仍**出**完好** Dataset | 该页搜 `揭阳每日天象数据集（2026-` |
| I | 事件归档 `/sky-forecast/` 为 `CollectionPage` | 该页搜 `CollectionPage` |

> ★ **A 项拿不到会记「跳过」，不是「通过」**：没有应用程序密码时，其余八项仍能判「行为对不对」，
> 但分不清「包没生效」与「改了没用」。**上传后第一件事就是确认版本号。**
> ★ **空集守卫**：脚本扫到 0 条事件页会**报红**，不会因为「取不到」而放过（本库踩过「扫到 0 件却报全达标」）。
> ★ **扫描面下限**：判据 G 的扫描面**不能取自被观测对象自身的产物** —— 它原先取自 `/sitemap_index.xml`，
> 而那个地址**正好就是坏掉的那个** ⇒ 21 页会**静默缩到 2 页却照样报绿**。现改为**双入口回落 ＋ 文件名翻译**，
> 并加 **`MIN_SCAN_PAGES = 15` 下限守卫**（不足即报红）。**缩水的扫描面比没有扫描面更危险。**
> ★ **B2 的修法（按顺序，都在用户侧）** —— **2026-09-23 04:37 已按第 ① 步修复，B2 转 200/200，九项全通过**：
> ① `设置 → 固定链接`（Permalinks）→ **什么都不改，直接点「保存更改」**（＝ flush 重写规则）← **只要这一步就够**；
> ② 仍不通 → `Rank Math → Dashboard → Database Tools` 清一次 **sitemap 缓存**；③ 复跑 `python live_verify.py`；
> ④ 再不通 → 查 `Sitemap Settings → General` 的**基名／索引文件名**。**注意 `robots.txt` 的兜底治不了根**：
> 它推荐的 `…/sitemap.xml`（**仍 404**）与 `…/sitemap_index.xml`（**已 200**）。**残留**：`/news-sitemap.xml` 亦 404，
> 但主索引已覆盖全站 ⇒ 收录不受影响（可选清理：删掉那两行 robots 声明，或开 News Sitemap 模块）。
> ★ **判断顺序（本轮绕错过一次）**：**漂亮路径全 404 而查询式全 200 ⇒ 先去「固定链接」按保存**，别先翻插件设置／清缓存。
> ★ **预期告警不列为不通过**：② 的 `Event` 在 Rich Results Test 里会提示**缺少 `location`** ——
> 天文事件无举办场地，插件**有意不填**（`docs/rank-math-config.md` §1 末「`location` 的取舍」）。
> 同理 `isAccessibleForFree` 线上呈 `"1"`（WordPress 核心会把标量串化，见 F39），**不算缺陷**。

---

## 2. 启用后第一步：验三张表与行数

调用健康检查端点（**需应用程序密码**）：

```bash
curl -u "<用户名>:<应用程序密码>" \
  "https://kuangchujia.com/wp-json/kcj-astro/v1/health"
```

返回结构（键名固定）：

| 键 | 内容 | 判据 |
|---|---|---|
| `ok` / `plugin` | 插件版本（应为 `1.3.0`） | 与 zip 一致 |
| `url_infix` | `sky-forecast` | 与 §8 的 URL 口径一致 |
| `tables` | 三表逐一 `{table, exists, rows}` | **三表 `exists` 全为 `true`** |
| `freshness` | 最新日记录 vs 今天 | 空库时为空值，属正常 |

- 若 `exists=false`：建表未成功 ⇒ 走 §1 兜底手动执行 SQL。
- 若返回 401/403：应用程序密码或权限不对 ⇒ 回 §5 重取密码。
- 只读新鲜度（不查表结构）：`GET /wp-json/kcj-astro/v1/freshness`。

---

## 3. 从 v1.1.0 升级的前置动作（**顺序不能颠倒**）

v1.2.0 新增两个唯一键：`wp_astro_daily.uk_date_str` 与 `wp_astro_relations.uk_from_to_rel`。
**若表内已有重复行，加唯一键会失败** ⇒ 必须先清理、再激活新版插件。

### 3.1 先查有没有重复行（可选）

```sql
SELECT date_str, COUNT(*) c FROM wp_astro_daily
 GROUP BY date_str HAVING c > 1;

SELECT from_event, to_event, rel_type, COUNT(*) c FROM wp_astro_relations
 GROUP BY from_event, to_event, rel_type HAVING c > 1;
```

### 3.2 清理重复行（保留最小 `id`）

语句取自 `sql/install_tables.sql` 末尾注释：

```sql
DELETE a FROM wp_astro_daily a JOIN wp_astro_daily b
  ON a.date_str = b.date_str AND a.id > b.id;

DELETE a FROM wp_astro_relations a JOIN wp_astro_relations b
  ON a.from_event = b.from_event AND a.to_event = b.to_event
     AND a.rel_type = b.rel_type AND a.id > b.id;
```

清理完再让新版插件激活（或用 dbDelta 触发一次），唯一键即可加上。

### 3.3 jd 尺度修正（F17）⇒ 需重导

v1.1.0 的解析降级行把 **UT 儒略日当 TT（JDE）** 用了，古代行偏差可达数小时。

- **若曾用 v1.1.0 导入过 1900 年以前或 2053 年以后的数据，请重导这些日期**。
- 重导是**更新而非新增**：`uk_date_str` 唯一键保证同一日期只留一行。
- 重导命令见 §5（把 `--start/--end` 指向需要重导的区间）。

> 2026 年前后的现代数据误差可忽略（实测 2026 年黄经偏 0.01°），不需要为它专门重导。

---

## 4. 刷新重写规则

CPT `astro_event` 与分类法 `event_type` 注册后，重写规则需刷新一次：

后台 → **设置 → 固定链接 → 直接点「保存更改」**（不必改任何值）。

未做这一步的典型症状：`/sky-forecast/` 归档页 404，但后台菜单与编辑页正常。

---

## 5. 计算并推送数据

### 5.1 取应用程序密码

WP 后台 → **用户 → 个人资料 → 页面最下方「应用程序密码」→ 新建应用程序密码** → 复制生成的密码串（只显示一次）。
账号需具备 `edit_posts` 能力（编辑/管理员）。**不要用登录密码。**

### 5.2 先干跑，再真推

```bash
export PATH="/usr/bin:/bin:/mingw64/bin:$PATH"
PY="C:/Users/chirc/.workbuddy/binaries/python/envs/skills/Scripts/python.exe"
cd "D:/OneDrive/文档/Obsidian Vault/公众号/05-工具/astro/astro-forecast/python"

# 1) 干跑：真算，但只统计行数、不发任何请求
"$PY" build_dataset.py --start 2026-01-01 --end 2026-12-31 --jobs 4 --dry-run

# 2) 真推
"$PY" build_dataset.py --start 2026-01-01 --end 2026-12-31 --jobs 4 \
  --push --wp-site https://kuangchujia.com --wp-user <用户名> \
  --wp-app-password '<应用程序密码>'
```

承诺档全量（1900-01-01 — 2050-12-31，约 5.5 万天，4 进程约 1 小时）：

```bash
"$PY" build_dataset.py --start 1900-01-01 --end 2050-12-31 --jobs 4 \
  --push --wp-site https://kuangchujia.com --wp-user <用户名> \
  --wp-app-password '<应用程序密码>'
```

### 5.3 推送口径

| 项 | 值 |
|---|---|
| 端点 | `POST {site}/wp-json/kcj-astro/v1/import` |
| 单请求上限 | **500 行**（插件端硬限） |
| 脚本批大小 | 每批 **200 行**，批间休眠 0.3 s |
| 目标表 | 日记录 `--table daily`（默认）；事件固定写 `events` |
| 幂等键 | daily 按 `jd` / `date_str`；events 按 `slug` |
| 推送后 | 脚本自动再调 `/flush-cache` |

- 产物落仓库根 `data/`（`--outdir` 默认值），另可在 manifest 中查看精算/降级/失败条数与推送结果。
- 事件导入后自动同步为 `astro_event` CPT 文章。

---

## 6. 页面挂载

### 6.1 ★ v2.0.0：天象预告页改为**三栏目**（用户令：不做成菜单）

| 页面 | 状态 | 短代码 |
|---|---|---|
| 天象预告（`/tianxiang-yugao/`） | **已建（page id 258，2026-09-23）**；v2.0.0 起正文**整段换成一行** —— 三个子项由插件渲染成**页内三栏目**（纯 CSS 切换，无脚本） | **`[astro_hub]`**（详见 `docs/deploy-hub.md`） |
| 老黄历页（`/tianwen-rili/`） | ⚠ **不要直接手改该页** —— 它是 `05-工具/astro/gen_huangli.py` 的**生成物**，手动插的短代码块**下次重生成即被抹掉**。要嵌 `[astro_today]` **必须先给生成器加插槽、再重生成** | `[astro_today]`（指定日期：`[astro_today date="2026-10-01"]`） |

**★ 三条不要做**：

1. **不要**为「今日天象／未来天象预告／历史上今日天象」新建**菜单项** —— 它们是页内栏目，不是站级导航。
2. **不要**把栏目切换改成 JS —— 平台后处理会拆断内联脚本（v1.3.0 老黄历失效的真因）。
3. **不要**在页面正文里另写栏目标题 —— 标题由插件生成，手写会造成两处文案漂移。

---

### 6.2 其余页面与短代码
| 老黄历页（`/tianwen-rili/`） | ⚠ **不要直接手改该页** —— 它是 `05-工具/astro/gen_huangli.py` 的**生成物**，手动插的短代码块**下次重生成即被抹掉**。要嵌 `[astro_today]` **必须先给生成器加插槽、再重生成** | `[astro_today]`（指定日期：`[astro_today date="2026-10-01"]`） |

**具体操作**：后台 → 页面 → 选中/新建页面 → 添加「短代码」区块 → 粘贴短代码 → 更新；
或用 REST：`POST /wp-json/wp/v2/pages`，`content` 用 Gutenberg 短代码块 `<!-- wp:shortcode -->\n[astro_today]\n<!-- /wp:shortcode -->`（**实测渲染正常**）。
`[astro_forecast_list]` 留空 `type` 即渲染全部 Tab；`type` 可取 `solar` / `lunar` / `solar_eclipse` / `lunar_eclipse` / `eclipse` / `planet` / `meteor` / `traditional` / `historical`。

关联与详情如需内嵌，另有 `[astro_related_events id="N" mode="auto|historical|future"]` 与 `[astro_event_detail id="N"]`。

---

## 7. Rank Math 配置

指令 07 的标题/描述模板与 Schema 分工，**逐屏配置步骤见 `docs/rank-math-config.md`**。

要点（避免同页两份同类型数据）：

| 能力 | 承担方 |
|---|---|
| `WebPage` / `Event` / `CollectionPage` | Rank Math（免费版可做） |
| `Dataset` / `ScholarlyArticle` | **插件模板直接输出 JSON-LD**（Rank Math 免费版无此类型，自定义 Schema 属 PRO） |

---

## 8. 旧 URL 301 的说明与验证

| 项 | 值 |
|---|---|
| 新归档 | `/sky-forecast/` |
| 新详情 | `/sky-forecast/{slug}/` |
| 旧前缀 | `/sky/forecast/` |

旧前缀已实现 **301** 跳转到新前缀（指令 10 要求无死链）。

**验证方法**（任选其一）：

```bash
# 命令行：看状态码与 Location
curl -sI "https://kuangchujia.com/sky/forecast/" | grep -Ei "HTTP/|location"

# 预期：HTTP/1.1 301 且 location 指向 /sky-forecast/
```

- 浏览器：访问 `/sky/forecast/`，地址栏应自动变为 `/sky-forecast/`。
- 若返回 404 而非 301：先做 §4 刷新重写规则，再重试。
- 注意：301 会被浏览器/CDN 缓存，验证时建议用无痕窗口或加随机查询参数。

---

## 9. 缓存与刷新

| 项 | 机制 |
|---|---|
| 今日天象 | 按日期缓存 12 h（transient，键 `kcj_astro_today_<date>`） |
| 导入后 | 服务端**自动**清缓存，无需另跑刷新 |
| 手动清 | `POST /wp-json/kcj-astro/v1/flush-cache` |
| 定时任务 | 插件后台**跑不了 Python / skyfield**；cron 只做「触发 action + 审计数据新鲜度 + 清缓存」，真正重算在本机 Python 完成后经 REST 推送 |

> WordPress.com 默认禁用真实系统 cron，定时任务的触发时机不完全可控 ⇒ **以本机推送为数据更新的主路径**，cron 仅作审计与兜底。

---

## 10. 回退

### 10.1 轻回退（保留数据）

后台停用插件即可。**表保留**，仅 flush 重写规则；再次启用即恢复。

### 10.2 彻底回退（删数据，不可逆）

```sql
-- 先备份！执行后数据不可恢复
DROP TABLE IF EXISTS `wp_astro_relations`;
DROP TABLE IF EXISTS `wp_astro_events`;
DROP TABLE IF EXISTS `wp_astro_daily`;
```

（表名前缀按实际站点替换；三表有外键语义上的引用关系，建议按上序删除。）

---

## 11. 未覆盖项（如实）

| # | 未覆盖项 | 原因 | 建议 |
|---|---|---|---|
| 1 | ~~本机无 PHP runtime~~ **已线上激活（2026-09-23），无 500** | 环境仍无 PHP 解释器；tree-sitter 只证明语法正确（语法 ≠ 运行时） | 后续若改 PHP，仍需人工盯一次线上 |
| 2 | ~~REST 真机复验~~ **已真机复验（2026-09-23）** | 应用程序密码已拿到，`/health` `/freshness` `/import` 三端点实测通过 | 已办；`/import` 的列宽缺陷见 F22，须重传 v1.2.1 |
| 3 | **dbDelta 在 WP.com 的实际行为** | 建表已线上验证成功（三表齐备） | **增量 ALTER（32→64）待重传 v1.2.1 后验证**；失败则回退到 §1 手工执行 SQL |
| 4 | **REST 推送在托管环境的超时表现** | 未实测 | 已按 200 行/批 + 批间 0.3 s 保守设置；若超时，减小批大小重试 |

---

## 12. 上线前必须跑的验收

```bash
export PATH="/usr/bin:/bin:/mingw64/bin:$PATH"
PY="C:/Users/chirc/.workbuddy/binaries/python/envs/skills/Scripts/python.exe"
cd "D:/OneDrive/文档/Obsidian Vault/公众号/05-工具/astro/astro-forecast"

"$PY" python/compute_sky.py --selftest      # 预期：通过 31 项，失败 0 项
"$PY" verify_package.py                     # 预期：通过 216 项，失败 0 项
"$PY" php_selftest.py                       # 预期：通过 30 项，失败 0 项  ★ 2026-09-23 新增
"$PY" python/build_dataset.py --selftest    # 预期：通过 51 项，失败 0 项
"$PY" python/event_almanac.py --selftest    # 预期：通过 227 项，失败 0 项（约 110 秒）
"$PY" make_zip.py --selftest                # 预期：通过 7 项（自证打包幂等、文件集齐）

# ★ 上传之后才跑（要联网）：线上验收九项 A—I。见 §1b
"$PY" live_verify.py
```

**前六闸都 exit=0 才上传插件包。** 逐项实测值见 `docs/verification-report.md`；上线检查清单见 `docs/acceptance-checklist.md`。

> ★ **第五闸（`php_selftest.py`）为什么必须有**：本机原无 PHP ⇒ 插件代码**从未被执行过一次**，
> 只能靠读源码猜。2026-09-23 的 F37（面板选 `Event` 前台零输出）与 F38（日期为空的 `Dataset`）
> 都是**读到才能发现、跑一次就现形**的那类缺陷。闸门内含**语法闸**（15 个 `*.php` 过 `php -l`，
> 有错＝整站白屏）与**钩子桩测试**（30 项，含负控制）。
> PHP 可执行文件位置与安装法见该文件头部；**它找不到 PHP 会直接报错退出，不会静默跳过**。
>
> ★ **`live_verify.py` 为什么不列进「闸」**：它要联网、且结果取决于线上真实状态
> （2026-09-23 04:2x 那次跑就因**漂亮路径 sitemap 404（B2／F41）**而 exit=1；**04:37 修复后已 exit=0**），
> **当闸门会天天假红**。它的位置是「**上传后的验收**」，不是「上传前的门禁」。
> 六闸查的都是**本机文件**，碰不到线上 ⇒「包对了 ≠ 线上对了」这一段原先没有判据，F37／F38 就漏在这里。

---

## 13. v2.0.0 增量部署（2026-09-23 · 观测地维度与三个子项）

### 13.1 版本与包指纹

| 项 | 值 |
|---|---|
| 插件版本 | **2.0.0**（`KCJ_ASTRO_VER`） |
| 表结构版本 | **3**（`KCJ_ASTRO_SCHEMA`；v1.3.0 为 2） |
| zip | **25 条目 / 91,490 B / SHA1 `b8d07da78ae61015559c8e57af8fa2f61ab92d11`** |

### 13.2 第 4 张表（**自动建，无需手工跑 SQL**）

新增 `wp_astro_daily_site`（观测地维度，24 列）：

* 唯一键 **`uk_date_city (date_str, city)`** —— **复合键**。缺了它，
  同一天的第二座城会**覆盖第一座且不报错**；
* 索引 `idx_city_date (city, date_str)`；
* 原三表不变。

**升级路径**：表结构版本 2 → 3 ⇒ 重传插件后**首次访问即自动 ALTER**
（`init` 守卫比对 option；`create()` 逐列实测列宽，达标才落账）。**无需重新激活插件。**

**验证**：`GET /wp-json/kcj-astro/v1/health` 的 `schema` 段应显示
`option: 3`、`expected: 3`、四张表 `exists: true`。

### 13.3 短代码总表（v1.3.0 为 4 个 → 现 7 个）

| 短代码 | 新增？ | 用途 |
|---|---|---|
| `[astro_hub]` | ★ v2.0.0 | **三栏目外壳**（今日／未来／历史），纯 CSS 切换 |
| `[astro_today place="auto"]` | ★ 加 `place` | 今日天象 ＋ **观测地选择器** |
| `[astro_forecast_report period="month"]` | ★ v2.0.0 | 月/季/年度报告 ＋ 下载 |
| `[astro_history_today]` | ★ v2.0.0 | 历史上今日天象 ＋ 下载 |
| `[astro_forecast_list type="…" side="future"]` | ★ 加 `side` | 事件列表（`side` 默认 `future`，防历史条目混入） |
| `[astro_related_events id="N"]` | —— | 事件关联 |
| `[astro_event_detail id="N"]` | —— | 事件详情块（旧名） |

### 13.4 数据推送（**当前 REST 401 ⇒ 需先解决凭据**）

| 数据 | 生成命令 | 规模 |
|---|---|---|
| 未来事件（重出，覆盖 2026—2028） | `python/build_dataset.py --events-only --events-range 2026 2028` | **145 条** |
| 历史月食（1900—2025） | `python/history_events.py --from 1900 --to 2025` | **288 条**（约 15 分钟） |
| 观测地维度（**340 个地级锚点 × −7/+120 天**） | `python/build_site.py --jobs 8 --format both` | 约 **43,520 行**（**实测 1,987 s ≈ 33 分钟**；`--format both` 另出 SQL 备用件） |

> ⚠ **导入器版本红线（v2.3.1 修）**：v2.3.0 的多行快路径在 `daily_site` 导入时会触发
> **致命错误**（`$flush` 闭包内 `$wpdb` 为 `null`）⇒ **整个导入端点 500、一行也进不去**。
> 线上站点健康页报的正是 `Call to a member function prepare() on null`。
> **务必上传 v2.3.1 及以上再导**；装好后先点一次后台「数据导入」页（使公开信标刷成新版本号），
> 再跑本表最后一行（观测地维度）。
> ⚠ **结构化数据红线（v2.3.2 修）**：v2.3.1 及更早，`includes/rankmath.php` 的 daily
> 判据**只认字面 `[astro_today]`** ⇒ 用 `[astro_hub]` 的页面（**「天象预告」页就是**）
> 虽然页面上看得到「今日天象」，却**不声明 Dataset 结构化数据**（线上探针 H 项实测：
> 期望 1 页、命中 **0** 个）。**上传 v2.3.2 及以上即恢复** —— 该页会与首页一样出
> 「揭阳每日天象数据集（当日）」节点。核验（站外免凭据）：抓 `/tianxiang-yugao/` 源码
> 搜 `"@type":"Dataset"`，应为 **1** 个；首页同样应为 1 个。
> ⚠ **v2.3.0 起观测地规模与耗时都变了，别照抄旧数**：
> · 预置档由 38 城扩到 **340 个地级锚点**（`python/build_places.py` 采集区划中心点与海拔，
>   另出 2,870 个县级可选点就近绑定）。
> · 滚动窗由 −370/+400 收紧为 **−7/+120 天**。理由：`daily_site` **只被「今天」查询**
>   （历史栏读的是 events 表），旧窗是照抄 `daily` 的；观测地 ×8.95 后维持旧窗会得到
>   262,140 行而一个查询都用不到。**行数因此是 43,520（+48%）而不是 262,140（+795%）。**
> · 耗时**不随进程数下降**：实测单进程 0.129 s/行，而 4/8/16 进程分别是 14/11/11 秒（340 行）
>   ⇒ 硬停在约 **31 行/秒**（父进程侧串行点，见 `build_site.py` 文件头）。
>   加进程无益，要缩短只能先修 `run_tasks`。
> · 采集脚本需联网（阿里 DataV ＋ opentopodata），带磁盘缓存 `python/_geo_cache/`，
>   复跑用 `--offline`。属**构建侧**，不进 zip。

**入库三条路**（v2.2.0 起第一条最省事）：① 后台「**数据导入**」页 —— 直接吃包内
`wp-astro-forecast/data/datasets/*.ndjson`，**不需要应用密码、不装 WP-CLI**；
② 重新签发应用密码后走 REST；③ 用 `data/site_daily_*.sql` 手工导入。
> ⚠ 数据件换版后**必须整批重导**：导入器以清单里的 **`sha1`**（而非文件字节数）判「换没换过」——
> 只比字节数会漏掉「同字节数的重排行序」，游标会落在行中间，`fgets` 读回半行 ⇒ 后半段静默丢失。

### 13.5 上线后跑验收

```bash
python verify_package.py     # 包内一致：期望 288 项通过 / 0 失败
python php_selftest.py       # PHP 层：期望 32 项通过 / 0 失败
python live_verify.py        # 线上产物：九项 A—I
```

**页面级验收**（三栏目）：见 `docs/deploy-hub.md` 第七节的 8 条判据。
