# 合并前的配置快照

这是2026-10-29整理 `config` 前工作区文件的原始字节备份，包含当时尚未提交的修改。仅用于历史路径和 SHA256 追溯，不作为运行配置读取。

| 原入口 | 当前入口 |
| --- | --- |
| `config/S21_formal_rules.json`、`S22_formal_rules.json`、`S23_formal_rules.json` | `config/game_rules.json` 的共同规则及来源记录；局数、轮换、导入设置在 `config/seasons.json` 的 `formal_import` |
| `config/S21_game_scope.json`、`S22_game_scope.json`、`S23_game_scope.json` | `config/seasons.json` 中对应赛季的 `scope` |
| `config/S23_review_rules.json` | `config/game_rules.json` 的 `review_rules`，案例状态、场次及证据保留 |
| `config/scoring_rules.user_reported.v1.json` | `config/game_rules.json` 的 `scoring`，保留原规则标识及用户报告来源 |
| `config/board_templates/s21_*.json`、`s23_*.json` | 每版型一份无赛季前缀模板，原存储代码通过 `storage_variants` 兼容；精确路径见清单 |
| `config/S22_standard_sample.json`、`S22-pilot-board.candidate.json` | 本目录中的原文件；历史样本与未采用候选不再放入运行配置 |

[manifest.json](manifest.json)逐项记录原路径、快照路径、原 SHA256 和当前入口。旧收据仍按其记录的原版本解释，不替换原哈希，也不把旧来源标记为新规则。

合并不改变已确认规则、案例裁定或对局事实。保存的 `rule_derivations.json` 只有在重新计算结果完全一致时才迁移配置依赖指纹；数据库收据与已发布版本保持原样。
