# 京城大师赛数据项目

把官方媒体整理为可回溯的对局档案，并发布到本机网站。当前展示 **S21 122条媒体档案、S22 148局、S23 84局，共354条档案**。S21先发布现有结果，正式计分总局数与缺口留待后续复核，未复核悍跳留空；原始媒体归档还包含不进入正式统计的表演／娱乐内容。

## 从这里开始

数据接入统一看[赛季数据全流程](docs/01_赛季数据全流程.md)：先采原件，再核实嘉宾与座位、姓名、底牌，随后恢复日夜流程和票型，再识别悍跳并计算成功率，核对后按已有适配写库，按指定范围做独立复核；缺文字时才转写音频。

1. [全流程操作手册](docs/01_赛季数据全流程.md)：按八步完成采集、核实、入库、复核、发布和验收，复用已有已核成果。
2. [嘉宾与座位身份核实](docs/01_赛季数据全流程.md#第二步核实当天嘉宾与每局座位姓名真实底牌)：复用既有姓名照片映射，按新增资料核实。
3. [复核规范](docs/02_字段证据与交叉复核规范.md)：判断新增资料的具体字段时查证据矩阵，既有定案保持。
4. [每日增量更新](docs/08_增量更新流程.md)：在自选模型的窗口说“增量更新”，直接整理新增资料并生成备注复核页；确认结果后再按授权入库发布。
5. [人工复核入口](data/manual_review/index.html)：待核页面、清单和导出反馈统一放在`data/manual_review/`；按[复核页生成](docs/09_复核页面生成规范.md)与[对局信息呈现](docs/10_对局信息呈现规范.md)执行，悍跳及成功由用户选择。

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
| [scripts](scripts/README.md) | 工作流入口和实现；新增对局按增量流程使用三个入口，既有阶段使用`workflow.py` |
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
.\.venv\Scripts\python.exe scripts/local_postgres.py start
.\.venv\Scripts\python.exe -m pytest tests website/tests -q
.\.venv\Scripts\python.exe scripts/backup_database.py
.\.venv\Scripts\python.exe scripts/cleanup_data.py
# 检查删除清单后才执行：scripts/cleanup_data.py --apply
```

本次结构整理记录在`data/reports/maintenance/2026-10-27/`。模型、媒体、数据库dump和登录设置保留本地；代码、规则、正式JSON和复核文字按项目Git约定保存。远程仓库：[fengmaker/LangRenSha](https://github.com/fengmaker/LangRenSha)。
