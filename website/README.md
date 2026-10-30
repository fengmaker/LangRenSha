# 大师赛档案网站

当前发布S21 122条媒体档案、S22 148局、S23 84局，共354条档案。S21正式计分总局数与现有缺口留待后续复核，未复核悍跳的次数与成功率显示为空。完整数据加工见[全流程手册](../docs/01_赛季数据全流程.md)；本站负责公开快照、只读查询与页面。

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
| `积分榜字段说明.txt` | 现行指标的分子分母、未知及悍跳口径 |

## 启动

```powershell
# 项目根目录
.\.venv\Scripts\python.exe scripts/local_postgres.py start
.\.venv\Scripts\python.exe website/run.py
```

打开<http://127.0.0.1:3000>，API文档在<http://127.0.0.1:8000/docs>。依赖安装使用`requirements/web.txt`，前端在`website/web`运行`npm ci`；启动器会查PATH或`.tools/node/`。需要生产版本时先在前端目录`npm run typecheck`、`npm run build`，再从根运行`website/run.py --production`。

端口可用`--port 3001 --api-port 8001`配对调整。API代码或照片清单更新后重启API；前端生产代码更新后重建。Windows运行中的standalone目录会锁住构建，先停止本站进程。Ctrl+C结束启动器不停止PG。

## 发布与回退

日常用统一入口，自动保留全部已存在正式档案的注册季：

```powershell
.\.venv\Scripts\python.exe scripts/workflow.py plan --season S23 --stage publish
.\.venv\Scripts\python.exe scripts/workflow.py run --season S23 --stage publish
```

发布器从`data/games/{season}`正式JSON及规则／投票旁证生成不可变快照，在事务内切换活动release；不从JCMS正式对局表读取事实。底层命令示例为`python -m website.api.publish --seasons S22 S23 --check`，通过后去掉`--check`。单季`--season`或`--sample`会替换完整活动集，不能用于“追加一季”。

game release变化后，已有悍跳发布输入必须逐季重新预检／同步，数据库版本与对应game release绑定。统一入口优先复用`website/assets/bluffs/*.json`，避免重建推断覆盖人工结果；没有输入且没有悍跳适配的赛季可先发布档案，悍跳留空。这些JSON是发布输入，不是运行时绕过数据库的数据源。照片清单与图片在API侧，更新清单后重启API清缓存。

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

## 部署

历史交付、接入与验收状态见[dot-handoff索引](../dot-handoff/README.md)及[接续记录](../dot-handoff/INTEGRATION.md)；下文按目标环境执行并记录实际结果。

以下为独立目标环境的操作交接，不代表已经部署成功。基线 `dfd2f94aaa24a71db7e61e627985f0437db353ba` 的审计发现：Compose只挂载／发布S22，API镜像漏掉悍跳证据截图。本配置补齐S22/S23与 `assets/bluff-frames`；没有修改正式数据、数据库schema或JCMS迁移。

### 配置与边界

在 `website` 目录运行以下命令。目标机器需有Docker Compose、完整S22/S23正式JSON、档案引用的字幕／转写、投票旁证（源中存在时）、配置／网站资产；字幕／转写用于绑定发言证据和生成一致的来源哈希，无旁证的赛季挂载目录可为空。数据不打进镜像，发布服务只读挂载指定赛季目录；API镜像包含照片、悍跳输入和截图。API运行时不挂载原始数据，不使用管理员账号。

在目标环境的私有 `website/.env` 或受控环境变量中设置 `POSTGRES_PASSWORD`、`POSTGRES_READER_PASSWORD`（后者至少20字符），不要提交或粘贴凭据。密码用于连接URI，应使用高熵URI安全字符，或按目标环境正确处理URI编码；不要将示例值用于实际部署。`SITE_PORT` 默认3000，前端仅绑定127.0.0.1；公网反向代理／TLS与访问策略需另外审查。不要把 `docker compose config` 展开的凭据保存到公开日志，校验时使用 `--quiet`。

### 首次发布顺序（仅在获准部署的目标环境执行）

每一步成功后才继续；不要直接 `up -d` 启动尚未初始化的API。

```sh
docker compose config --quiet
docker compose build api web publish publish-bluffs reader-setup
docker compose up -d db

# 只检查磁盘源，不连接／写数据库；必须保留全部目标赛季。
docker compose run --rm publish --seasons S22 S23 --check
# 写入完整活动game release；自动执行 website/api/schema.sql。
docker compose run --rm publish --seasons S22 S23

# 悍跳预检读取真实活动数据库；不同于上面的离线源预检。
docker compose run --rm publish-bluffs --season S22 --check
docker compose run --rm publish-bluffs --season S23 --check
# 两季都预检成功后，分别绑定到刚发布的同一个game release。
docker compose run --rm publish-bluffs --season S22
docker compose run --rm publish-bluffs --season S23

# 仅在上述发布全部成功后，由获授权管理员运行已有脚本。
docker compose run --rm reader-setup
# API使用masters_web_reader；发布工具才使用masters管理员连接。
docker compose up -d api web
```

发布器和悍跳发布器使用同一个 `website/api/schema.sql`，无需运行JCMS业务迁移。`publish-bluffs`只读挂载 `/app/config`，因为完整对局数校验读取包根目录配置，不读取 `MASTERS_SOURCE_ROOT`。正式发布会替换整个活动集，单季或 `--sample` 不是追加操作；悍跳两个发布各自事务化，**不是跨两季原子事务**。任一失败则停止上线，排查后重跑并确认两季绑定；更新已有站点时需在获准维护窗口完成，不要让访客看到中间状态。game release变化或回退后，两季悍跳均需重新预检／同步。

### 只读账号与验收

沿用 `website/grant_reader.py`，不要手工猜测授权SQL：它要求已存在 `masters_web.releases`，创建或更新 `masters_web_reader`，设默认事务只读，仅显式授予 `masters_web` 的schema USAGE、现有表SELECT及当前建表者的未来表SELECT。首次正式及悍跳发布后再运行，可确保相关表已创建；后续必须由同一发布角色建表，否则需管理员重新审查默认权限。脚本会更新既有同名角色密码，拒绝已有superuser／createrole／createdb权限的同名角色。

此脚本不是通用角色清理器，不撤销历史授权或角色成员关系，默认事务只读也不能替代权限隔离。对于既有数据库，同名角色的成员关系、继承权限、PUBLIC授权和跨schema写权限必须先由管理员审计；未确认最小权限时不要用于运行时。本文只描述已有授权流程，本次准备没有创建角色、设置密码或修改数据库安全配置。

目标环境上线前核对：API `/health`、`/api/v1/releases`、S22/S23各148／75局、两季悍跳的game release绑定、照片和清单内102张S23截图可访问，再运行本README的通用验收（通过环境变量 `MASTERS_API_URL`、`MASTERS_WEB_URL` 指定目标地址）及桌面／手机浏览器检查。Compose没有向宿主机发布API端口，验收程序必须在获准且可达API服务的目标网络中运行，不能默认宿主机 `localhost:8000` 可用；不要为验收擅自开放公网API端口。源数据更新时以当前正式范围为准，不把这些基线数量当成永久规则。正式备份与恢复验证仍按上节执行；不要删除持久卷来排障。

本次仅完成静态Compose配置检查、离线223局源预检及纯／mock测试；Docker构建／容器运行、PostgreSQL实际发布／授权、完整API集成与浏览器验收未运行（当前云环境相关能力受限）。这些检查通过前，不应宣称已复现有数据的完整网站或已可上线。
