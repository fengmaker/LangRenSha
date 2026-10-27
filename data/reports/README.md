# 进度、审计与验收报告

本目录保存统一工作流、采集、转写、逐局复核和数据库操作产生的进度与验收材料。

- `.json` / `.jsonl` 是机器可读状态、汇总、校验结果或操作收据；`.csv` 是表格化清单。
- `.md` / `.html` 是面向人工的报告和复核页面；`.log` / `.txt` 保留执行过程或诊断信息。
- `S22_*`、`S23_*` 及子目录通常按赛季或任务阶段组织；报告记录状态，不自动等于事实确认。
- 复核结论、验收收据和被其他材料引用的报告属于审计证据，不能按可重建缓存删除。
- 当前进度从 [scripts/workflow.py](../../scripts/workflow.py) 的 `status --season S22` 查询；`plan` 只预览阶段命令。
- 正式逐局源记录在 [games](../games/README.md)，可回溯的来源和画面证据在 [raw](../raw/README.md) 与 [extractions](../extractions/README.md)。
