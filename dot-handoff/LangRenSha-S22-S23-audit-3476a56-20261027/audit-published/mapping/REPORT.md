# S22/S23 已存正式字段 → 发布 → API → 展示／统计映射审计

## 结论与边界

已按 `docs/16_字段证据与交叉复核规范.md`、网站README和积分榜字段说明，扫描 **S22 148局、S23 75局，共2676个座位、525个票轮、3813张逐人票**。正式文件与生产代码均未修改；未连接数据库、未推送、未部署。**本报告是当前仓库的离线映射审计，不是对生产URL或原媒体的全面核验。**

发现确实在当前数据触发的9类发布／展示语义差异，涉及33局（S22 18局、S23 15局；分类可重叠；其中1类与S22事实审计共用源内矛盾根因），而不只是代码潜在风险：默认弃票依据被抹掉、技能重投名称漏映射、流徽原因臆定、已终局／已DQ的猎人仍被推断有枪、未开始白天被显示成无人放逐，以及一处源内矛盾原样传到页面。逐局范围见下文及 [展示专项完整报告](presentation/REPORT.md)。不以修展示为由覆盖正式unknown，不把终局无枪窗记为主动不开枪。

**对当前源字段的独立算式对照没有发现积分／胜率等计算差异，但这不证明源事实正确。** S23事实审计另发现 `BV1KaaT67Eca` 混血字段候选错误；若该候选核准，荣耀S23整季积分会从3变为1。这个“公式正确、输入仍可能错”的例子单列在第4节。

基线为 `origin/ci/full-acceptance=3476a56af155f36a0d0050abc1660ed0d6fd538a`；只读工作树 `actions-acceptance` HEAD为 `f31de2b059b54667419c68b12a16c01c76973b07`，与基线除 `dot-handoff/` 外零差异。合并源hash `1c2312637b4dd6b89e365b122e8ef0f7f17e006e9691c5b53051a3c65a827925`，规则hash `805e617180aec9c9999450298da5d435aae1e8fd3298a64dc370f98ad5e445e8`。

## 1. 发布层确定差异

### M-01｜S23两局6票“规则默认弃票”被改标普通弃票

| 对局 | 票轮 | 座位 |
|---|---|---|
| 2026-09-22 第1局 `BV1gBhn6dE5c` | D1 `ballot-2` 放逐 | 12 |
| 2026-10-02 第2局 `BV1UNaQ6kEWR` | D1 `ballot-1` 警徽 | 1、2、7、10、11 |

正式 `voting.json` 已逐票记录 `basis=本轮票权由已核死亡及存活唯一确定；未播报投向按既有用户口径默认弃票`。`publisher.py:135–149` 丢弃源basis，只按 `rule_defaults` 集合重建basis；该集合来自旧式 `data/extractions/{season}/voting/{BV}.json`。S22有148份此旁证，S23当前75局均没有。于是这6票均被重新写成 `basis=abstained`。

`ballot-panel.tsx:16–20,31–34` 只把 `basis=rule_default` 作为默认弃票；实际离线React SSR得到“弃票1人：12号”和“弃票5人：1、2、7、10、11号”，没有“规则默认”。这违背docs16对原文弃票和规则默认弃票分开的要求。

**影响**：当前分子分母不变（现行口径两者都计弃票）；错误是证据等级／来源性质。修复应传递经过确认且经过公开白名单规范化的来源类别，不应重判这6票、不应复制私有路径或完整审计文本进网页。

证据：[逐票源与公开值](default-vote-basis-loss.json)、[真实组件SSR](extra-render-audit.json)。`check_semantic_mapping.py` 可重新发现全6票。

### M-02｜S22源内放逐结果矛盾被原样公开（与S22事实审计共用同一根因）

