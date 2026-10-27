# 大师赛档案网站

当前发布S22 148局、S23 75局。完整数据加工见[全流程手册](../docs/15_赛季数据全流程操作手册.md)；本站负责公开快照、只读查询与页面。

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
| `prepare_photos.py` | 当前S22/S23照片来源适配，生成API清单和静态资产；新季另行确认映射 |
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

game release变化后，悍跳必须逐季重新预检／同步，数据库版本与对应game release绑定。`website/assets/bluffs/*.json`是发布输入，不是运行时绕过数据库的数据源。照片清单与图片在API侧，更新清单后重启API清缓存。

`GET /api/v1/releases`查看版本，再用`python -m website.api.publish --activate <真实release-id>`回退。它不回退JCMS或磁盘JSON；回退后核对悍跳绑定。

## 验收与备份

```powershell
.\.venv\Scripts\python.exe website/check_publication.py --api-only
.\.venv\Scripts\python.exe website/check_publication.py
.\.venv\Scripts\python.exe -m pytest website/tests -q
.\.venv\Scripts\python.exe -m website.backup --verify-restore
```

通用验收支持`--seasons`、`--baseline <receipt.json>`和`--output`。源与API逐局比对，检查分页、单季／跨季stats、悍跳绑定、已列入清单的照片和桌面／手机页面；无照片本身合法。原固定S22／S23验收入口已合并；特殊结算保留在语义测试中。

API仅导出白名单公开字段，不含本地路径、凭据或全文转写。原始资源、JCMS业务库与`masters_web`网站库分开。整库备份在`scripts/backup_database.py`，`website.backup`只覆盖网站schema。

## 部署

`compose.yaml`、Dockerfile和nginx示例保留为独立部署配置，本机未以Docker实跑。部署前按目标环境配置数据库只读用户、运行时环境变量和反向代理；凭据不写入源码。API镜像需要同步`config/seasons.json`、注册加载器及网站资产；现有Dockerfile已使用集中依赖目录。数据发布与站点访问权限由实际部署环境管理。
