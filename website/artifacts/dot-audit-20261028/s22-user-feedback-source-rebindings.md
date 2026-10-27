# S22 用户确认悍跳反馈的来源指纹重绑定

日期：2026-10-28。只更新 `data/extractions/S22/bluff_review/user_confirmed.json` 中既有记录的 `source_fingerprint`，没有改动任何 yes/no、claim_day、claimed_role、notes 或原始表单值；未写数据库，未写正式悍跳 asset，未发布。

## 总结

- 对照发现并重绑 **9** 条失配记录，覆盖 5 局。原始反馈完整对象逐条保存在 `source_rebindings[review_id].original_feedback`，旧指纹、新指纹、证据与语义差异一并留痕。
- 原决定保持不变：5 条 yes、4 条 no；改动决定数为 0。
- 9 条旧指纹均同时匹配 `source-before.zip` 的旧 dossier/voting、不可变旧 public snapshot，以及旧 `website/assets/bluffs/S22.json` 中已发布的绑定。
- 九条记录的姓名、物理底牌和 seat 均与当前源一致。旧 part/recheck 证据 JSON 的 SHA 与当前相同；每条旧证据的来源文件 SHA 与固定 S22 `evidence_registry.json` 记录相同，摘录在当前文件对应时间窗内逐字匹配。
- 源差异仅在 5 局的 `voting.ballots`；所有变更 ballot 的赢家不变，dossier 日结果事件与 voting day 状态不变。
- 按既有成功规则复算旧发布中 5 条相关 yes：变化 **0** 条；旧有 46 次成功保持 46。
- 实际 `--check` 结果恢复旧摘要：121 次 yes、46 次成功、46 条用户确认、0 项待复核。

## 逐条绑定

| 反馈编号 | 结论 | 原指纹 → 新指纹 | 受影响投票轮 | 成功判定 |
| --- | --- | --- | --- | --- |
| `BV1BPNB6QE1V:10` | yes | `b8dd157baff2` → `3db6b1c03d25` | D1 ballot-2赢家7→7 | True→True（不变） |
| `BV1BPNB6QE1V:6` | no | `b8dd157baff2` → `3db6b1c03d25` | D1 ballot-2赢家7→7 | 不适用 |
| `BV1PEN863EXG:5` | yes | `d936ddbf0a0f` → `df9c28dcaf97` | D3 ballot-2赢家2→2 | False→False（不变） |
| `BV1YxNH6YEqY:3` | no | `28fd20837225` → `9b7d57b4c589` | D4 ballot-2赢家None→None | 不适用 |
| `BV1YxNH6YEqY:8` | yes | `28fd20837225` → `9b7d57b4c589` | D4 ballot-2赢家None→None | False→False（不变） |
| `BV1iDGK61E2z:5` | yes | `7ee2e212028f` → `fb40b77dcce0` | D1 ballot-2赢家None→None | False→False（不变） |
| `BV1iDGK61E2z:6` | no | `7ee2e212028f` → `fb40b77dcce0` | D1 ballot-2赢家None→None | 不适用 |
| `BV1zX7C6qEmR:10` | yes | `bdc025faecdd` → `c0dac00d911f` | D3 ballot-1赢家3→3 | False→False（不变） |
| `BV1zX7C6qEmR:12` | no | `bdc025faecdd` → `c0dac00d911f` | D3 ballot-1赢家3→3 | 不适用 |

## 核对边界

`source-before.zip` 不含大体积字幕、转写、音频或截图字节。本次没有声称从 ZIP 校验过这些字节；旧评估实际引用的 6 个不同源文件由固定审计包 `audit-published/S22/evidence_registry.json` 提供更新前 SHA-256，6/6 与当前文件一致，旧引用文字/时间戳也全部通过现行证据定位校验。对应 part/recheck JSON 本身则可从 ZIP 直接逐字节校验且与当前文件一致。

## 验证

```powershell
.\.venv\Scripts\python.exe scripts\build_bluff_inference.py --check
```

该只读检查恢复旧发布摘要：121 yes、46 successful、46 条用户确认、0 pending，证据问题 0、未重核候选 0。正式 `website/assets/bluffs/S22.json` 尚未由本任务写入；待主代理执行 builder 与发布后再做完整映射审计。