`2026-07-31 第3局 BV1iDGK61E1c` D2：正式 `voting.ballot-3.winner=2`，同日 `dossier.exile_result.targets=[10]`。发布器保留二者；API不做覆盖；真实 `BallotPanel` SSR直显 **“本轮结果：2号 张小凡”**，同页 `EventBoard` 又按最终事件显示10号被放逐。

S22事实审计已定位原字幕5776349–5778149ms的更正为10号出局。此处只是证明其下游影响，不重复计为第二个事实错误，不以不加权票数自行推翻现场。位置：`publisher.py:33–36,135–149,237–251`，`app.py:408–414`，`ballot-panel.tsx:28`，`event-board.tsx:57`。

全223局对“同日同类最后一轮明确winner”与最终放逐／当选事件的交叉检查，只发现这1处冲突。另99处最后票轮winner为空但最终事件明确：**空值仅使票卡不显示本轮结果，不等于无人出局；不列为错误**。见 [逐局结果交叉表](vote-result-crosscheck.json)。

## 2. 展示推导层确定差异

完整逐局清单、代码行、原字段、推导结果、SSR文字，以及S22/S23事实审计交叉证据见 [presentation/REPORT.md](presentation/REPORT.md)。关键类别：

- `badge_lost` 被一概解释为“延期竞选再次自爆”，误伤S23首日双平票和全员上警的3局。
- S23末神猎人、以及S22已有本季夜间终局定案的相关局，展示程序仍制造“具备开枪资格、枪口请复核”；不能把这种程序生成疑问转交用户重判。
- S23 `BV1BmpB6PE2C` DQ已在正式supplemental中，但公开投影不读取；已DQ的8号猎人N3–N5仍被展示可开枪。
- 有明确“未进入D3／D4”等终局边界的局仍显示该白天和“本日无人被放逐”；“未举行这个阶段”不等于“该阶段举行但无人出局”。
- S22 `BV12pNo6HEuV` 的6号猎人首夜已明确被选傀儡、技能失效，D4展示却再次制造资格／枪口待核。
- 正式 `stage=revote` 在前端被漏映射，S22 7局8轮、S23 6局6轮显示“其他投票轮次”而非技能重投。没有错写成PK，但类别丢失。

特别排除两种误报：`BV1vgpm6nEz6` 的两条ballot.result未公开，但半票/定序王子重投说明仍在dossier事件且实际SSR可见；不能声称解释全部丢失。`BV1U3p86dEHL` 的“D2未开始放逐”只否定放逐，不是否定白天。

## 3. 已执行的字段／统计核对与正确保留的语义

[per-game-index.json](per-game-index.json) 汇总223局的适用检查和具体差异分类；[semantic-checks.json](semantic-checks.json) 有每局源文件hash、票轮和座位数、逐项检查；此处只总结结果，不把程序一致性当原媒体事实。

| 范围 | 实际核对结果 |
|---|---|
| 身份、姓名、学习目标／结果 | 2676个座位由正式dossier到公开快照一致；实际role没有被学习角色或个人阵营覆盖 |
| 个人阵营 | 既有非null阵营原样保留；8个S22混血null由唯一榜样推导，API标faction_inferred并追加说明；不是8条源错误 |
| 日期、局次、阶段、整局胜方 | 223局公开值与正式字段一致；未按投稿日另推比赛日；原源本身是否正确由事实审计处理 |
| 票轮／票权 | 525轮逐票voter/target/state、eligibility和候选字段保留；3813张记录票均在各自已录eligible名单，无同轮重复voter；不是逐时存活的媒体证明 |
| 票重 | 人员分组显示“人”，投票比例计张数，不将警长半票加进“投狼次数”；不擅自扩展S22未计半票归档口径。S23绑票理论票力及现场结果必须另区分 |
| 终局源字段 | endgame六个公开业务字段保留；evidence本来不在公开白名单，不能据此断言证据丢失；展示终局边界另见上文差异 |
| 整季／决赛周 | 代码按范围切积分，其余指标仍整季；没有将冠军榜的场次替换为其他指标分母 |
| 比例未知 | 现有223局整局胜方均good/werewolf；有效个人阵营也全可确定。当前数据没有未决胜负样本，不可据此宣称已实测所有未知情形；选定既有单元测试覆盖unknown/null排除，47 passed |
| 副作用 | 运行纯函数前后公开输入深比较一致；未打开DB连接、未写源文件 |

