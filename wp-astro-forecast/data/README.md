# data/ —— 导入用 JSON 数据（指令 01 的 `/data/` 目录）

本目录服务于《WordPress 站点天象模块落地指令集》指令 01 的目录要求：
> `/data/`：导入用的 JSON 数据

## 为什么这里只有样例，没有全量数据

插件的 zip 是要上传到 WordPress 后台安装的。日粒度承诺档是
**1900-01-01 至 2050-12-31（≈5.5 万天）**，单条记录约 2—4 KB，
全量塞进 zip 会让安装包膨胀到几百 MB —— 既传不上去，也没必要（站点只读数据库）。

因此目录分工是：

| 位置 | 内容 | 是否进 zip |
|---|---|---|
| `wp-astro-forecast/data/`（本目录） | 结构说明 + 3 份小样例 | 是 |
| 仓库根 `astro-forecast/data/` | 实际产出的数据集（NDJSON 分片 + manifest） | 否 |

后者由 `python/build_dataset.py` 生成，再用 REST 端点推送入库。插件**不读取**本目录，
它只是「随插件分发的一手结构参考 + 手工导入演示」。真要手工导入时，
把根目录产出的 NDJSON 转成 SQL 后走 phpMyAdmin 亦可（但 WordPress.com 不提供，
所以线上请一律走 REST）。

## samples/ 三份文件

| 文件 | 来源 | 用途 |
|---|---|---|
| `daily_sample.json` | `compute_sky.py --emit-samples` 实算 | 日记录结构（太阳/月球/五星/宿度/声明） |
| `future_event_sample.json` | 同上 | 未来事件结构（Event 类字段） |
| `historical_event_sample.json` | 同上 | 历史事件结构（含**真算**的月相与回推值、三层文本） |

三份**都是实算产出**，不是手写占位数。校验方法：`python verify_package.py`
会断言它们含 `method` / `ephemeris` 等溯源键，且历史样例的时间是**区间**
（`time_bj_earliest` < `time_bj_latest`）而非唯一时刻。

历史样例对应《春秋》隐公三年「春王二月己巳，日有食之」（公元前 720 年 2 月 22 日）。
其 `literature` 只引古籍正本（`《春秋》[M]. 先秦.`），不引近现代注本。

## 字段与列的对应关系

推送时按 REST 白名单过滤，**键名必须与表列同名**，多余键会被服务端丢弃：
白名单定义在 `includes/rest-import.php` 的 `kcj_astro_rest_columns()`。

- `daily`：`date_str` `jd` `data_json` `data_version` `method` `special_event_ids`
- `events`：`event_id` `event_type` `jd_core` `event_time_bj` `time_uncertainty` `dt_model`
  `post_id` `title` `slug` `summary` `params_json` `obs_guide` `obs_site` `literature`
  `discussion` `source_ref` `method` `ephemeris` `publish_status`
- `relations`：`from_event` `to_event` `rel_type`

`jd` 与 `jd_core` 一律是 **TT 尺度**（JDE）。UT 尺度另存在 `data_json.jd_ut` 里备查。

## 怎么生成与推送

```bash
# 干跑 3 天，快速自检（约 4 秒）
python python/build_dataset.py --limit 3 --dry-run

# 生成未来一年
python python/build_dataset.py --start 2027-01-01 --end 2027-12-31

# 推送到站点（WordPress.com：用「应用程序密码」，路径 用户 → 个人资料 → 应用程序密码）
python python/build_dataset.py --start 2027-01-01 --end 2027-12-31 --push \
  --wp-site https://kuangchujia.com --wp-user <用户名> --wp-app-password <应用程序密码>
```

推送分批 200 行/请求（服务端上限 500）。导入成功后服务端会**自动清 transient 缓存**，
无需客户端另行触发。

## 幂等性承诺

配合 v1.2.0 的表结构（`daily` 上 `uk_date_str`、`relations` 上 `uk_from_to_rel`）：

- 同一日期重复导入 = **更新**，不会插出第二行；
- 同一关系重复导入 = **更新**，不会追加重复行；
- 因此「先干跑、再正式推、怀疑时重推一次」是安全的操作方式。

> 从 v1.1.0 升级时若表内已有重复行，加唯一键会失败。清理语句见
> `sql/install_tables.sql` 末尾的「激活/迁移说明」。

## 已知缺口（如实声明）

`build_dataset.py` 中的**事件集目前只是结构样例**：

- `events_future.json` 为空数组。原因：`compute_sky.py` 里只有单日检测器
  `identify_special_events()`，它不返回事件核心时刻、不做跨日去重，
  用它落库会产出成串重复 slug 与失真的 `jd_core` —— 那等于伪造时刻精度，故不用。
- `events_historical.json` 含 2 条结构样例：`params_json` 内是**真实回推值**
  （最近朔望、ΔT 不确定度、日月黄经与宿度），但 `title` / `summary` /
  `literature` / `source_ref` 标为 `TODO-人工补录`，`publish_status=0`。

要自动枚举事件，还缺四件（缺一不可）：① 事件时刻求根；② 事件级参数模块
（食分与见食带、流星雨辐射点与 ZHR）；③ 去重与 slug 生成规则；④ 人工史料条目表。
