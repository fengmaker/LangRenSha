# S22/S23 逐局公开展示语义审计

## 先看结论

对正式范围 **S22 148局 + S23 75局**，在内存中执行现有 `load_release → _public_game → effective_faction → build_game_presentation`，并用真实 TSX 组件做离线 React SSR，确认 **7类已触发映射问题、31局涉及本次确认的展示差异**。未修改正式数据、网站代码、数据库，未推送或部署。**未访问生产网站；这不是线上页面验收或原媒体事实重核。**

范围基线：`origin/ci/full-acceptance = 3476a56af155f36a0d0050abc1660ed0d6fd538a`；实际只读工作树 `actions-acceptance` 为 `f31de2b059b54667419c68b12a16c01c76973b07`，父审计已确认除 dot-handoff 外与基线零差异。源码文件 SHA256、输入 source/rules hash、每局覆盖均在 `presentation-audit.json`。

### P-01｜3局流徽原因被改写成“延期竞选再次自爆”

| 正式对局 | 正式记录 | 实际前端渲染 |
|---|---|---|
| S23 2026-09-15 第2局 `BV1MheH6wEBb` | D1警徽初轮、PK轮均完整，2/5双平票；D1流徽 | “延期警长竞选再次被狼人自爆中断，警徽流失…” |
| S23 2026-10-06 第2局 `BV17xpA6aE7N` | D1全员上警，警下空，无警徽票轮；D1流徽 | 同上 |
| S23 2026-10-15 第1局 `BV1i6J163EnN` | D1全员上警，`badge.result=全员上警，警徽流失` | 同上，且紧邻原文“全员上警”造成页面自相矛盾 |

**原因**：`website/api/game_presentation.py:416–427` 只检查 `days.sheriff=badge_lost`，没有区分首日全员上警、双平票和延期再次自爆，就写入后者推断；`website/web/src/components/event-board.tsx:56` 又对所有 `badge_lost` 硬编码同一原因。现有56条流徽展示推断中，53条位于D2，以上3条位于D1；只把这3条列为已证实错误，未由日次单独确认其余53条原因。

**影响**：终局/警徽归属未改，但首日事件、竞选延期、狼自爆发生次数和因果叙事被错误表达。应保留已知流徽状态，只在来源满足条件时显示具体原因；不是重新询问已确认流徽。

### P-02｜S23末神猎人无枪窗被展示成枪口待核

`S23 2026-09-22 第1局 BV1gBhn6dE5c`：正式记录N2出局7号女巫、12号白神，N3出局3号预言家，D4放逐11号猎人；11号是最后一神。源 `hunter_shot=unknown` 为保留未知，不应改成主动不开枪。

`config/S23_formal_rules.json:32`、`docs/16_字段证据与交叉复核规范.md:88` 已明确S23末神猎人出局即终局、无后续开枪窗口。展示却通过 `game_presentation.py:599–616` 的“未被毒→can_shoot”，再经 `794–841` 生成：**“档案确认猎人本日出局且具备开枪资格，但未记录开枪目标，请复核。”** 真实组件 SSR 已复现该文字。

父级S23证据审计另已定位原字幕SHA `52fdc23075a5345be636f9cd9d7aea233e5e9dbc795a45c11ec886a1f71d6b5d`、6303610–6310080ms：“白天最后一张神职牌 / 11号猎人被抗推出局 / 游戏结束 / 狼人阵营屠神获胜”。这是父级交叉证据，本子审计没有独立回听媒体。`daily_audit` 对该 unknown 无 human_questions；不能把展示程序制造的待核项当成需要用户重判的事实疑问。

**建议边界**：修展示终局限制，保持源 unknown，不补枪口、不记主动不开枪。S22另有11条猎人待核展示推断，后经本季既有确认和旁证交叉核对，其中9局夜终局另列P-06、1局傀儡禁用另列P-07；`BV11uMG6PEkr`为绑票白天末局，不计为已确认错误。这里不跨季套用S23规则。

### P-03｜补充档案里的DQ未进入存活投影，已DQ猎人连续被展示可开枪

`S23 2026-10-13 第3局 BV1BmpB6PE2C` 的正式 `supplemental.json` 有D2独立出局：`disqualification / disqualify / targets=[8]`，结果为“8号猎人被DQ出局；独立于平安夜的普通死亡结算”。公开快照没有这条补充事件，也没有相关 `public_notes`；`endgame.phases=[]`。

