# 数据来源与验收

## 客流数据

香港特别行政区政府入境事务处提供逐日统计。项目使用 2024-01-01 至 2026-10-31 的罗湖、落马洲支线和深圳湾记录，每个口岸每天区分入境和出境。数据来源及权利归属为香港特别行政区政府入境事务处，数据经 DATA.GOV.HK 提供。提交数据时一并记录原始链接、下载日期和使用区间。 [官方英文逐日客流 CSV](https://www.immd.gov.hk/opendata/eng/transport/immigration_clearance/statistics_on_daily_passenger_traffic.csv) · [官方英文字段说明](https://www.immd.gov.hk/opendata/eng/transport/immigration_clearance/data_specification_for_statistics_on_daily_passenger_traffic.pdf) · [DATA.GOV.HK 使用条款](https://data.gov.hk/en/terms-and-conditions)

| 官方字段（英文版） | 建议提交字段 | 说明 |
| --- | --- | --- |
| Date | `date` | 观测日期，统一为 `YYYY-MM-DD` |
| Control Point | `control_point` | Lo Wu、Lok Ma Chau Spur Line、Shenzhen Bay |
| Arrival / Departure | `direction` | `arrival` 为入境香港，`departure` 为出境香港 |
| Hong Kong Residents | `hong_kong_residents` | 香港居民人次 |
| Mainland Visitors | `mainland_visitors` | 内地访客人次 |
| Other Visitors | `other_visitors` | 其他访客人次 |
| Total | `passengers` | 对应日期、口岸和方向的总人次 |

### 客流清洗交付（Issue #1）

[`passenger_daily.csv`](passenger_daily.csv) 已交付，UTF-8、逗号分隔、LF 换行，按 `date + control_point + direction` 升序排列。日期为文本 `YYYY-MM-DD`，四个人次字段均为非负整数，单位为人次；入境和出境以香港为参照。`Lok Ma Chau Spur Line` 是落马洲支线，不包含 `Lok Ma Chau`。

2026-11-23 下载的官方原表覆盖 2021-01-01 至 2026-11-22。清洗表仅保留项目区间 2024-01-01 至 2026-10-31，共 **1,035 天、6,210 条**，六个口岸方向组合各 1,035 条。主键无重复、日期无缺报，四个人次字段无缺失或零值，三类旅客之和逐行等于总人次。只进行筛选、日期格式转换、方向映射和排序，未填补、删去极端值或修改人次。

- [核验说明](../docs/客流核验说明.md)：清洗口径、分组覆盖、抽查、异常处理、发布时间的证据与限制，以及交付大小。
- [`passenger_audit.json`](passenger_audit.json)：由脚本生成的覆盖、质量、分组统计和输出校验值。
- [`raw/statistics_on_daily_passenger_traffic.csv.gz`](raw/statistics_on_daily_passenger_traffic.csv.gz)：完整官方 CSV 的无损压缩快照，解压后保留原始字节。
- [`raw/passenger_source.json`](raw/passenger_source.json)：官方链接、香港时间下载时刻、HTTP 响应时间、Last-Modified、大小和 SHA-256。
- [`passenger_release_evidence.json`](passenger_release_evidence.json)：2026-10-01 至 10-04 的官方历史快照归档时间及最新日期的六条客流。

在仓库根目录运行 `python code/clean_passenger.py` 可离线重建；`python code/clean_passenger.py --check` 核对原始快照和交付内容。显式加 `--download` 才会联网刷新原始快照，刷新后需重新审阅核验说明。完整命令见[代码说明](../code/README.md)。

历史快照样本支持预测目标日 D 时，在 D−1 日 18:00 暂用 D−2 及更早客流。每日固定首发时刻、全区间延迟和历史修订仍未确认，不能将本次下载的修订后历史表等同于当时可见版本，详见核验说明。

## 假期与调休

[`holidays.csv`](holidays.csv) 为 UTF-8 CSV，按 `date` 升序排列，覆盖 2024-01-01 至 2026-10-31（含首尾），每个日期一行。客流表可按 `date` 多对一连接，同一日期的各口岸和方向共用这些标记。

- 香港公众假期及补假。 [2024 年公告](https://www.info.gov.hk/gia/general/202305/25/P2023052500209.htm) · [2025 年公告](https://www.info.gov.hk/gia/general/202405/03/P2024043000414.htm) · [2026 年公告](https://www.info.gov.hk/gia/general/202505/16/P2025051300354.htm)
- 内地放假与调休补班。 [2024 年国务院办公厅通知](https://app.www.gov.cn/govdata/gov/202310/25/508678/article.html) · [2025 年国务院公报，第 23 页](https://www.gov.cn/gongbao/2024/issue_11726/material/gwygb202433.pdf#page=23) · [2026 年国务院公报，第 17–18 页](https://www.gov.cn/gongbao/2025/issue_12406/material/gwygb202532.pdf#page=17)

| 字段 | 口径 |
| --- | --- |
| `date` | 本地日历日期，格式为 `YYYY-MM-DD` |
| `hk_holiday` | 香港年度公告逐项列出的公众假期或补假为 `1`，其余为 `0`。公告中的通用星期日条目由 `is_weekend` 表示，遇星期日顺延的节日按公告所列的补假日期标记 |
| `mainland_holiday` | 国务院办公厅公告所列连休区间内为 `1`，含区间内的周末，其余为 `0`。2024 年端午节与周末连休按 6 月 8–10 日记录。[中国政府网英文日历](https://english.www.gov.cn/policies/latestreleases/202310/25/content_WS65387be8c6d0868f4e8e0a04.html) |
| `mainland_makeup_workday` | 内地公告明确指定补班的日期为 `1`，其余为 `0` |
| `is_weekend` | 星期六、星期日为 `1`，周一至周五为 `0`。与两地假期及内地补班标记独立 |
| `hk_holiday_name`、`mainland_holiday_name` | 对应的假期名称。内地 2025 年国庆节、中秋节按公告使用同一假期名称 |
| `mainland_makeup_workday_for` | 内地补班对应的假期名称 |
| `hk_source_url`、`mainland_source_url` | 两地假期或内地补班的官方公告链接。未标记的地区名称和链接字段为空 |

### 日历核验

| 覆盖年份 | 日历天数 | 香港公众假期及补假 | 内地放假 | 内地调休补班 |
| --- | ---: | ---: | ---: | ---: |
| 2024 | 366 | 17 | 30 | 8 |
| 2025 | 365 | 17 | 28 | 5 |
| 2026（截至 10 月 31 日） | 304 | 15 | 33 | 6 |
| 合计 | 1,035 | 49 | 91 | 19 |

逐日检查了日期顺序、唯一性和连续性，根据上面的官方公告核对了假期及补班日期。以下几处在合表后可用于抽查。

- 2024-02-11 为星期日，香港农历年初二顺延对应的补假记在 2024-02-13（农历年初四）。2024-02-09 内地除夕仅为公告鼓励安排休息的日期，内地放假标记为 `0`。
- 2025-09-28、2025-10-11 为内地调休补班。内地国庆节、中秋节连休为 10 月 1–8 日，香港「中秋節翌日」为 10 月 7 日。
- 2026-04-06 香港清明节补假和 2026-04-07 香港复活节星期一增补假各占一行。2026-05-25 和 2026-10-19 分别为香港佛诞、重阳节补假。2026-09-20 和 2026-10-10 为内地国庆节调休补班。

在仓库根目录运行 `python code/build_holidays.py` 可离线重建日历。运行 `python code/build_holidays.py --check` 可检查现有 CSV 是否与脚本一致。

## 拟交付的文件

| 建议文件名 | 内容 |
| --- | --- |
| `passenger_daily.csv` | 三个口岸按日期和方向清洗后的客流数据 |
| `holidays.csv` | 每日的 `date`、`hk_holiday`、`mainland_holiday`、`mainland_makeup_workday`，记录节假日名称和来源 |
| `traffic_calendar.csv` | 按日期合并的共用分析表，保留口岸和方向，供项目负责人开始分析 |

## 数据交接的核验要求

1. 观测区间共 1,035 天。三个口岸和两个方向全部齐全时应有 **6,210 条**。检查实际覆盖、日期断点和 `date + control_point + direction` 的唯一性，并列出异常记录。
2. 检查人次为非负整数，核对三类旅客之和与总人次。区分真实零值和缺报。对重复、缺失或异常的处理保留记录。
3. 抽查两地假期和调休补班日期与公告一致，确认按日期合表后客流记录没有重复或丢失。
4. 核对官方数据的实际发布时间。做历史回测时，按预测日前一天香港时间 18:00 确定哪些观测已经能取得。
5. 提交数据来源、字段说明、可复现的清洗脚本、核验结论与项目使用的数据。交付的数据文件合计控制在 **10 MB 以内**。

客流全量快照有 63,678 条；本次筛选后的日期连续性和交付大小已核验。当前 `data/` 下数据及 JSON 凭据共 1,009,940 字节（不含本说明），低于 10 MB。合表后的重复、丢失和假期匹配检查由 Issue #3 完成。
