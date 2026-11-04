# 大师赛档案网站

当前发布S21 122条媒体档案、S22 148局、S23 90局，共360条档案。S21正式计分总局数与现有缺口留待后续复核，未复核悍跳的次数与成功率显示为空。完整数据加工见[全流程手册](../docs/01_赛季数据全流程.md)；本站负责公开快照、只读查询与页面。

网站版型名称和筛选使用共用模板的统一代码与名称，同版型跨赛季合并统计。赛季存储代码继续用于已核事实和规则适配。

对局档案的日夜、票型与角色事项按[统一呈现规范](../docs/10_对局信息呈现规范.md)渲染，与[人工复核页](../docs/09_复核页面生成规范.md)共用展示序列；常规角色共用规则，特殊版型只补实际差异。发布按[全流程第七步](../docs/01_赛季数据全流程.md#第七步发布所有保留季及新季照片)及本次授权范围执行。

## 目录分工

| 目录／文件 | 职责 |
| --- | --- |
| [api](api/README.md) | FastAPI、发布器、指标、照片／截图访问；运行时只读`masters_web` |
| [web](web/README.md) | Next.js前端，从API取数据；不直接读原始转写或JCMS事实表 |
| [assets](assets/README.md) | 经过确认的同季照片、悍跳发布输入和证据截图 |
| [tests](tests/README.md) | 指标、发布事务、混血阵营、特殊结算、用户反馈等语义回归 |
| [artifacts](artifacts/README.md) | 验收报告、历史备份和回执；不放进网页公开数据 |
| [runtime](runtime/README.md) | 本机服务日志；可再生，不作事实依据 |
| `run.py` | 成对启动API和前端，退出时停子进程；PG单独管理 |
| `check_publication.py` | 唯一通用端到端验收，按当前源动态核对，不写固定赛季局数 |
| `backup.py` | 网站schema备份与临时库恢复验证；全库备份用根scripts/backup_database.py |
| `prepare_photos.py` | S21/S22/S23照片来源适配，生成API清单和静态资产；S21复用已识读的同季名牌及当前档案姓名 |
| [static_publish](static_publish/README.md) | 静态导出、构建、验收、一键同步及 GitHub Pages 部署模板 |
| `积分榜字段说明.txt` | 现行指标的分子分母、未知及悍跳口径 |

## 启动

```powershell
# 项目根目录
.\.venv\Scripts\python.exe scripts/local_postgres.py start
# 首次使用本机网站／静态导出前，配置独立只读账号（数据库中须已有网站发布表）
.\.venv\Scripts\python.exe -m website.grant_reader --local
.\.venv\Scripts\python.exe website/run.py
```

打开<http://127.0.0.1:3000>，API文档在<http://127.0.0.1:8000/docs>。依赖安装使用`requirements/web.txt`，前端在`website/web`运行`npm ci`；启动器会查PATH或`.tools/node/`。需要生产版本时先在前端目录`npm run typecheck`、`npm run build`，再从根运行`website/run.py --production`。

端口可用`--port 3001 --api-port 8001`配对调整。API代码或照片清单更新后重启API；前端生产代码更新后重建。Windows运行中的standalone目录会锁住构建，先停止本站进程。Ctrl+C结束启动器不停止PG。

本机只读账号凭据单独保存在 `.secrets/masters_web_reader.json`，由授权脚本生成；`database.json` 中的开发者凭据仍供发布等写入工具使用。本机API会优先使用只读凭据，即使进程继承了发布器的 `DATABASE_URL` 也不会改用它。静态发布器启动的临时API复用相同配置；部署容器未携带本机 `.secrets`，继续使用Compose中只读角色的 `DATABASE_URL`。

## 发布与回退

日常用统一入口，自动保留全部已存在正式档案的注册季：

```powershell
.\.venv\Scripts\python.exe scripts/workflow.py plan --season S23 --stage publish
.\.venv\Scripts\python.exe scripts/workflow.py run --season S23 --stage publish
```

发布器从`data/games/{season}`正式JSON及规则／投票旁证生成不可变快照；不从JCMS正式对局表读取事实。底层预检使用`python -m website.api.publish --seasons S21 S22 S23 --check`，去掉`--check`才完整发布。无参数和`--sample`只预检。所有活动指针切换共用同一个保护入口，候选缺少当前活动赛季或必需悍跳绑定时拒绝激活；单季发布不能用于“追加一季”。

完整发布先保存未激活的game release，再复用`website/assets/bluffs/*.json`中的人工结果，在同一事务内逐季校验、写入并最后激活。最后一季失败时，所有本次悍跳写入回滚，访客仍读取上一份完整版本；game release未变化时也遵守这个保证。独立`publish_bluffs --release <候选ID> --check`可预览候选绑定，去掉`--check`只准备该候选的悍跳。发布不重算历史规则、不重建悍跳推断；必需输入缺失时明确报错。S21尚未复核悍跳，可发布档案并留空。这些JSON是发布输入，网站查询读取数据库。照片清单与图片在API侧，更新清单后重启API清缓存。

公开选手ID统一来自已纳入版本管理的`website/assets/people.json`，已固化当前90名选手的ID；发布不再根据JCMS是否存在切换人物来源。本批实际使用的姓名与ID进入发布来源哈希和manifest；预检、本机、容器及空网站库重建使用同一份文件。备份正式档案时同时保留此文件，已有姓名的ID保持不变，详见[人物映射说明](api/people.md)。

`GET /api/v1/releases`查看版本，再用`python -m website.api.publish --activate <真实release-id>`回退。它不回退JCMS或磁盘JSON；回退后核对悍跳绑定。

## 验收与备份

```powershell
.\.venv\Scripts\python.exe website/check_publication.py --api-only
.\.venv\Scripts\python.exe website/check_publication.py
.\.venv\Scripts\python.exe -m pytest website/tests -q
.\.venv\Scripts\python.exe -m website.backup --verify-restore
```

通用验收支持`--seasons`、`--bvid BV... [BV...]`、`--baseline <receipt.json>`和`--output`。不加BV时保留完整发布验收；按赛季/BV收窄的报告明确标为`partial`，只请求所选局详情，再核对受影响选手及轻量全局版本/覆盖/唯一性。报告记录源读取范围、验收局数、请求数与耗时，局部通过不能代替完整验收。源与API逐局比对，检查分页、单季／跨季stats、悍跳绑定、已列入清单的照片和桌面／手机页面；无照片本身合法。特殊结算保留在语义测试中。

API仅导出白名单公开字段，不含本地路径、凭据或全文转写。原始资源、JCMS业务库与`masters_web`网站库分开。整库备份在`scripts/backup_database.py`，`website.backup`只覆盖网站schema。

## 静态成品

静态发布脚本和模板统一放在 [static_publish](static_publish/README.md)，修改位置、环境前提、预览、上线、失败处理及回退均见该目录说明。日常在项目根执行：

```powershell
.\.venv\Scripts\python.exe website/static_publish/sync_pages.py
```

命令读取本地已正式发布的数据，增量复用响应和图片，通过检查后同步独立发布仓库、提交推送并等待部署，最后核对线上版本。它不负责数据入库、本地正式发布或源码仓库提交。仅数据变化时复用网页程序，首次或网页源码变化时才执行 Next 构建；默认浏览器检查关键入口和改动相关页面。加 `--skip-browser-check` 可跳过浏览器检查，文件、API 和版本检查仍保留，详见静态发布说明。

网页源码继续修改 `web/src`，API 与统计逻辑修改 `api`；`D:\langrensha-site\site` 是生成成品，由脚本维护。仅构建预览和运行目录说明见 [操作流程](static_publish/README.md#只构建与预览不上线)。

## 部署

GitHub Pages 使用上节的合格静态成品和独立发布仓库，部署状态以[执行方案](../docs/11_GitHub_Pages静态发布执行方案.md)的实际执行记录为准。下文继续描述全栈部署方式。

历史交付、接入与验收状态见[dot-handoff索引](../dot-handoff/README.md)及[接续记录](../dot-handoff/INTEGRATION.md)；下文按目标环境执行并记录实际结果。

以下为独立目标环境的操作交接，不代表已经部署成功。Compose默认一次发布S21/S22/S23完整活动集；API镜像包含当前照片、悍跳输入、证据截图及发布所需规则模块。当前准备基线为357条档案，没有修改正式数据、数据库schema或JCMS迁移。

### 配置与边界

在 `website` 目录运行以下命令。目标机器需有Docker Compose、完整S21/S22/S23正式JSON、档案引用的字幕／转写、投票旁证（源中存在时）、配置／网站资产；字幕／转写用于绑定发言证据和生成一致的来源哈希，无旁证的赛季挂载目录可为空。数据不打进镜像，发布服务只读挂载指定目录；API运行时不挂载原始数据，不使用管理员账号。

部署文件应来自同一份当前工作目录，保留项目相对路径及原始字节。源文件范围以 `compose.yaml` 的只读挂载为准：包含S21的 `data/extractions/S21/media_evidence` 警上发言旁证，以及S23新增对局对应的 `incremental_review.json`、`data/reports/S23/S23_逐局复核计划.json` 和 `data/reports/S23/incremental/reviews` 人工确认原件。悍跳发布工具也挂载S23正式档案和这两处复核来源，用于校验新增局数；S21目前没有悍跳发布输入，保留未复核状态。

上传 `data/seasons` 和S21旁证目录时只需保留文本资料，音频／视频无需上传；`.dockerignore` 也将原始数据排除在镜像构建上下文之外。API镜像从 `website/api` 复制照片／截图清单，并复制 `website/assets/player-photos`、`bluffs` 和 `bluff-frames` 整目录，包括最新两名选手照片。若使用Git拉取部署，必须先确保当前代码、正式档案、复核原件和清单内资产均已纳入目标版本，不能用旧提交替代当前工作目录。

在目标环境的私有 `website/.env` 或受控环境变量中设置 `POSTGRES_PASSWORD`、`POSTGRES_READER_PASSWORD`（后者至少20字符），不要提交或粘贴凭据。密码用于连接URI，应使用高熵URI安全字符，或按目标环境正确处理URI编码；不要将示例值用于实际部署。`SITE_PORT` 默认3000，前端仅绑定127.0.0.1；公网反向代理／TLS与访问策略需另外审查。不要把 `docker compose config` 展开的凭据保存到公开日志，校验时使用 `--quiet`。

### 首次发布顺序（仅在获准部署的目标环境执行）

每一步成功后才继续；不要直接 `up -d` 启动尚未初始化的API。

```sh
docker compose config --quiet
docker compose build api web publish publish-bluffs reader-setup
docker compose up -d db

# 只检查磁盘源，不连接／写数据库；必须保留全部目标赛季。
docker compose run --rm publish --seasons S21 S22 S23 --check
# 准备候选game release，所有悍跳校验、写入成功后一起激活。
docker compose run --rm publish --seasons S21 S22 S23

# 可选：核对刚发布版本的悍跳；完整发布已完成两季绑定。
docker compose run --rm publish-bluffs --season S22 --check
docker compose run --rm publish-bluffs --season S23 --check

# 仅在上述发布全部成功后，由获授权管理员运行已有脚本。
docker compose run --rm reader-setup
# API使用masters_web_reader；发布工具才使用masters管理员连接。
docker compose up -d api web
```

发布器和悍跳发布器使用同一个 `website/api/schema.sql`，无需运行JCMS业务迁移。完整发布从`MASTERS_SOURCE_ROOT`读取正式档案、人物映射、配置、增量确认和悍跳输入，先保存候选，再将各季悍跳写入和激活合为一个事务。独立`publish-bluffs`默认从包根目录`/app`读取配置及新增对局确认来源。激活与回退均检查保留赛季及必需悍跳绑定；失败排查后可重跑，尚未完成的候选不会成为访客活动版本。

### 只读账号与验收

沿用 `website/grant_reader.py`，不要手工猜测授权SQL：它要求已存在 `masters_web.releases`，创建或更新 `masters_web_reader`，设 `NOINHERIT` 和默认事务只读，撤销该角色在 `masters_web` 的旧schema／表授权，再授予schema USAGE、现有表SELECT及当前建表者未来表SELECT。脚本拒绝带管理属性、角色成员关系或对象所有权的同名角色，并检查`masters_web`不存在有效写权限，使用独立登录实际读取活动快照，再在显式读写事务中确认对`active_release`的UPDATE被拒绝。首次正式及悍跳发布后再运行，可确保相关表已创建；后续必须由同一发布角色建表，否则需管理员重新审查默认权限。

本机配置使用 `python -m website.grant_reader --local`，管理员凭据读取自 `.secrets/database.json`，读者密码独立保存在 `.secrets/masters_web_reader.json`。部署配置使用环境变量 `DATABASE_URL` 与 `MASTERS_READER_PASSWORD`。脚本不会修改业务数据或活动版本；显式写入探针带 `WHERE false`，并且角色权限检查先于探针。

目标环境上线前核对：API `/health`、`/api/v1/releases`、S21/S22/S23各122／148／87条档案（当前共357条）、S22/S23悍跳的game release绑定、三季照片和清单内102张S23截图可访问，再运行本README的通用验收（通过环境变量 `MASTERS_API_URL`、`MASTERS_WEB_URL` 指定目标地址）及桌面／手机浏览器检查。Compose没有向宿主机发布API端口，验收程序必须在获准且可达API服务的目标网络中运行，不能默认宿主机 `localhost:8000` 可用；不要为验收擅自开放公网API端口。源数据更新时以当前正式范围为准，不把这些基线数量当成永久规则。正式备份与恢复验证仍按上节执行；不要删除持久卷来排障。

本地部署回归使用 `python -m pytest website/tests/test_deployment_contract.py -q`：只复制Compose声明的发布源和API镜像的COPY输入，在独立Python进程中执行三季离线预检，与完整工作目录的计数、来源哈希及release逐项比较，并核对新增对局计数和图片字节哈希。该检查不连接或修改数据库。本次环境未安装Docker，未执行Docker构建、Compose运行或云端上线；目标服务器仍须完成上述运行与验收。
