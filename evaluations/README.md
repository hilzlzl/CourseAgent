# 实验记录

当前展示以[课程作业生成与交付评估](../docs/evaluation.md)为主，实验规模为 20 个需求各 3 次、共 876 题次。主报告中的通用 AI 与人工结果、更新后的重合率和 Agent 评分由作者补充；本目录保留历史脱敏记录，尚未归档这些新增结果对应的逐次记录与评分标注。

| 目录 | 内容 | 与主报告的关系 |
| --- | --- | --- |
| [extended-benchmark](#扩展实验文件) | 历史 12×3 加新增 8×3；67 次实际尝试和 60 个替换后槽位 | 主表 CourseAgent 完成率、耗时与模型用量的来源 |
| [通用 AI 直接生成](direct-api-baseline/protocol.json) | 朴素 AI 基线，3 个需求各 1 次，52,382 token | 历史预实验，不对应主表新增的 60 次结果 |
| [api-pilot](api-pilot/protocol.json) | 同三需求的 CourseAgent 工作流，197 次逻辑调用、582,042 token | 历史同配额的 CourseAgent 工作流预实验 |
| [final-acceptance](final-acceptance/metrics.json) | 历史 12 个需求 × 3 次 | 已作为主实验的历史 36 次纳入，不重复相加 |
| [server-benchmark](server-benchmark/README.md) | 作者提供的 960 题三组服务器汇总 | 独立历史批次，未并入当前 876 题结果 |
| [content-review.json](content-review.json) | 历史助手内容评价 | 不用于复算主表更新后的 Agent 评分 |

## 数值复算

以下命令从仓库根目录执行，只使用标准库，不调用模型：

```bash
python scripts/summarize_extended_benchmark.py
python scripts/summarize_benchmark.py
python scripts/summarize_api_pilot.py
python scripts/summarize_direct_api_comparison.py
python scripts/summarize_server_benchmark.py
```

原始题目、课件、程序、隐藏测试、缓存、模型完整响应和数据库保留在本地。哈希与脱敏数值标识已保存的快照，不构成独立的内容正确性认证。

## 扩展实验文件

历史 36 次首次记录与新增 24 次首次记录形成 60 个需求轮次。新增首次未完整的 7 套各重跑一次，在派生结果中全部选用重跑结果；首次记录保持原样。实际发生 67 次尝试。

| 文件 | 内容 |
| --- | --- |
| [cases.json](extended-benchmark/cases.json) | 20 个需求的题型、数量、考查范围和脱敏复现提示 |
| [runs.json](extended-benchmark/runs.json) | 60 次首次尝试的数值记录，包含未完整任务 |
| [retries.json](extended-benchmark/retries.json) | 7 次重跑及对应首次运行 ID |
| [summary.json](extended-benchmark/summary.json) | 首次、替换后、重跑与实际累计用量，含替换映射 |
| [repeat-pairs.json](extended-benchmark/repeat-pairs.json) | 同需求完整轮次的匹配数与分母，无题面或题目身份 |
| [protocol.json](extended-benchmark/protocol.json) | 样本范围、模型请求设置、计时、缓存、历史与替换规则 |
| [provenance.json](extended-benchmark/provenance.json) | 私有数值源摘要、历史源码哈希及发布文件差异 |

`summarize_extended_benchmark.py` 检查覆盖样本唯一性、题型题量、七个重跑目标及替换映射、成功状态、用例分类、usage 覆盖、百分位、重复率宏平均和包含废弃尝试的实际用量。替换后为 55/60 套完整、852/876 题；累计为 4,749 次调用、11,612,024 已报告 token。

主表 CourseAgent 的调用与 token 数按选定的 60 次结果统计，不包含被替换尝试的开销；耗时为其中 54 次限时内无人工干预的完整任务截至本地导出的时间，不含平台保存与回读。

需求中的草稿表述已明确为本地生成，私有课件名统一为“教师自备课件.pdf”；它们是脱敏复现描述，不是原始请求字节快照。C 类需求依赖自备课件，仓库不分发原课件。

重复配对的身份匹配依据保留在私有题目索引中，公开匹配数仅供重算统计。源码哈希描述历史版本，发布代码并非冻结版本的逐字副本；现有依赖锁也不代表历史实验环境锁。数值检查通过不代表已独立复现在线实验或完成内容验收。
