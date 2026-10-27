# S23 悍跳证据来源重绑审计（2026-10-28）

## 处理结论

`build_s23_bluff_publication.py --check` 因5条独立复核记录绑定的 `dossier.json` SHA-256 过期而失败。与更新前 ZIP 内旧 dossier 和旧 parts 记录逐条对照后，只在 `data/extractions/S23/bluff_review/parts/audit_b.json` 更新这5条记录的 `source_sha256`。独立判断、姓名、物理身份、所跳身份、起跳日、原始字幕/截图证据定位均未改；`user_confirmed.json` 与原始用户反馈文件无需更新。

全体结论保持：75局、300个狼人出场，82 yes、218 no、0 uncertain，24次成功；构建器检查通过且 `written=false`。没有更改资产、网站或数据库。

## 更新前后文件绑定

| 对局 | 审计全文来源 | 旧 SHA-256 | 新 SHA-256 |
|---|---|---|---|
| BV1MneS6kEWz | `data/games/S23/2026-09-18_g03_BV1MneS6kEWz/dossier.json` | `5700d32bf6825c1a7a4515bfb2a68452b3264b3224ce127307eef9f15541d9a3` | `de1690023e4e4f4148830d16b7dd21ba28ea8e61dc6d9d1c2382433618a2a6a1` |
| BV18Bhn6dEJ6 | `data/games/S23/2026-09-22_g02_BV18Bhn6dEJ6/dossier.json` | `0bf974f4cb6e86ef9fa1b15ed83af7d07140b4363276d8cb3c6853646949b2ba` | `c2ed4f67b0f4d6e3702dc67687d5e7c30f4e77942da2bcf2bea9a74d45a1dda7` |
| BV1KaaT67Eca | `data/games/S23/2026-09-24_g01_BV1KaaT67Eca/dossier.json` | `623d900d5f5561f61af8d83f5aa3031d44e35c1018d4a98232286a40ec0d8f11` | `52c767634e90acb48a8069f2315aafc854eace76039d5322b451a6c0f309c2d1` |
| BV1KBhU68EjA | `data/games/S23/2026-09-25_g02_BV1KBhU68EjA/dossier.json` | `124ef8e7c43ac01d00803621cb33496753ef3fcda7f6e2ec655b1e4b4d0cedc4` | `62cd29aa08c105e33d4afe240248314b4d5825015fd78562eb5c2bcbf3120a27` |
| BV1saaT6jEyK | `data/games/S23/2026-09-24_g02_BV1saaT6jEyK/dossier.json` | `782410e35ddd63fd5d4239f8ca1985acbe720fcf34abef57f7b67d204f1715ab` | `90ce330210787b02dd7e5d13783866cc3aaad501f2e17686e06ccfe183af9bd3` |

完整原 audit 记录与重绑后记录、原始证据定位及逐项 hash 校验保存在同目录 JSON 的 `rebindings[].old_audit_record`、`current_audit_record`、`source_evidence_revalidation.evidence`。

## 逐局 dossier 差异与结论核查

### BV1MneS6kEWz（2026-09-18 第3局）

源文件：`data/games/S23/2026-09-18_g03_BV1MneS6kEWz/dossier.json`，SHA `5700d32bf6825c1a7a4515bfb2a68452b3264b3224ce127307eef9f15541d9a3` → `de1690023e4e4f4148830d16b7dd21ba28ea8e61dc6d9d1c2382433618a2a6a1`。旧 audit 记录除该 SHA 外与当前逐字节解析后完全相同。

| dossier 字段 | 旧值 | 新值 |
|---|---|---|
| `rounds[3].night[0].action（第4轮night · guard · action）` | `"guard"` | `"unavailable"` |
| `rounds[3].night[0].availability（第4轮night · guard · availability）` | `null` | `"dead"` |
| `rounds[3].night[0].result（第4轮night · guard · result）` | `null` | `"守卫3号已于N3出局，N4无法执行守护。"` |
| `rounds[3].night[0].targets（第4轮night · guard · targets）` | `[1]` | `[]` |

**悍跳审计记录（改前/改后相同）：**

2号 徐言雨（狼人）：yes / 通灵师 / day=1; 5号 耿许儿（狼人）：no / 未自称 / day=None; 9号 董鲸鱼（狼人）：no / 未自称 / day=None; 11号 宝玉妹妹（机械狼）：no / 未自称 / day=None

- 独立判断评估数：4；姓名、物理身份、yes/no、claimed_role、claim_day 和 decision_note 保持原样。
- 关联转写/截图证据：12项；当前文件全部命中旧 audit 记录的 SHA-256（0 mismatch）。

**为何可只更新来源绑定：** 上表变化仅涉及夜间守卫行动、夜死汇总、混血榜样/阵营或预言家反馈规范化，未改变该局的物理狼名单与任何被审玩家的自称证据、姓名、物理角色或起跳日。BV1KaaT67Eca 的 seat 4 变化为混血儿阵营，物理角色仍为混血儿，且不属于悍跳审计里的物理狼人座位。独立审计中的证据摘录、时间范围、帧文件与SHA全部原样保留。

