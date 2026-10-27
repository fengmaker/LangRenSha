# 按赛季整理的采集材料

本目录存放按赛季、周次或节目期组织的媒体与阶段性目录文件。

- 子目录保留赛季内的周次/节目分组；CSV 目录汇总音频、字幕或补转写任务状态。
- 目录文件用于导航和覆盖核对，不替代原始媒体、逐局正式档案或规则判断。
- 原始文件与采集回执在 [raw](../raw/README.md)，正式逐局档案在 [games](../games/README.md)。
- 注册赛季以 [config/seasons.json](../../config/seasons.json) 为准，由 `scripts/season_config.py` 读取。
- 正式范围快照仍在 [config/S22_game_scope.json](../../config/S22_game_scope.json)、[config/S23_game_scope.json](../../config/S23_game_scope.json)。
- 正式规则快照仍在 [config/S22_formal_rules.json](../../config/S22_formal_rules.json)、[config/S23_formal_rules.json](../../config/S23_formal_rules.json)；不要移动或重生成它们。
- 日常进度和各阶段计划使用 [scripts/workflow.py](../../scripts/workflow.py) 的 `status`、`plan` 和 `run`。
