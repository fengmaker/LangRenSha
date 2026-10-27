# 历史复核记录

本目录保留早期试点复核产生的 JSON 记录，作为数据库证据引用的历史材料。

- `*.review.json` 保存旧试点中的复核状态、意见或字段记录；它不等同于当前赛季复核快照。
- 已被数据库证据引用的内容保持只读，不覆盖、不删除，也不当作普通缓存。
- 旧 review pipeline 已退出当前流程；不要重跑旧脚本来改写这些记录。
- 历史“通过/待查”状态只说明当时试点记录，不构成当前新任务的批准。
- 当前复核阶段由 [scripts/workflow.py](../../scripts/workflow.py) 按 [config/seasons.json](../../config/seasons.json) 中的赛季 profile 规划。
- 当前正式源记录见 [games](../games/README.md)，审计报告见 [reports](../reports/README.md)。
