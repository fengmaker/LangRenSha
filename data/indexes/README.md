# 采集索引与计划

本目录保存平台候选目录、采集计划、索引摘要和缺口核验表。

- `.csv` 汇总视频候选、BVID、标题、发布时间或采集状态，适合人工排序和抽查。
- `.json` 保存任务计划、索引摘要、缺口核验及其他结构化状态。
- 索引是发现来源和跟踪覆盖率的工具，不是正式对局范围或事实档案。
- 正式范围和规则仍使用 `config/S22_game_scope.json`、`config/S23_game_scope.json` 与各自的规则快照，路径保持不变。
- 当前入口是 [scripts/workflow.py](../../scripts/workflow.py)：`status` 查看进度，`plan --stage collect` 预览采集阶段。
- 采集原件在 [raw](../raw/README.md)，正式对局记录在 [games](../games/README.md)。