### 3.1 不应“修复”的8个混血源null

`analytics.py:48–86` 只在源阵营缺失、榜样唯一、榜样阵营已知且阵营事件不冲突时推导；`app.py:214–228` 公开有效阵营并说明推导。下列均有正式N1 choose事件；完整事件留在 `semantic-checks.json.derived_mixed_blood_factions`。

| 日期/BV | 混血座位／姓名 | 明确榜样 | 有效阵营 |
|---|---|---|---|
| 07-31 BV1iDGK61EYt | 3 徐言雨 | 9 | good |
| 08-04 BV1q9MB6FEhU | 6 KS | 5 | good |
| 08-13 BV1GXgW6HEmA | 11 贝拉酱 | 12 | good |
| 08-14 BV1PigN6nEjA | 9 彭彭 | 3 | good |
| 08-18 BV1dc836KEjJ | 10 陈明峻 | 6 | werewolf |
| 08-19 BV1tj8p6REqy | 9 董鲸鱼 | 3 | good |
| 08-20 BV1kG8A6dEfF | 9 荣耀 | 5 | werewolf |
| 08-21 BV1jM8B6jE2i | 9 董鲸鱼 | 7 | werewolf |

### 3.2 独立公式重算

以正式dossier/voting为输入，另写逐人累计器，不调用analytics内部累计函数作为期望值，比较113个“赛季×选手”的积分、胜负、狼人场次、弃票，以及10类比例分子分母/比率；**算式对照差异0**。这不是对正式输入的背书。

| 当前正式数据口径 | S22 | S23 |
|---|---:|---:|
| 出场 | 1776 | 900 |
| 个人胜／负 | 945 / 831 | 497 / 403 |
| 有效狼人阵营出场 | 611 | 311 |
| 其中物理狼人（悍跳适用） | 586 | 300 |
| 狼混（算狼人指标，不算悍跳底牌） | 25 | 11 |
| 好人投狼分子／分母 | 949 / 1373 | 486 / 652 |
| 好人站边分子／分母 | 458 / 634 | 247 / 355 |
| 警徽正确分子／分母 | 229 / 342 | 124 / 196 |
| 已识别悍跳／成功 | 121 / 46 | 82 / 24 |

悍跳发布输入精确覆盖全部223局和886个物理狼人座位，姓名／底牌／来源指纹匹配；当前203次识别等于203个唯一“人×局”，没有重复计数，成功结果当前均可判定。延期D2起跳 `BV1fPKY6gEFp:5` 与D3起跳 `BV15PaW66EjW:9` 均未倒用首日放逐，成功false。2026-10-09第3局用户最新结论仍为6号yes、10号遗言起跳no，均标user_confirmed；未被历史待核说明覆盖。三项技能正确率仍留空。

## 4. S23事实候选的条件性影响（不是已执行修复）

S23事实审计提出 `2026-09-24 第1局 BV1KaaT67Eca` 的4号荣耀混血，榜样应为8号狼人而非当前12号，个人阵营应werewolf而非good。这里未独立回听媒体，以其证据审计最终状态为准。

网站没有在另一层自动纠正：源非null阵营优先，公开/API仍good。**仅在内存**替换这两个候选字段、整局winner仍good，真实公开器/analytics重算得到：

