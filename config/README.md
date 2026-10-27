# 配置

日常从[赛季注册表](seasons.json)开始，只读本次任务需要的规则文件。执行入口为`python scripts/workflow.py`。

| 文件／目录 | 职责 |
| --- | --- |
| `seasons.json` | 唯一运行期赛季注册：名称、状态、官方合集、种子BV、规则／范围文件引用、复核／导入／悍跳适配；采集CLI与网站API共同读取 |
| `S22_game_scope.json`、`S23_game_scope.json` | 该季正式范围、排除条件或固定候选快照；媒体归档范围与正式范围分开 |
| `S22_formal_rules.json`、`S23_formal_rules.json` | 该季已采用的版型、字段、角色和结算口径；结构不同是实际适配差异 |
| `S23_review_rules.json` | 带来源、状态和作用域的现场案例／用户确认；不是所有赛季的通用规则 |
| [board_templates](board_templates/README.md) | 固定事件槽、动作枚举、角色配置；S23同名规则变化用独立模板，不覆盖旧季 |
| `game_rules.json` | 现有已确认的固定座位及机械狼等共有约定，使用前核对作用域 |
| `scoring_rules.user_reported.v1.json` | 用户报告计分规则及未决项，不声称已官方验证；旧季计分需逐季确认 |
| `asr_hotwords.txt` | 全文Paraformer热词 |
| `asr_recap_hotwords.txt` | 复盘专项热词，显式选择，替换默认词表 |
| `asr_review_hotwords.txt` | Nano片段复核的精简热词，不超过50个 |
| `S22_standard_sample.json` | 复盘短样本的来源与定位 |
| `S22-pilot-board.candidate.json` | 早期已登记规则候选，仅供来源追溯，不是正式录入规则 |

运行配置已提取到注册表；历史正式规则和范围文件仍保留原路径与字节，因为S23快照、导入回执和发布版本绑定它们的SHA256。改动规则时应形成明确的新版本和重核范围，而不是为了整理文件夹移动并破坏证据链。

新增季：注册来源 → 准备该季范围／规则／模板 → 指定并实现适配 → 样板验证；仅新增一行注册表不会自动生成逐局复核或授权。
