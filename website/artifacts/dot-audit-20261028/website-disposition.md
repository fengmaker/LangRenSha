# S22/S23 网站发布与展示语义处置

日期：2026-10-28
范围：网站 API 发布投影、前端展示、回归及实际联调。实现子任务未直接写库；主代理已完成业务库同步、完整发布、两季悍跳绑定及实际API/浏览器验收。

## 九类问题处置

| 编号 | 处置 | 结果 |
| --- | --- | --- |
| M-01 | 发布保留已确认的 S23 规则默认弃票依据 `rule_default`，不泄露内部说明文字。 | 已修复；BV1gBhn6dE5c 实际 BallotPanel SSR 显示“规则默认”。 |
| M-02 | 按法官最终纠正将BV1iDGK61E1c的票轮赢家更新为10号，与放逐事件一致；保留通用冲突提示保护。 | 已修复；实际桌面/手机页面显示10号安妮，最终源内结果冲突0。 |
| P-01 | 警徽流失使用原因中性的文案，不再推断为延迟竞选被自爆打断。 | 已修复；16 局候选的实际组件 SSR 中未发现错误原因文案。 |
| P-02 | S23 混血规则的末神判断跨轮累计已出局神牌，终局猎人不再出现待开枪问题。 | 已修复；实际局与跨轮夹具通过。 |
| P-03 | 将补充的 DQ/退赛事件以脱敏形式发布，并将 DQ 计入后续存活推断；不推断 DQ 猎人仍可开枪。 | 已修复；审计中 DQ 后猎人推断为 0。 |
| P-04 | 应用有当前 dossier 指纹绑定的终局记录和严格识别的“整天未开始”标记；终局夜事件另列。仅裁去占位日，若之后存在真实投票、登记、插播或日结果则明确报冲突。 | 已修复；审计中终局后白天为 0。仅“未进入 D#放逐/投票”不会被认作整日未开始。 |
| P-05 | `revote` 与旧 `skill_revote` 标签统一显示“技能重投”。 | 已修复；16 局候选 SSR 中“其他投票轮次”标签为 0。 |
| P-06 | 九局 S22 夜终局仅在 flow audit 的 dossier SHA 与当前 dossier 一致时生效；移除未发生的白天及占位票，保留终局夜事实。 | 已修复；九局严格指纹回归通过，终局猎人待核和终局后白天审计均为 0。 |
| P-07 | 猎人已被傀儡禁用时，不再推断待开枪。 | 已修复；回归通过，审计中傀儡猎人待核为 0。 |

## 验证

- 网站测试：`179 passed`。
- React 组件 SSR 夹具：`5 actual component SSR assertions passed`。
- 从离线展示审计候选生成 16 条时间线并用实际 TSX 组件 SSR：错误警徽原因文案、未映射投票轮次文案、待开枪和傀儡待核均为 0。
- TypeScript：使用仓库 Node 24 执行 `website/web/node_modules/typescript/bin/tsc --noEmit` 通过。
- 原始投票总数回归：从正式 `voting.json` 独立汇总票轮和投票明细，与 `load_publication` 结果对照；不使用固定季总数。
- 源事实回归按已核原文更新：S22-B-131-3 通灵反馈为“平民”，7 号底牌仍为“盗宝大师”；S22-A-043-01/02 普通女巫毒 11 号、机械女巫毒 5 号，猎人可开枪。

展示审计命令（PowerShell）：

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe dot-handoff\LangRenSha-S22-S23-audit-3476a56-20261027\audit-published\mapping\presentation\check_presentation.py --repo . --out tmp\dot-audit-presentation-final --render-input tmp\dot-audit-presentation-final-render.json
.tools\node\node-v24.22.1-win-x64\node.exe dot-handoff\LangRenSha-S22-S23-audit-3476a56-20261027\audit-published\mapping\presentation\check_render.cjs . website\web\node_modules tmp\dot-audit-presentation-final-render.json tmp\dot-audit-ssr-final.json
```

离线展示审计的诊断表仍列出 3 条首日 `badge_lost` 候选和 13 条原始 `revote` 阶段记录。这两类是审计器按源事件/阶段输出的复核行；组件 SSR 已分别核实原因文案与用户可见标签。终局、猎人、DQ 类审计行均为 0。

最终映射审计已完成：223局，独立公式差异0、默认弃票依据丢失0、最终票轮结果冲突0。S22源修订的9条反馈与公开终局投影的14条反馈均逐条核对并留痕重绑，原用户决定及成功判定未变。

## 主代理实际集成验收

活动release为`S22_S23-8012409cd1c0e327-ef9d908b-p6-s2`，两季悍跳均绑定此版本。业务库223局逐字段比对0差异；API223局匹配，36个通用桌面/手机页面及14个重点页面通过。

额外修复了S22生成器raw/public投影指纹不一致、终局说明丢失，以及API响应模型过滤终局字段三处相邻问题。分别有全148局指纹回归、实际终局说明回归与响应模型回归；原用户确认S2246条、S232条均保留，悍跳待复核0。

TypeScript和生产构建通过，API/前端已重启。实际验收记录见同目录`publication-acceptance.json`及`targeted-pages/result.json`，主汇总见`data/reports/dot-audit-20261028/README.md`。
