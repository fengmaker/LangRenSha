# 配置

规则按用途和版型集中维护，不按赛季复制。基础身份、同版型能力和基础计分默认共用；明确的改版只覆盖受影响字段，单局裁定保留场次及证据。

| 文件／目录 | 职责 |
| --- | --- |
| [game_rules.json](game_rules.json) | 共同规则入口：字段定义、基础身份与投票、各版型能力、规则来源与未决项、带状态和作用域的案例、计分与赛制 |
| [seasons.json](seasons.json) | 赛季来源与运行入口；`scope` 保存正式范围、排除项和快照，`formal_import` 保存局数、轮换、存储代码映射及导入设置 |
| [board_templates](board_templates/README.md) | 每个版型一份身份及事件槽模板；已有存储代码的归档差异集中保存，不另建赛季规则文件 |
| `asr_hotwords.txt` | 全文Paraformer热词 |
| `asr_recap_hotwords.txt` | 复盘专项热词，显式选择，替换默认词表 |
| `asr_review_hotwords.txt` | Nano片段复核的精简热词，不超过50个 |

程序通过 `scripts/rule_config.py` 读取规则、范围与导入配置，通过 `scripts/board_config.py` 读取模板。日常执行入口为 `python scripts/workflow.py`。新增季复用共同规则，只登记来源、实际范围、必要的适配与有证据的差异。

`review_rules.rules` 的 `status`、`scope` 和证据决定能否采用；观察案例不因移入共同文件就变成通用结论。`scoring` 保留用户报告来源与 `official_verified: false`，未确认计分项继续留空。

整理前的原文件、样本和早期候选已逐字节保存在[历史配置快照](../data/extractions/shared/config_history/2026-10-29/README.md)，供旧收据中的路径与 SHA256 追溯；它们不再作为运行配置读取。保存的推导文件只在计算结果完全相同时迁移规则依赖指纹，不改对局事实、数据库收据或已发布版本。
