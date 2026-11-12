# 大师赛档案网站

从 `data/games/*/*/game.json` 直接加载最终对局，使用 `api/analytics.py` 等共用纯计算模块生成选手统计、榜单、对局档案和静态 JSON。`api` 目录保留的是计算与照片/人物工具，没有动态 API、数据库发布版本或反馈存储。

```powershell
.\.venv\Scripts\python.exe website/run.py
```

本地预览在 <http://127.0.0.1:3000>；启动器准备本地静态数据后运行 Next.js。无需启动 PostgreSQL，也无需 API 账号。Python 依赖见 [requirements](../requirements/README.md)，前端依赖在 `web` 执行 `npm ci`。

只读验证与本地数据导出：

```powershell
.\.venv\Scripts\python.exe website/static_publish/export_static.py --check
.\.venv\Scripts\python.exe website/static_publish/export_static.py
.\.venv\Scripts\python.exe -m pytest website/tests -q
```

网站只消费最终数据，不重算历史推导，不读取旧转写或历史人工反馈。悍跳保留最终次数、成功率及未知状态；公开证据截图、公开复核和反馈页面已退役。日夜、票型与特殊角色共用[呈现规范](../docs/07_对局信息呈现规范.md)。

`assets/people.json` 保存稳定人物 ID，`api/player_photos.json` 和 `assets/player-photos` 是正式照片基线。`prepare_photos.py --season S23` 仅按该季最终姓名补已核的新选手照片，已有绑定不重读历史微博原件。

本地修改和验证默认不生成或同步线上成品。明确要求上线时使用 [static_publish](static_publish/README.md)。