### BV18Bhn6dEJ6（2026-09-22 第2局）

源文件：`data/games/S23/2026-09-22_g02_BV18Bhn6dEJ6/dossier.json`，SHA `0bf974f4cb6e86ef9fa1b15ed83af7d07140b4363276d8cb3c6853646949b2ba` → `c2ed4f67b0f4d6e3702dc67687d5e7c30f4e77942da2bcf2bea9a74d45a1dda7`。旧 audit 记录除该 SHA 外与当前逐字节解析后完全相同。

| dossier 字段 | 旧值 | 新值 |
|---|---|---|
| `rounds[1].day[3].result（第2轮day · night_deaths · result）` | `"一号自刀、6号狼人被女巫毒杀，双死"` | `"N2狼队1号自刀、毒杀6号；1号与6号双死。"` |
| `rounds[1].day[3].targets（第2轮day · night_deaths · targets）` | `[6]` | `[1,6]` |

**悍跳审计记录（改前/改后相同）：**

1号 郭小炜（狼人）：no / 未自称 / day=None; 6号 陈俊洁（狼人）：no / 未自称 / day=None; 8号 华仔仔（狼人）：yes / 预言家 / day=1; 11号 宝玉妹妹（诡术师）：no / 未自称 / day=None

- 独立判断评估数：4；姓名、物理身份、yes/no、claimed_role、claim_day 和 decision_note 保持原样。
- 关联转写/截图证据：9项；当前文件全部命中旧 audit 记录的 SHA-256（0 mismatch）。

**为何可只更新来源绑定：** 上表变化仅涉及夜间守卫行动、夜死汇总、混血榜样/阵营或预言家反馈规范化，未改变该局的物理狼名单与任何被审玩家的自称证据、姓名、物理角色或起跳日。BV1KaaT67Eca 的 seat 4 变化为混血儿阵营，物理角色仍为混血儿，且不属于悍跳审计里的物理狼人座位。独立审计中的证据摘录、时间范围、帧文件与SHA全部原样保留。

### BV1KaaT67Eca（2026-09-24 第1局）

源文件：`data/games/S23/2026-09-24_g01_BV1KaaT67Eca/dossier.json`，SHA `623d900d5f5561f61af8d83f5aa3031d44e35c1018d4a98232286a40ec0d8f11` → `52c767634e90acb48a8069f2315aafc854eace76039d5322b451a6c0f309c2d1`。旧 audit 记录除该 SHA 外与当前逐字节解析后完全相同。

| dossier 字段 | 旧值 | 新值 |
|---|---|---|
| `rounds[0].night[0].targets[0]（第1轮night · mixed_blood_model · targets[0]）` | `12` | `8` |
| `rounds[0].night[4].result（第1轮night · seer_check · result）` | `"白神"` | `"好人"` |
| `seats[3].faction（座位4 · faction）` | `"good"` | `"werewolf"` |

**悍跳审计记录（改前/改后相同）：**

1号 蛋黄派（狼人）：yes / 预言家 / day=1; 3号 李斯（狼人）：no / 未自称 / day=None; 8号 牛肉干（狼人）：no / 未自称 / day=None; 10号 陈明峻（狼人）：no / 未自称 / day=None

- 独立判断评估数：4；姓名、物理身份、yes/no、claimed_role、claim_day 和 decision_note 保持原样。
- 关联转写/截图证据：7项；当前文件全部命中旧 audit 记录的 SHA-256（0 mismatch）。

**为何可只更新来源绑定：** 上表变化仅涉及夜间守卫行动、夜死汇总、混血榜样/阵营或预言家反馈规范化，未改变该局的物理狼名单与任何被审玩家的自称证据、姓名、物理角色或起跳日。BV1KaaT67Eca 的 seat 4 变化为混血儿阵营，物理角色仍为混血儿，且不属于悍跳审计里的物理狼人座位。独立审计中的证据摘录、时间范围、帧文件与SHA全部原样保留。

### BV1KBhU68EjA（2026-09-25 第2局）

源文件：`data/games/S23/2026-09-25_g02_BV1KBhU68EjA/dossier.json`，SHA `124ef8e7c43ac01d00803621cb33496753ef3fcda7f6e2ec655b1e4b4d0cedc4` → `62cd29aa08c105e33d4afe240248314b4d5825015fd78562eb5c2bcbf3120a27`。旧 audit 记录除该 SHA 外与当前逐字节解析后完全相同。

| dossier 字段 | 旧值 | 新值 |
|---|---|---|
| `rounds[1].night[3].result（第2轮night · seer_check · result）` | `"平民"` | `"好人"` |
| `rounds[2].day[3].targets（第3轮day · night_deaths · targets）` | `[9]` | `[9,12]` |

**悍跳审计记录（改前/改后相同）：**

