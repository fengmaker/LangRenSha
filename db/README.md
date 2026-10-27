# PostgreSQL schema migrations

本目录保存数据库结构变更的有序 SQL 迁移。

- `NNN_description.sql` 按编号递增；应用器记录迁移文件名和 SHA-256，检测已应用文件是否被改写。
- 已应用迁移应保持不变；新结构变更追加新编号迁移，不回写旧文件。
- 当前迁移入口是 `python scripts/database.py migrate`；执行前确认目标数据库连接配置正确。
- 赛季采集、转写、复核、导入和发布使用 [scripts/workflow.py](../scripts/workflow.py) 与 [scripts/season_config.py](../scripts/season_config.py) 的注册配置。
- `workflow.py plan --season S22 --stage import` 先预览导入命令；正式写入前流程会调用 [scripts/backup_database.py](../scripts/backup_database.py)。
- Python 依赖清单及环境分组见 [requirements/README.md](../requirements/README.md)。
- 数据库转储在 [data/backups](../data/backups/README.md)，DBartifact 哈希快照在 [data/archive](../data/archive/README.md)。
