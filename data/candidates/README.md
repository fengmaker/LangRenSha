# 历史候选记录

本目录保留早期流程产生的候选 JSON，供追溯历史导入和数据库证据引用。

- `*.candidate.json` 是试验/过渡阶段的结构化候选，不是当前正式 `dossier.json`。
- 这些文件已被数据库证据或历史记录引用，按只读历史材料保留，不要覆盖或删除。
- 不要执行旧 candidate 导入管线，也不要将候选文件直接当作当前事实来源。
- 如需继续处理，先从当前赛季注册配置和原始来源重新进入正式流程。
- 当前赛季任务统一从 [scripts/workflow.py](../../scripts/workflow.py) 的注册阶段计划开始。
- 正式逐局档案见 [games](../games/README.md)，阶段审计材料见 [reports](../reports/README.md)。
