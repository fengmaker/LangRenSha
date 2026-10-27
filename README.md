# 京城大师赛数据项目

把官方媒体整理为可回溯的对局档案，并发布到本机网站。当前保留 **S22 148局、S23 75局，共223局**；原始媒体归档还包含不进入正式统计的表演／娱乐内容。

## 从这里开始

1. [全流程操作手册](docs/15_赛季数据全流程操作手册.md)：以后接入更早赛季，按顺序完成每步工作和验收，已有成果直接复用。
2. [微博分步流程](docs/06_微博排班采集.md)：从已采到的2026-05-26边界继续向前，建立新季姓名、照片及座位对应。
3. [复核规范](docs/16_字段证据与交叉复核规范.md)：判断新增资料的具体字段时查证据矩阵，既有定案保持。
4. [dot复核与历史交接](docs/17_本地与云端协作交接.md)：需要dot提供复核建议或查阅历史交接、验收记录时读取；当前开发与建议采纳遵循[工程约定](AGENTS.md#开发与复核)。

只启动已有网站：

```powershell
Set-Location D:\langrensha
.\.venv\Scripts\python.exe scripts/local_postgres.py start
.\.venv\Scripts\python.exe website/run.py
```

打开 <http://127.0.0.1:3000>；不需要重采、重转写或重新发布。

继续处理一个赛季：

```powershell
.\.venv\Scripts\python.exe scripts/workflow.py status --season S23
.\.venv\Scripts\python.exe scripts/workflow.py plan --season S23
# 按已授权的任务阶段执行；例如只核验网站
.\.venv\Scripts\python.exe scripts/workflow.py run --season S23 --stage verify
```

`status`只读进度；`plan`预览命令；`run`执行指定阶段。新季身份推断与证据核对仍需逐局完成；微博独立采集，不包含在`collect`阶段内。实际进度写入报告，不另生成任务单。

## 文件夹分工

| 目录 | 职责与阅读入口 |
| --- | --- |
| [scripts](scripts/README.md) | 工作流入口和实现；日常只需`workflow.py`，需要定位实现再查职责索引 |
| [config](config/README.md) | `seasons.json`统一赛季注册；正式范围、版型规则、模板及热词分开 |
| [requirements](requirements/README.md) | Python依赖按主环境、网站、测试、可选OCR、ASR分组；ASR使用独立环境 |
| [data](data/README.md) | 原始媒体、文字、证据、正式档案与发布输入；每个职责目录有说明 |
| [website](website/README.md) | Next.js前端、只读API、快照发布和网站验收 |
| [db](db/README.md) | PostgreSQL迁移；通过新增迁移演进，不改已执行迁移 |
| [tests](tests/README.md) | 数据语义、采集来源、转写完整性和事务行为测试 |
| [docs](docs/README.md) | 按当前任务选择手册，历史研究不作日常上下文 |
| [outputs](outputs/README.md) | 模型对照、片段复听及可再生的展示／验收产物 |
| [tmp](tmp/README.md) | 一次性调试和临时日志；不保存唯一证据或最终结论 |

`.venv/`、`.venv-funasr39/`、`.models/`、`.tools/`是运行环境，`.local/`是本机数据库，`.secrets/`存本机凭据；不随普通Git克隆恢复，不作为临时文件清理。`.cache/`和`__pycache__/`才是可再生缓存，清理前确认没有任务在运行。

## 配置与数据约定

- 新季先在[赛季注册表](config/seasons.json)登记来源与适配，完成一局样板再批量；注册不等于已经实现该季全部规则。
- 物理身份、个人胜利阵营、淘汰边分开；玩家自称不等于真实底牌。未知、未发动、不适用、禁止分别保存。
- 原始证据、助手推断、用户确认和正式事实分层保存。业务术语见[CONTEXT](CONTEXT.md)。
- 网站从磁盘正式JSON生成发布快照，不直接读取JCMS事实表；发布必须保留所有已有季。统一入口会检查活动批次中是否有本地缺失季。
- `data/archive/`的哈希文件可能被数据库及复核引用；使用清理器的预览和引用检查，不按文件年代删。

## 环境、检查与备份

安装分组见[requirements说明](requirements/README.md)；主Python3.12与FunASR Python3.9的依赖不能混装。前端在`website/web`安装Node依赖。启动与生产构建细节见[网站手册](website/README.md)。

```powershell
.\.venv\Scripts\python.exe -m pytest tests website/tests -q
.\.venv\Scripts\python.exe scripts/backup_database.py
.\.venv\Scripts\python.exe scripts/cleanup_data.py
# 检查删除清单后才执行：scripts/cleanup_data.py --apply
```

本次结构整理记录在`data/reports/maintenance/2026-10-27/`。模型、媒体、数据库dump和登录设置保留本地；代码、规则、正式JSON和复核文字按项目Git约定保存。远程仓库：[fengmaker/LangRenSha](https://github.com/fengmaker/LangRenSha)。
