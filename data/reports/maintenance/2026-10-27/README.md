# 2026-10-27 工作流整理记录

- 删除 733 个无用实现、无引用资料和临时／缓存文件，合计 57,315,954 字节（约 54.7 MiB）。
- 正式范围仍为S22 148局、S23 75局；活动发布ID与源／规则摘要保持。
- 1300 份既有正式JSON／规则哈希全部不变；1682 条DBartifact对应文件全部存在。
- Python回归601项通过；统一入口验收223局逐局匹配，浏览器36页／1440和390宽通过。
- 2754 个当前文档相对链接检查通过；历史data/archive快照内容未为改路径而重写。

## 记录用途

| 文件 | 用途 |
| --- | --- |
| [summary.json](summary.json) | 本次最终清理与验证汇总 |
| [obsolete_files.json](obsolete_files.json) | 被替代或无用的实现及删除原因 |
| [data_cleanup.json](data_cleanup.json) | 全季引用保护后的数据删除清单与SHA |
| [scratch_cleanup.json](scratch_cleanup.json) | 无引用临时产物、字节码和测试缓存清单 |
| [baseline.json](baseline.json) | 清理前正式文件保护哈希和原工作区状态，不是后续执行入口 |

整库备份回执位于`data/backups/reorganization-20261027/receipt.json`，网站实际验收报告位于`website/artifacts/publication-acceptance.json`。
日常从[全流程手册](../../../../docs/01_赛季数据全流程.md)开始，不需要读取本目录。
