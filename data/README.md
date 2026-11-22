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

## 假期与调休

日历按日期整理，分别记录香港公众假期、内地放假与内地调休补班。建议分别标记周末和香港公告列出的节庆、公众假日与补假。常规星期日按周末记录。假期落在周末时可以同时有两种标记。

- 香港公众假期及补假。 [2024 年公告](https://www.info.gov.hk/gia/general/202305/25/P2023052500209.htm) · [2025 年公告](https://www.info.gov.hk/gia/general/202405/03/P2024043000414.htm) · [2026 年公告](https://www.info.gov.hk/gia/general/202505/16/P2025051300354.htm)
- 内地放假与调休补班。 [2024 年国务院办公厅通知](https://big5.www.gov.cn/gate/big5/www.gov.cn/zhengce/zhengceku/202310/content_6911528.htm) · [2025 年国务院公报](https://www.gov.cn/gongbao/2024/issue_11726/material/gwygb202433.pdf) · [2026 年国务院公报](https://www.gov.cn/gongbao/2025/issue_12406/material/gwygb202532.pdf)

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

客流全量 CSV 的实际记录数、日期连续性和提交文件大小，安排在数据准备阶段验收。