- 荣耀该局个人胜+1 → 个人负−1；S23整季积分3 → 1，胜19 → 18，负18 → 19。
- 当前整季积分名次并列21 → 并列30；其他12名选手仅名次随之变化，不改变各自指标。
- 荣耀狼人场次14 → 15，总胜率19/37 → 18/37；投狼20/25 → 20/24，站边11/14 → 11/13，警徽正确11/11 → 10/10；具体分子分母见JSON。
- 无他人投向4号，因此此次条件性变更未改变其他选手投狼指标。4号仍是混血底牌，不加入物理狼人悍跳统计；当前悍跳判断及成功结果不变。

可复现脚本 `check_candidate_impact.py` 与 `candidate-BV1KaaT67Eca-impact.json` 明确标为COUNTERFACTUAL。它不修改正式数据、不是批准修改，也不代表候选已被用户接受。任何实际修复后仍需重新发布全活动赛季并重新同步悍跳绑定，不能复用旧release的上线声明。

另一个S23事实候选 `2026-09-10 第4局 BV12sY36hEdr`：当前公开层确实保留D1 `night_deaths=peaceful`，以及D3 `ballot-2` 中12号大卫（平民good）有票权且投11；API和展示没有隐藏修正。S23事实审计指出原字幕有D1 12号倒牌的强矛盾，媒体结论由其单独交付；此处仅存 [当前传播证据](candidate-BV12sY36hEdr-propagation.json)，不删票、不推定替代票，也不把此候选计入上述33局已确认映射问题。

## 5. 复现、文件与限制

使用实际既有依赖环境 `reproduction-latest/api/venv/bin/python`（psycopg3.3.6）。最终脚本**没有stub或删导入**。

```sh
PYTHONDONTWRITEBYTECODE=1 reproduction-latest/api/venv/bin/python \
  audit-published/mapping/check_semantic_mapping.py --root actions-acceptance \
  --output audit-published/mapping/semantic-checks.json \
  --render-input /tmp/mapping-extra-render-input.json
node audit-published/mapping/check_mapping_render.cjs \
  actions-acceptance langrensha-cloud/website/web/node_modules \
  /tmp/mapping-extra-render-input.json audit-published/mapping/extra-render-audit.json
PYTHONDONTWRITEBYTECODE=1 reproduction-latest/api/venv/bin/python \
  audit-published/mapping/check_candidate_impact.py --root actions-acceptance \
  --output audit-published/mapping/candidate-BV1KaaT67Eca-impact.json
# 展示扫描及实际组件SSR命令详见 presentation/REPORT.md。
# 单元回归必须从repo根执行；曾从工作区根尝试导致导入失败，已保留日志并在正确cwd重跑。
(cd actions-acceptance && PYTHONDONTWRITEBYTECODE=1 \
  ../reproduction-latest/api/venv/bin/python -m pytest -p no:cacheprovider \
  website/tests/test_analytics.py website/tests/test_bluffs.py \
  website/tests/test_s23_bluff_publication.py website/tests/test_s23_public_semantics.py -q)
```

- `semantic-checks.json`：223局保真/公式覆盖、8个混血派生、默认票依据丢失、源内结果矛盾。
- `presentation/REPORT.md` / 两个脚本 / 两份JSON：展示专项逐局证据、真实TSX离线SSR。
- `extra-render-audit.json`：本报告M-01/M-02三局的真实票卡SSR文本。
- `candidate-BV1KaaT67Eca-impact.json`：条件性重算，不改源。
- `focused-pytest.log`：47 passed；原错误cwd尝试另存 `focused-pytest-wrong-cwd.log`，不是测试失败或已覆盖线上。

离线SSR验证实际React组件产生的文字和区块，但没跑Next服务、浏览器视觉/交互或生产API；实际数据库人物ID绑定亦未访问。脚本以姓名作稳定本地ID，不重新裁定既有姓名／照片映射。已有CI162 passed不能替代上述语义差异，也不能把新的脚本通过称为媒体全部真实或网站线上已核验。用户最新指示是先在dot云端工作区保存；本报告未推送GitHub。