因此 `presentation` 在 **N3、N4、N5** 仍把8号猎人的空状态推断成 `can_shoot`，真实组件渲染“8号小苍（猎人）本夜可开枪”。这是正式补充记录与展示推导之间的确定矛盾。父级S23媒体链审计另已定位原字幕SHA `10d159a35b3c268840bff0f65dd5561c587295dee167f17654d48919c8747c83`、5334269–5342480ms：猎人于机械狼行动夜间错误摘盔DQ；N2发生、D2公告。本子审计未独立回听媒体，保留该交叉证据的来源边界。

**位置**：`publisher.py:334–349` 将 supplemental 纳入hash但只将 formal_context作为公开上下文；`_public_game`未传补充出局；`game_presentation.py:210–244,599–616,1020` 的出局集合/资格推断因而看不到DQ。应使已核独立出局成为投影约束，同时保留“DQ不是普通狼刀死亡”区别。

### P-04｜本次确认12局终局后仍生成“第N天”区块（S23 3局 + S22 9局）

下表为S23 3局；S22 9局及其本季独立终局依据见P-06。这里只声明所列12局，不把其他未经逐局证据核对的终局候选一并判错。

| 正式对局 | 正式字段已给出的边界 | 真实SSR白天区块 |
|---|---|---|
| S23 2026-10-02 第3局 `BV1K3aQ6zEB9` | N3机械狼交牌；D3 `exile_result.result=N3机械狼交牌，D3未开始` | 含第3天、夜间出局待核、“本日无人被放逐”，旁边又写D3未开始 |
| S23 2026-10-02 第4局 `BV123aQ6BEu2` | N3机械狼交牌；D3 `exile_result.result=机械狼在夜间选择交牌，D3未开始` | 同样含第3天、待核死亡、“本日无人被放逐” |
| S23 2026-10-15 第2局 `BV1i6J163Ees` | N4 `night_deaths.result=N4假面击杀4号白神终局；游戏结束未进入D4。`；D4放逐不存在 | 含第4天及“本日无人被放逐” |

**位置**：仅 `publisher.py:279–290` 在 `formal_context.terminal_observation` 非空时裁边；以上3局该字段为空。`game_presentation.py:672–684,1006` 保留重要未知/明确none日事件，`event-board.tsx:119–136` 有day事件就生成白天，`64` 将 `exile_result none` 一概译成“本日无人被放逐”。因此“根本没有这个白天/放逐环节”变成“这个白天举行而无人出局”。应在确认的终局边界上裁切/归置终局结果；不能仅删除夜末真实死亡以掩盖问题。

父级S23媒体链审计另已定位：`BV1K3aQ6zEB9` 原字幕SHA `8001b18179fb7e99383ba5b8f85e4116a9fa919cea27cf2f245189d948ae4386`、3847320–3852140ms“机械双刀狼夜间交牌游戏结束”；`BV123aQ6BEu2` SHA `4250475d6f604f66dfca8ddae4482f35840311c4bb6d27005c7738fab39eec3e`、2136870–2141770ms“夜睁眼交牌游戏结束”。本子审计未独立回听这些媒体；第三局 `BV1i6J163Ees` 此处仅依据已存在正式字段作映射矛盾判断。

**已排除误报**：`BV1U3p86dEHL` 的文字是“D2未开始放逐”，仅否定放逐、不否定白天，本报告不将其列为虚构白天。`BV17xpA6aE7N` 已有N4 terminal_observation，公开day为空且D4 voting全为unknown/not_applicable，真实前端不会重生D4；现有这一裁切路径有效。

### P-05｜13局14轮技能重投被显示成“其他投票轮次”

正式枚举是 `revote`（`scripts/voting_records.py:362` 校验；`:552` 译“技能触发重新投票”），前端 `ballot-panel.tsx:5` 却只识别 `skill_revote`，所以当前 **S22 7局8轮、S23 6局6轮** 全落到“其他投票轮次”。没有误写成PK，但用户无法从该轮标题辨认技能重投。

