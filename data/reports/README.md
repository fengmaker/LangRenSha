# 进度、复核与验收报告

先按用途进入子目录，根目录只保留本索引。报告记录当时状态；事实确认以对应逐局证据和批准记录为准。

| 目录 | 内容与入口 |
| --- | --- |
| [S21](S21/README.md) | S21采集、转写、身份与日夜复核、发布验收 |
| [S22](S22/README.md) | S22批处理、票型、因果复核和规则对齐 |
| [S23](S23/README.md) | S23逐局/逐日复核、悍跳确认和入库验收 |
| [shared](shared/README.md) | 跨季通用规则推导与验收 |
| [acquisition](acquisition/README.md) | 单视频采集收据、微博原件与排班采集验收 |
| [maintenance](maintenance/README.md) | 目录整理、数据库维护与历史操作记录 |
| [baselines](baselines/) | 历史文件路径与清理基线 |

常用入口：[通用规则前移验收](shared/S21_S22_S23_通用规则前移验收_20261029.md)、[S21日夜投票复核](S21/S21_日夜投票逐局复核_20261029.md)、[S22投票逐局核对](S22/S22_投票逐局核对.json)、[S23悍跳人工确认](S23/S23_悍跳人工复核应用_20261029.md)。

## 放置约定

- 季报告写入`data/reports/{season}/`，保留原文件名；逐视频转写日志放在该季的`logs/全文补转写/`。锁文件仍由原工具管理。
- 跨季推导写入`shared/`；采集收据写入`acquisition/`；清理和维护收据写入`maintenance/`。
- CSV、HTML等供打开或分享的展示产物放在[data/exports](../exports/README.md)。报告中的JSON详情和Markdown摘要用途不同，均保留；只有内容相同的别名副本才去重。
- 历史JSON、批准记录和审计证据保持原字节。它们保存的旧报告路径可在[本次迁移清单](maintenance/2026-10-29_报告目录整理.json)查到新位置；其中旧配置SHA仍表示当时的配置，不冒充最新验收。

当前任务状态可用`python scripts/workflow.py status --season S21`查询。正式逐局记录见[games](../games/README.md)，原始证据见[extractions](../extractions/README.md)。
