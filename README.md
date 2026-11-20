# 京城大师赛档案

长期保存网站源码、最终对局、必要来源和通用增量流程。S21 的正式计分总局数仍未确认，媒体档案数量不代表正式计分局数。

每局只有 `data/games/<赛季>/<局目录>/game.json` 一份正式结果。它保存身份、个人阵营、事件、逐人选票、终局、存活结算、悍跳及成功结果和未知状态，以及 BV、CID、分 P 与官方链接。选手 ID、版型规则、赛季设置和正式照片继续保存。

网站直接读取最终 JSON，复用共用统计生成本地静态数据，不依赖数据库、动态 API、全文转写、历史复核页或反馈原件。

```powershell
.\.venv\Scripts\python.exe website/run.py
```

打开 <http://127.0.0.1:3000>。安装说明见 [requirements](requirements/README.md)，网站及显式上线见 [website](website/README.md)。本地运行不会同步线上静态网站。

常用窗口指令与 PowerShell 命令见[常用命令](docs/01_常用命令.md)。新增对局从[增量更新流程](docs/02_增量更新流程.md)开始：

```powershell
.\.venv\Scripts\python.exe scripts/workflow.py status --season S23
.\.venv\Scripts\python.exe scripts/workflow.py plan --season S23
```

查看当前档案数时，将 `--season` 换成对应赛季，读取 `status` 输出的 `formal_games`。`workflow.py` 统一提供采集、准备当前批次、生成复核页、写入最终结果、导出和验证。分析由当前窗口选用的模型完成，不另起模型调用。写入结果及上线按用户明确范围执行。

| 目录 | 长期职责 |
| --- | --- |
| `website/` | 网站、共用统计、照片基线与静态导出 |
| `data/games/` | 每局最终 JSON |
| `data/sources/` | 通用规则必要来源和增量采集检查点 |
| `data/indexes/` | 官方媒体采集计划，用于发现新增来源 |
| `config/` | 人物之外的赛季与版型规则、模板、主转写热词 |
| `scripts/` | 通用采集、当前增量和结算工具 |
| `docs/` | [流程与业务规范](docs/README.md) |
| `tests/`、`website/tests/` | 规则、统计、复核输入和导出回归 |

当前批次的截图、转写、候选和人工复核页只在本机临时保存，完成后可清理；旧局修订需要重新取源。`.venv*`、`.models`、`.tools`、`.secrets` 为本机环境；`.local` 是已退役的旧数据库文件，不是网站输入。Git 普通删除不移除历史对象；历史改写与远端操作需另按明确授权执行。