| 赛季 | 日期/局次 | BV | 轮次 |
|---|---|---|---|
| S22 | 2026-06-11 第2局 | BV13tEB6VEVV | D3 / `causal-ballot-2-d3` |
| S22 | 2026-06-16 第2局 | BV1W6jG6HELj | D3 / `ballot-4` |
| S22 | 2026-06-18 第2局 | BV1Hjja6zEZa | D3 / `ballot-4` |
| S22 | 2026-07-09 第2局 | BV1hZMp63Esx | D4 / `ballot-4` |
| S22 | 2026-07-09 第2局 | BV1hZMp63Esx | D4 / `causal-ballot-review-day-4-exile-revote-d4` |
| S22 | 2026-07-23 第2局 | BV19Ggx6xEqE | D1 / `ballot-3` |
| S22 | 2026-07-31 第2局 | BV1iDGK61E2z | D1 / `ballot-3` |
| S22 | 2026-08-18 第2局 | BV1jc836TEt1 | D1 / `ballot-4` |
| S23 | 2026-09-09 第2局 | BV1ddY46sEgn | D3 / `ballot-5` |
| S23 | 2026-09-16 第2局 | BV1yAeA6qE7X | D1 / `ballot-3` |
| S23 | 2026-09-22 第2局 | BV18Bhn6dEJ6 | D1 / `ballot-4` |
| S23 | 2026-09-30 第2局 | BV1V8af6zEtX | D1 / `ballot-3` |
| S23 | 2026-10-07 第2局 | BV1gmHy6vECS | D1 / `ballot-3` |
| S23 | 2026-10-14 第2局 | BV1vgpm6nEz6 | D1 / `ballot-4` |

专项 `BV1vgpm6nEz6` 的 ballot-3/4 `result` 确实未进入公开BALLOT白名单，但**不能说警徽半票/技能解释全部丢失**：`dossier D1 exile_vote.result`已有“首轮原始票6/12各6票；警徽计票后报6号6.5票，随后定序王子翻牌触发重新投票”，`prince_skill`事件也保留说明，真实SSR已看到。其确切缺陷是 ballot-4 `stage=revote` 标签漏映射；首轮不作最终放逐和第二轮最后12号出局仍被正确保留。

### P-06｜S22本季已确认夜终局的9局，被展示成下一白天且猎人枪口待核

**不是套用S23规则。** S22已有 `data/extractions/S22/用户确认_20261025_存活与终局.txt`：

> 如果夜晚刀人之后已经达成屠边规则，游戏就已经结束了，不会再有下一天白天了。

该文件SHA256为 `8ed5af2fae1e749c1c4d4a963fe3247debb043add3bba491375aba663a524d8e`。以下9局的同版本投票提取旁证 `game_flow.terminal` 均明确 `phase=night`、`eliminated_side=god`，`display_phases` 已排除下一白天；S22事实审计已核对相应复盘，确认入夜击杀最后神猎人、游戏结束。9局旁证 `dossier_sha256` 均与本次正式 dossier 原字节SHA一致，脚本已断言其绑定；既有原文定位和SHA摘录见 `s22-established-context.json`，本子审计未重新下载或转写媒体。

| 正式对局 | BV | 已确认结束边界 | 实际多出的白天 |
|---|---|---|---|
| 2026-07-02 第3局 | `BV149TJ6WETs` | N4 / 仅到D3 | D4 |
| 2026-07-08 第3局 | `BV1suMG6PEYP` | N5 / 仅到D4 | D5 |
| 2026-07-14 第4局 | `BV1WEN86gERp` | N3 / 仅到D2 | D3 |
| 2026-07-23 第3局 | `BV1RGgx6xEP9` | N5 / 仅到D4 | D5 |
| 2026-07-24 第2局 | `BV1iMgq6ZEtz` | N3 / 仅到D2 | D3 |
| 2026-07-28 第3局 | `BV13g3z6FEdh` | N4 / 仅到D3 | D4 |
| 2026-08-05 第3局 | `BV1DFM26MEWR` | N5 / 仅到D4 | D5 |
| 2026-08-20 第1局 | `BV1kG8A6dEfF` | N4 / 仅到D3 | D4 |
| 2026-08-20 第2局 | `BV1kG8A6dEye` | N4 / 仅到D3 | D4 |

