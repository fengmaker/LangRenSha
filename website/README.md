# 大师赛档案网站

Next.js + TypeScript 前端、FastAPI 查询 API、PostgreSQL 发布库。现有 S22 档案保持原样；网站从固定发布批次读取数据。

2026-10-25 本机验收：已发布148局、47个比赛日、62位参赛选手、347轮投票和2513条选票。24项后端回归测试、Next.js生产构建、全部148局API读取、桌面与360/390/768像素布局、筛选/分页/404以及独立数据库备份恢复均通过。1066个既有档案、规则和迁移文件的哈希保持不变。62名选手的胜率、站边/警徽指标和两榜积分均已与原始逐局记录独立核对；8条混血儿空阵营均按明确榜样补算，现无待定积分。浏览器验收报告与截图在 `website/artifacts/`。

## 本机启动

在项目根目录 `D:\langrensha` 执行：

```powershell
.\.venv\Scripts\python.exe scripts/local_postgres.py start
.\.venv\Scripts\python.exe -m pip install -r website/requirements.txt
.\.venv\Scripts\python.exe -m website.api.publish --season S22 --check
.\.venv\Scripts\python.exe -m website.api.publish --season S22
.\.venv\Scripts\python.exe -m website.api.publish_bluffs --season S22 --check
.\.venv\Scripts\python.exe -m website.api.publish_bluffs --season S22
.\.venv\Scripts\python.exe website/run.py
```

打开 <http://127.0.0.1:3000>。Ctrl+C 同时停止前端和 API；PostgreSQL 仍由原项目命令管理。

首次安装前端依赖需要 Node.js 24 LTS，在 `website/web` 执行 `npm ci`。本次工作区已有便携 Node，`run.py` 会自动查找 `.tools/node/`。Node 不在 PATH 时，可以先把实际安装目录加入当前终端 PATH。

生产构建：在 `website/web` 执行 `npm run build`，然后回到项目根目录执行：

```powershell
.\.venv\Scripts\python.exe website/run.py --production
```

端口冲突时使用 `--port 3001 --api-port 8001`。API 默认只监听本机，文档地址为 <http://127.0.0.1:8000/docs>。

## 发布与回退

```powershell
# 第一阶段样例；会把网站切换为只有该局的发布版本
.\.venv\Scripts\python.exe -m website.api.publish --sample BV1yt7v6QE3Q

# 预检不写数据库；--list 列出本地正式范围中的对局
.\.venv\Scripts\python.exe -m website.api.publish --season S22 --check
.\.venv\Scripts\python.exe -m website.api.publish --season S22 --list

# 发布完整S22，事务内写入快照并切换公开版本
.\.venv\Scripts\python.exe -m website.api.publish --season S22

# 查询发布历史：GET http://127.0.0.1:8000/api/v1/releases
# 使用返回的真实批次ID回退，不要把占位符原样执行
.\.venv\Scripts\python.exe -m website.api.publish --activate <release-id>
```

发布使用独立 `masters_web` schema。每个批次保存公开单局快照、选手索引及来源/规则摘要。发布失败时，新批次与公开指针一起回滚；重复发布相同内容不会新增重复对局。更改持久化快照时更新发布器的格式/统计版本；查询时计算的选手指标另有 `analytics_version`，无需重写既有批次。

当前一个公开批次是一次完整数据集，命令中的 `--season` 选择其来源赛季。未来多赛季上线需要先扩展为包含全部收录赛季的批次，不能直接用仅含新赛季的批次替换既有全站数据。

悍跳复核结果单独发布到同一个 `masters_web` 数据库，并绑定当前对局批次。`python -m website.api.publish_bluffs --season S22 --check` 预检完整赛季的身份和结果指纹；去掉 `--check` 原子保存逐局结论并切换复核版本，重复同步相同内容不会重复计数。积分榜、选手详情和复核页统一从数据库读取，旁证 JSON 仅作为同步输入和离线导出。重新发布对局批次后，也应同步对应复核数据；未同步的版本保留未知状态。

## 数据与页面边界

