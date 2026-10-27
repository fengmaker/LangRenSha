# 数据库备份

本目录保存 PostgreSQL 整库备份及其校验收据。

- 历史 `.dump` 文件是 PostgreSQL custom-format 备份，不能当作生成物缓存删除。
- 新工作流备份通常写入独立时间戳目录，包含 `database.dump` 和 `receipt.json`。
- `receipt.json` 记录 SHA-256、大小、活动发布版本、赛季源文件基线及归档目录校验状态。
- 备份不会自动完成还原验证；保留 dump 与收据配对，删除前先确认另有可恢复副本。
- 当前备份入口是 [scripts/backup_database.py](../../scripts/backup_database.py)；赛季导入阶段也会由 [scripts/workflow.py](../../scripts/workflow.py) 调用备份。
- DBartifact 内容快照单独存放在 [archive](../archive/README.md)。