真实组件SSR对以上9局都生成末尾D区块，同时展示“档案确认猎人本日出局且具备开枪资格，但未记录开枪目标，请复核”。这并非把正式档案未知补全，而是忽略本季已存在的终局边界，制造了没有发生的下一白天和待核枪口。`BV1suMG6PEYP`源 `hunter_shot.actor=null`，展示仍按本局唯一猎人推导出同样问题，不能因为actor空就忽略。

**根因位置**：`publisher._public_game` 将投票旁证仅用于默认弃票，未把已有 `audit.game_flow.terminal/display_phases` 带入公开终局限制；当前终局裁切只读 `formal_context.terminal_observation`。`game_presentation.py:794–841` 不知终局仍生成待核枪口；前端按保留day事件生成区块。应在经过来源绑定的S22既定边界上裁切并保存终局夜结算，而不是补枪口、记主动不开枪或让用户重审既有定案。

脚本范围特意限定为 **S22的11条现有hunter_shot展示推断中，terminal.phase=night且terminal.round与待核白天相同的9条**，所以没有把所有自动推演terminal都当作新事实，也没有将 `BV11uMG6PEkr` 的绑票白天末局计错。

### P-07｜S22已确认的傀儡猎人禁用，又被写成资格待核

`S22 2026-07-17 第2局 BV12pNo6HEuV`：正式N1 `puppet_select/select/targets=[6]`；同夜 `puppet_skill_effect/skill_disabled` 的result明确“6号猎人被选为傀儡，猎人技能失效”。D4正式放逐6号。既有复盘源SHA `7065208c3b538967ad50b46bd2c55b1eed05db10f285f7b67b1200aee4ec6cf5`，8871.180–8873.620s为选择6号猎人为傀儡，8918.770–8922.190s为D4傀儡猎人出局；来源是S22事实审计已核的review_bundle，本子审计未回听。

`_annotate_hunter_state`（`game_presentation.py:594–597`）确实识别持续的傀儡状态，因而不推断can_shoot；但 `_annotate_pending_hunter_shot`（`:794–841`）没有接收这个持续状态，只看本日 `puppet_hunter_eligibility` 空槽，又生成：**“猎人本日出局，开枪资格或开枪目标仍待核；档案未记录枪口，请复核。”** 实际React SSR已复现。这是禁用已在源中明确时又制造疑问，不是媒体信息不足；应复用已存在禁用状态，不补枪口。

## 已检查而未发现本范围差异的路径

- 223局公开投影执行成功；603条展示推断、7817条省略事件均计数；输入深拷贝一致，未修改输入对象。数量只是结构覆盖，不是媒体真实性证明。
- 混血底牌、个人阵营分别展示；`app._resolved_snapshot` 使用 effective_faction，并在 data_notes 标明推导；不能把源阵营null但唯一榜样可确定当成事实缺失。
- `SeatGrid`保留真实role；学习/榜样文字分开，不把机械学习结果改成底牌。
- 毒药 effects 原目标/实际出局单列；前端有 resolved_targets 单列交换后实际目标。未凭代码阅读保证所有媒体结算正确。
- 真实React SSR覆盖上述问题涉及的31局；未启动Next服务/浏览器，未检验CSS视觉效果，未连接生产API/数据库。

## 可复现运行

```sh
# 使用真实依赖，不stub publisher，不访问DB。
reproduction-latest/api/venv/bin/python audit-published/mapping/presentation/check_presentation.py \
  --repo actions-acceptance \
  --out audit-published/mapping/presentation/presentation-audit.json \
  --render-input /tmp/presentation-render-input.json

# 从实际源码TSX离线转译并React SSR；依赖目录只读，可换成任意已安装当前锁定依赖的node_modules。
node audit-published/mapping/presentation/check_render.cjs \
  actions-acceptance langrensha-cloud/website/web/node_modules \
  /tmp/presentation-render-input.json audit-published/mapping/presentation/render-audit.json
```

运行结果：223局扫描；问题行数：流徽3、重投标签14轮、DQ后推断1、终局后白天12（含下项S22九局）、S23末神1、S22夜终局枪口9、傀儡猎人1；31局真实组件SSR成功。`presentation-audit.json`含每局适用范围、源字段及实际投影；`render-audit.json`含真实组件生成的相关文字和白天区块。报告不把一次脚本成功或既有CI测试通过当作原媒体事实确认，也不重开已定案姓名/照片/未知字段。