- 首页、赛季、对局检索、单局详情、选手列表/档案、积分榜、统计与说明均读取已发布批次。
- 正式范围来自 `config/S22_game_scope.json`，不以媒体文件数量计对局数。
- 选手页包括出场率、总胜场/负场、总胜率、狼人/好人胜率、上警率、站边率、警徽票准确率、各身份胜率与逐局积分。每项比例展示分子、分母及缺失样本数量。
- 所有个人指标统一按整季统计，包含决赛周，不随阶段切换。出场率为全季出场局数 / 全季正式局数。上警率以每局首次报名为准，延期竞选不重复计数。
- 站边率按每轮放逐票计算：好人阵营非预言家、非通灵师玩家与真实预言家或通灵师均有票权，且后者明确投向某人；投同一目标成功，弃票失败，缺失票不算失败。
- 警徽票准确率按好人有票权且真实预言家或通灵师为合法候选的轮次统计，包含 PK 和技能复投；候选名单缺失时仅接受同轮确有投向该人的选票作为资格证据。
- `/leaderboard?phase=all` 累计整季积分（包含决赛周）；`phase=finals_week` 只累计决赛周积分作为冠军榜。两榜其余个人指标均为整季数值。狼人胜 +1.5，好人胜 +1，输 -1；同分并列。采用本项目约定规则，不附加官方加分或同分裁定规则。
- 积分榜参考 BV1fGRcBvEAD 扩展字段。列名使用“积分”，删除“整季胜 / 负”组合列；百分比单元格只显示百分比，零有效样本显示“—”。悍跳两项依据转写/复盘推断：狼人跳预言家或通灵师计一次，竞选拿徽或首日最终放逐好人即成功。推断及疑问在 `/leaderboard/bluff-review` 回查，原始对局档案不改写，三项技能正确率继续留空。字段与口径见 `积分榜字段说明.txt`。
- 悍跳复核重点检查首日的警上、PK与警下发言，延期竞选单独标注。在线复核页和 `data/exports/S22_悍跳推断与复核.html` 均可填写结论、天数、所跳身份及其他意见，自动保存浏览器草稿，支持导入/导出反馈JSON；离线页还可下载包含填写内容的HTML备份。未填写不代表确认，导出文件交给维护者后才更新统计。`scripts/import_bluff_feedback.py <文件>` 默认只预检，加 `--apply` 保存独立用户旁证，再由 `scripts/build_bluff_inference.py` 验证和构建发布资产；源底牌及投票档案始终分开保存。
- 复核应用后的同步顺序为：导入反馈 → `scripts/build_bluff_inference.py` → `python -m website.api.publish_bluffs --season S22`。网页读取数据库，不会因旁证文件更新或进程缓存而绕过已发布版本。
- 混血儿阵营与榜样阵营一致：阵营字段缺失时读取明确的选择榜样事件推导。当前 S22 的8条缺失均可确定。未能确定的结果保留待定，不能当作败场或零分；原文弃票和规则默认弃票分别标记。
- 照片按赛季和已人工确认的姓名匹配，S22 的62名选手均有同季正赛/决赛周原图。`python website/prepare_photos.py` 从既有微博映射生成静态资产与来源清单，不修改图片。API 仅提供清单列出的文件，前端经同源 `/media/player-photos/…` 访问。
- 日夜事件的槽位排列不承诺操作的精确先后；技能原目标、结算结果和实际出局者分开展示。
- 对局档案以大字号呈现版型、日期、解说、裁判和录像；座位分狼人、神职、平民三列，狼混归狼人列、好人混归平民列，榜样与底牌分别保留。日夜事件和对应白天票型按轮次纵向展开。
- 原始日夜事件保留在数据库快照和详情API的 `rounds` 中；`presentation` 是独立展示结果，省略已耗尽药剂、已出局角色的空操作和重复占位。猎人资格结合实际中毒、死亡及傀儡规则判断，有依据的推断逐条注明。药剂同夜只能使用一瓶，使用解药不会耗尽尚未用过的毒药。
- 目前没有公网写入或用户登录接口；维护者通过命令行预检、发布与回退。
- API 不导出本地文件路径、完整转写或凭据。查询使用只读事务。生产部署另配数据库只读账号。
- 发布副本通过源档案生成，不读取早期试验性的 `published_games` / `player_basic_stats` 视图。

## 测试与备份

```powershell
.\.venv\Scripts\python.exe -m pip install -r website/tests/requirements.txt
.\.venv\Scripts\python.exe -m pytest website/tests -q
.\.venv\Scripts\python.exe -m website.backup --verify-restore
# 网站启动后，使用本机 Chrome 检查完整 S22 与多种屏幕宽度
.\.venv\Scripts\python.exe website/check_site.py
.\.venv\Scripts\python.exe website/check_players.py
```

备份命令仅备份网站 schema，不涉及 S22 源库。`--verify-restore` 在新建的随机临时数据库中恢复，比较所有发布表的内容摘要后删除该临时库；需要本地数据库账号具备创建数据库权限。备份保存在 `website/artifacts/`，应另复制到独立存储。原始档案及旁证仍需要沿用项目自身的备份策略。

## 独立部署

`compose.yaml` 与两份 Dockerfile 为独立 Linux 部署配置。当前开发机未安装 Docker，容器部署仍需在目标主机验证。

1. 将 `website/.env.example` 复制为 `website/.env`；分别生成两段不同的随机十六进制密码（至少32字符），替换两项占位值。数据库URL内使用十六进制可避免特殊字符转义问题。
2. 在 `website` 目录执行以下命令：

```sh
docker compose up -d db
docker compose --profile tools run --build --rm publish --season S22 --check
docker compose --profile tools run --build --rm publish --season S22
docker compose --profile tools run --build --rm --entrypoint python publish -m website.api.publish_bluffs --season S22
docker compose --profile tools run --build --rm reader-setup
docker compose up --build -d api web
```

容器中的发布器使用管理员连接；查询API使用只授予 `masters_web` 读取权限的独立账号。原始数据目录只读挂载给发布任务，前台和API容器不挂载原始资料。公网入口需在目标主机接入反向代理与 HTTPS；Compose 默认仅把网站端口映射到宿主机 `127.0.0.1:3000`。

首次容器发布若没有原 `jcms.people` 表，会采用确定性的公开人物UUID。迁移已经上线的站点时，应恢复 `masters_web` 发布库以保留既有链接，不能把重新从源档案发布当作数据库迁移。

## 代码位置

| 目录 | 职责 |
| --- | --- |
| `api/publisher.py`、`api/publish.py` | 白名单转换、来源摘要、事务发布和回退 |
| `api/app.py` | 参数校验、查询和统一统计接口 |
| `api/analytics.py` | 胜率、投票指标、混血阵营与阶段积分计算 |
| `api/photos.py`、`prepare_photos.py` | 同赛季照片映射及原图访问 |
| `api/schema.sql` | 独立发布库 |
| `web/src/app` | 服务端页面与路由 |
| `web/src/components` | 座位、日夜事件、票型、列表和分页 |
| `tests` | 发布与 API 回归测试 |
| `run.py` | 本地服务启动与清理 |
| `backup.py` | 备份和实际恢复验收 |
