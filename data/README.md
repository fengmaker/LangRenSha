# 数据目录：按职责找资料

从[工作流手册](../docs/15_赛季数据全流程操作手册.md)或`python scripts/workflow.py status --season S23`进入。只读取当前阶段需要的区块。

| 目录 | 存什么／日常用途 |
| --- | --- |
| [raw](raw/README.md) | 官方音频、视频／字幕接口原件、微博正文／长文／原图、规则卡；来源入口 |
| [indexes](indexes/README.md) | 官方目录、冻结采集计划及缺集核查；决定拿什么资料 |
| [seasons](seasons/README.md) | 按季／日期命名的音轨硬链接、字幕阅读稿和媒体目录；人读的入口 |
| [transcripts](transcripts/README.md) | 平台文字规范化、本地全文、SRT、配置与ASR原始分块；转写与续跑 |
| [extractions](extractions/README.md) | 按季提取的身份／票型／日夜候选、画面、推断、用户意见和证据定位 |
| [games](games/README.md) | 按季的正式dossier/voting/endgame及必要补充、候选与导入回执；网站发布输入 |
| [reports](reports/README.md) | 阶段进度、验收、交付和本次维护记录；直接记录做到哪一步 |
| [exports](exports/README.md) | 当前可浏览／分享的离线复核页、目录CSV和交付包；从保留源数据生成 |
| [archive](archive/README.md) | 数据库内容寻址快照、被引用的旧版本和更正前资料；按哈希追溯，不当普通缓存 |
| [weibo](weibo/README.md) | 官方帖子阅读目录、排班、人名／照片映射与确认记录 |
| [backups](backups/README.md) | 数据库dump和对应回执，不进普通Git历史 |
| [diagnostics](diagnostics/README.md) | 限制、缺源、字幕可见性的诊断原件；不是赛事事实 |
| [candidates](candidates/README.md)、[reviews](reviews/README.md) | 早期已登记候选／反馈；历史只读，不用于当前正式入口 |

当前资料：[S22媒体](seasons/S22/README.md)、[S23媒体](seasons/S23/README.md)；正式范围148+75=223局。媒体条目163+87包含范围外内容，不能混用计数。

## 文件层次

原始JSON按原字节保存；`.srt`与`.阅读.txt`是同一字幕的派生格式，不是独立证据。`dossier.candidate.json`与正式`dossier.json`分别保留；原文、推断、用户确认的区别不因入库而消失。详情见[字段规范](../docs/16_字段证据与交叉复核规范.md)。

`data/seasons/`与`data/raw/`的音频常为硬链接，逻辑目录大小相加会重复计数。不要编辑媒体、随意重排已登记路径或改JSON换行来“美化”，这会破坏来源SHA和回执。

## 清理与恢复

`python scripts/cleanup_data.py`只预览；确认后才用`--apply`。它保护所有注册季的当前字幕／导出、DBartifact和业务证据路径／哈希，只清无引用快照及废弃副本。早期不等于无用；当前生成器依赖的baseline/reviewed/daily_audit、ASR raw/chunk和原始规则仍保留。

`python scripts/backup_database.py`记录全部已保留季基线并整库备份。数据库引用的文件仍要单独备份；单有Git或dump不能恢复被删除的媒体原件。本轮删除清单及正式JSON保护校验在`reports/maintenance/2026-10-27/`。
