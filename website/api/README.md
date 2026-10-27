# 只读API与发布

运行时：`uvicorn website.api.app:app --host 127.0.0.1 --port 8000`。本机优先用`website/run.py`同时管理前端；部署配置`DATABASE_URL`并使用只读账号。

| 文件 | 职责 |
| --- | --- |
| `app.py` | 参数校验、分页与范围查询；赛季名称／状态读取统一`config/seasons.json` |
| `publisher.py`、`publish.py` | 从磁盘正式JSON构建不可变game release，白名单公开字段，事务切活动指针 |
| `analytics.py` | 有效阵营、胜率、投票指标、排名与积分；不改源快照 |
| `game_presentation.py` | 在保留原事件的基础上整理展示日序、夜间结算和终局边界 |
| `bluffs.py`、`bluff_store.py`、`publish_bluffs.py` | 悍跳定义、逐季独立版本及绑定game release的发布 |
| `photos.py`、`player_photos.json` | 同季照片清单与允许访问的静态原图，清单缓存需API重启刷新 |
| `bluff_frames.py`、`bluff_frames.json` | 悍跳证据截图的清单与静态访问 |
| `schema.sql` | 独立`masters_web`发布schema，不运行JCMS业务迁移 |

常用GET：`/overview`、`/games`、`/games/{id}`、`/players`、`/players/{id}`、`/leaderboard`、`/stats`、`/bluff-review`、`/releases`，统一前缀`/api/v1`。

选手详情与stats支持`season_start/season_end=latest`；旧`season=S22`保持单季兼容。榜单仍按季，`phase=all|finals_week`只改变积分榜范围，其他个人指标按整季。未知阵营／胜负不当成负场，零有效样本比例为null。

发布与回退使用[网站README](../README.md)或`workflow.py`，不要用早期`database.py publish`。一个活动game release代表完整数据集，悍跳按每个保留季分别同步。
