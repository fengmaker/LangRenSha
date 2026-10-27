# 原始采集材料

这里保存平台返回的原始媒体、接口响应和补充来源，按 `bilibili/`、`weibo/`、`rules/` 等来源分区。

- `.json` / `.jsonl` 保存原始响应、清单或任务记录；音频、字幕和图片保留采集到的文件格式。
- `manifest.json` 与同目录记录描述媒体分段、来源标识和校验信息。
- 这些文件是后续抽帧、转写和正式入库的来源原件；不要当作可重建缓存清理或覆盖。
- 采集前查看 [data 目录说明](../README.md) 与赛季注册表 [config/seasons.json](../../config/seasons.json)。
- 当前采集流程入口是 [scripts/workflow.py](../../scripts/workflow.py)：先 `status`，再用 `plan --stage collect` 预览。
- 执行采集使用 `run --stage collect`；认证方式由任务需要决定，原件应保留在来源目录。
- 候选索引和采集计划放在 [indexes](../indexes/README.md)，提取文件放在 [extractions](../extractions/README.md)。
