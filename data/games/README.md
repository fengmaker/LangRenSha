# 正式对局档案

本目录按赛季保存逐局结构化档案，是发布与数据库入库所使用的正式源文件。

S21当前为按已核身份和流程生成的122条媒体档案，先供网站展示；正式计分总局数尚未确认，未决阵营、胜方和流程缺口继续保留未知，悍跳待用户后续复核。

- 每局 `dossier.json` 保存赛季、对局、座位、身份、事件和来源等结构化字段。
- `voting.json`、`voting_review.json` 等 JSON 侧件保存票型及独立复核结果。
- CSV 便于逐行检查；HTML、Markdown 是阅读或复核呈现，不能替代对应 JSON 源记录。
- 文件中的用户判断、来源引用和未知状态都属于证据链；不要从页面展示结果反写或覆盖原件。
- 日常入口为 [scripts/workflow.py](../../scripts/workflow.py)：`status --season S22`，再用 `plan` / `run --stage review|import|publish`。
- 赛季注册与固定范围、规则快照路径见 [config/seasons.json](../../config/seasons.json) 及 `config/S22_*`、`config/S23_*`；不要搬移这些快照。
- 原始媒体在 [raw](../raw/README.md)，逐局提取在 [extractions](../extractions/README.md)，验收结果在 [reports](../reports/README.md)。