5号 耿许儿（狼人）：no / 未自称 / day=None; 6号 KS（狼人）：yes / 预言家 / day=1; 7号 小苍（狼人）：no / 未自称 / day=None; 11号 冰辰（假面）：no / 未自称 / day=None

- 独立判断评估数：4；姓名、物理身份、yes/no、claimed_role、claim_day 和 decision_note 保持原样。
- 关联转写/截图证据：11项；当前文件全部命中旧 audit 记录的 SHA-256（0 mismatch）。

**为何可只更新来源绑定：** 上表变化仅涉及夜间守卫行动、夜死汇总、混血榜样/阵营或预言家反馈规范化，未改变该局的物理狼名单与任何被审玩家的自称证据、姓名、物理角色或起跳日。BV1KaaT67Eca 的 seat 4 变化为混血儿阵营，物理角色仍为混血儿，且不属于悍跳审计里的物理狼人座位。独立审计中的证据摘录、时间范围、帧文件与SHA全部原样保留。

### BV1saaT6jEyK（2026-09-24 第2局）

源文件：`data/games/S23/2026-09-24_g02_BV1saaT6jEyK/dossier.json`，SHA `782410e35ddd63fd5d4239f8ca1985acbe720fcf34abef57f7b67d204f1715ab` → `90ce330210787b02dd7e5d13783866cc3aaad501f2e17686e06ccfe183af9bd3`。旧 audit 记录除该 SHA 外与当前逐字节解析后完全相同。

| dossier 字段 | 旧值 | 新值 |
|---|---|---|
| `rounds[0].night[4].result（第1轮night · seer_check · result）` | `"平民"` | `"好人"` |
| `rounds[2].night[4].result（第3轮night · seer_check · result）` | `"平民"` | `"好人"` |

**悍跳审计记录（改前/改后相同）：**

4号 荣耀（狼人）：yes / 预言家 / day=1; 6号 KS（狼人）：yes / 预言家 / day=1; 8号 牛肉干（狼人）：no / 未自称 / day=None; 9号 小苍（九尾狐）：no / 未自称 / day=None

- 独立判断评估数：4；姓名、物理身份、yes/no、claimed_role、claim_day 和 decision_note 保持原样。
- 关联转写/截图证据：13项；当前文件全部命中旧 audit 记录的 SHA-256（0 mismatch）。

**为何可只更新来源绑定：** 上表变化仅涉及夜间守卫行动、夜死汇总、混血榜样/阵营或预言家反馈规范化，未改变该局的物理狼名单与任何被审玩家的自称证据、姓名、物理角色或起跳日。BV1KaaT67Eca 的 seat 4 变化为混血儿阵营，物理角色仍为混血儿，且不属于悍跳审计里的物理狼人座位。独立审计中的证据摘录、时间范围、帧文件与SHA全部原样保留。

## 用户定案和 source_fingerprint

更新前活动 release `S22_S23-1c2312637b4dd6b8-805e6171-p4-s2` 的p4 snapshot与当前p5公开源逐局对照，5局 `source_fingerprint` 全部相同。10号用户反馈旧/new fingerprint、`user_confirmed.json` 中fingerprint和 `user_feedback_20261026_eulogy.json` 中fingerprint均为 `a95a25d92303f530fab33ee70dba2daa2533c7fe3ade1a5ef582706be89ad085`；两反馈文件的SHA也与备份内旧文件一致，因此没有重写或失配。

- 6号：BV1U3p86dEJY，day 1 通灵师悍跳，`yes` / `user_confirmed`；`audit_c.json` 的旧记录和当前记录完全相同。
- 10号：同局遗言自称通灵师，用户已确认不计悍跳，`no`；反馈原文和结论保留。
- 不要求用户重新确认，也不把既有确认降级或改写。

## 最终发布检查

```powershell
.venv\Scripts\python.exe scripts/build_s23_bluff_publication.py --check
```

| 检查项 | 结果 |
|---|---|
| 状态 | 通过 |
| 对局数 | 75 |
| 狼人出场 | 300 |
| yes | 82 |
| no | 218 |
| uncertain | 0 |
| 成功悍跳 | 24 |
| 待复核 | 0 |
| 用户确认记录 | 2 |
| asset写入 | False |
| 发布 | False |

该检查只验证当前发布输入与asset，不写asset；asset构建和发布仍由主代理负责。

## 证据边界与改动范围

旧 source ZIP 保存了5条旧 `dossier.json` 和5条旧独立审计记录及其原始证据哈希元数据，但不包含这些字幕和bluff截图原件。本次读取旧记录里的原始SHA定位，再核对当前字幕/截图文件；52项均匹配，未改其中任何证据文件。

本次唯一业务旁证改动：`data/extractions/S23/bluff_review/parts/audit_b.json` 中5个全文来源SHA。`data/extractions/S23/bluff_review/user_confirmed.json`、`user_feedback_20261026_eulogy.json`、dossier、截图、原字幕和网站asset均未改。
