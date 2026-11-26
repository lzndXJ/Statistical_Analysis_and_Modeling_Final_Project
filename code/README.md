# 代码说明

课程要求把项目完整源代码放入 `code/`。代码随数据和分析工作逐步提交。

| 工作 | 源码交付 |
| --- | --- |
| 数据准备 | 客流清洗、日历与天气整理，以及生成共用分析主表的脚本 |
| 分析与建模 | 探索分析、图表、回归和分类模型的代码，以及评估、优化效果比较和结果导出的步骤 |
| 原型开发 | 原型源码、依赖和运行步骤。用已核验的结果展示数据清洗、可视化、模型评估、优化前后的指标对比和实际应用 |

组长向原型负责人交接图表、模型评估、优化效果对比和预测结果。预测结果按**预测目标日期、口岸和方向**对齐，包含预计人次、高客流概率以及所用预警门槛下的判断。例如，10 月 3 日 18:00 做出的次日预测，目标日期为 10 月 4 日。待结果齐备后一起确认原型的页面、演示案例和运行方式。

脚本和原型用仓库内的相对路径读取项目文件。数据接口见[数据说明](../data/README.md)。

## 客流探索分析（Issue #10）

在仓库根目录用 Python 3.10+ 运行。环境已有相应依赖时，可直接执行第二行。

```powershell
python -m pip install pandas==2.3.3 matplotlib==3.10.6
python code/explore_traffic.py
```

脚本从 `data/traffic_calendar.csv` 读取客流和日历字段，并读取用于极值核对的官方快照。生成五张 CSV、三幅 300 DPI PNG 图和一份复现清单。输出位于 [docs/探索分析/图表/](../docs/探索分析/图表/)。可用 `python code/explore_traffic.py --output-dir tmp/issue-10-eda-check` 在另一个目录重跑。

CSV 人次以原始单位计，`sd_passengers` 为样本标准差，四分位数用线性插值，浮点统计量保留两位小数。图内采用 Matplotlib 自带字体和英文标注，中文图注说明坐标、日期组和样本数。读表和图的顺序见[客流探索分析](../docs/探索分析/客流探索分析.md)。

`python code/explore_weather_traffic.py` 读取 `data/weather_daily.csv`，离线重跑天气关联试验。`python code/build_weather_eda_inputs.py` 从原始缓存重建逐日天气表和来源清单，默认写入 `data/`。该步骤需要 `lxml` 及上述分析环境，按需使用 `--download` 下载缺少的缓存。 [天气来源与复算说明](../docs/探索分析/天气关联/天气与客流.md)

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

假期表可用 `python code/build_holidays.py --check` 单独检查。

## 分析主表（Issue #3、#10）

`merge_traffic_calendar.py` 读取 `data/passenger_daily.csv`、`data/holidays.csv` 和 `data/weather_daily.csv`，按目标日 `date` 做多对一左连接。输出 `data/traffic_calendar.csv` 和 `data/traffic_calendar_audit.json`。主表包含客流 7 列、日历 9 列及 `forecast_psr`、`tc_signal_at_cutoff` 两列天气特征。以下命令只需 Python 3.10+ 标准库，可离线运行。

```bash
# 先核对客流与日历输入
python code/clean_passenger.py --check
python code/build_holidays.py --check

# 重建分析表与核验结果
python code/merge_traffic_calendar.py

# 只校验现有交付；不写文件，内容不一致时退出码为 1
python code/merge_traffic_calendar.py --check

# 客流清洗及合表测试
python -m unittest discover -s code -p "test_*.py" -v
```

合表前检查客流主键、人次及加总、日历标记和三张输入表的日期覆盖。天气检查包含台风信号编号、降雨概率等级，以及预报发布和归档时间是否满足 D−1 日香港时间 18:00 截止规则。日历与天气各需每天一行，缺失日期、重复及非法值会报错。2024-12-20 的天气行保留预报空值，仍可正常按日连接。

合表后检查行数、主键和三类字段逐条匹配，按日期、口岸、方向排序，输出 UTF-8 无 BOM、LF 换行的 CSV。核验 JSON 记录行数、天气缺失日期、等级与信号分布、输入及输出的 SHA-256。各输入先解析并按键排序，再用 UTF-8/LF CSV 计算内容校验值。

`--check` 从三张本地输入表重算并逐字节比对当前主表和核验 JSON。历次复核及当前建模交接见[分析表独立复核与建模交接](../docs/数据核验/分析表独立复核与建模交接.md)。
