# 代码说明

课程要求把项目完整源代码放入 `code/`。代码随数据和分析工作逐步提交。

| 工作 | 源码交付 |
| --- | --- |
| 数据准备 | 客流筛选、检查、清洗和日历合并的脚本，说明如何从官方数据生成共用分析表 |
| 分析与建模 | 探索分析、图表、回归和分类模型的代码，以及评估、优化效果比较和结果导出的步骤 |
| 原型开发 | 原型源码、依赖和运行步骤。用已核验的结果展示数据清洗、可视化、模型评估、优化前后的指标对比和实际应用 |

组长向原型负责人交接图表、模型评估、优化效果对比和预测结果。预测结果按**预测目标日期、口岸和方向**对齐，包含预计人次、高客流概率以及所用预警门槛下的判断。例如，10 月 3 日 18:00 做出的次日预测，目标日期为 10 月 4 日。待结果齐备后一起确认原型的页面、演示案例和运行方式。

脚本和原型用仓库内的相对路径读取项目文件。数据接口见[数据说明](../data/README.md)。

## 客流数据（Issue #1）

使用 Python 3.10 或更新版本，全部脚本仅依赖标准库，无需安装第三方包。在仓库根目录运行：

```bash
# 使用已提交的官方快照离线重建清洗 CSV 和机器核验结果
python code/clean_passenger.py

# 只核对，不联网、不改写文件；不一致时退出码为 1
python code/clean_passenger.py --check

# 质量规则回归测试：缺报、重复、非法人次、日期、分项加总等
python -m unittest discover -s code -p "test_*.py" -v

# 仅在需要更新来源时运行：联网下载、核验后替换快照并重建
python code/clean_passenger.py --download

# 可选：联网重取四份官方历史快照，更新发布时间的样本证据
python code/probe_passenger_release.py
```

`clean_passenger.py` 从 `data/raw/` 读取原表及来源记录，生成 `data/passenger_daily.csv` 和 `data/passenger_audit.json`。原表按 `DD-MM-YYYY` 解析，只接受指定三个口岸和两个方向。原表末尾的空列经验证为空后移除；发现缺报、重复、非法人次或分项加总不一致时，在终端列出异常并终止，不填零、不静默去重，不覆盖已有清洗交付。官方原值为零时保留并在核验结果列出。

`--check` 验证原始 CSV 的 SHA-256、字节数、来源 URL，再逐字节比较生成的清洗表及核验 JSON。它不会重新访问官方网站；更新官方版本后，必须重新审阅核验说明、极值和文件大小。`probe_passenger_release.py` 的归档时间仅用于有限样本的可得性核查，不作为固定发布时间保证。

假期表可用 `python code/build_holidays.py --check` 单独检查。Issue #1 合并后再从最新 `main` 创建 Issue #3 的合表分支。

## 客流与假期合表（Issue #3）

`merge_traffic_calendar.py` 从已交付的 `data/passenger_daily.csv` 和 `data/holidays.csv` 读取数据，按 `date` 做多对一左连接，输出 `data/traffic_calendar.csv` 和 `data/traffic_calendar_audit.json`。保留客流原有 7 列，追加日历除 `date` 外的全部 9 列，包括假期名称和来源链接。所有命令均可离线运行，只需 Python 3.10+ 标准库。

```bash
# 先核对两个前置交付
python code/clean_passenger.py --check
python code/build_holidays.py --check

# 重建分析表与核验结果
python code/merge_traffic_calendar.py

# 只校验现有交付；不写文件，内容不一致时退出码为 1
python code/merge_traffic_calendar.py --check

# 客流清洗及合表测试，共 21 项
python -m unittest discover -s code -p "test_*.py" -v
```

合表前检查字段、日期格式、客流主键、日历日期唯一性、区间覆盖、人次及总和、二元标记、周末、内地假期与补班冲突、标记与名称/来源是否对应。缺报、重复和未匹配日期均明确报错；未匹配不会填为 `0`，重复不会静默去重，异常输入不会覆盖已有输出。普通日没有假期名称或来源是预期的空字符串。

合表后检查行数、主键以及全部客流和日历字段与输入相同，再以 UTF-8 无 BOM、LF 换行按日期、口岸、方向排序输出。核验 JSON 记录行数、未匹配列表、各标记的日期数和客流行数、输入内容校验值与输出 SHA-256。输入校验值在解析并按键排序后，以 UTF-8/LF CSV 计算，所以不同系统的换行方式、BOM 或输入行顺序不会改变内容版本。

`--check` 核对两个输入与现有合表交付的一致性，不重新下载客流或重建假期。官方源版本的核对由上面的两个前置检查负责。A 的合表检查见[分析表合并核验说明](../docs/分析表合并核验说明.md)。C 对照官方原表和公告的结果见[分析表独立复核与建模交接](../docs/分析表独立复核与建模交接.md)。
