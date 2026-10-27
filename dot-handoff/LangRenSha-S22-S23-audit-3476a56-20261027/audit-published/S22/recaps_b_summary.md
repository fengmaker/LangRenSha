# S22 后74局复盘字段审计

固定基线 `3476a56af155f36a0d0050abc1660ed0d6fd538a`；74局连续复盘机器文本对照，原音/原视频直接核验0局。
新增候选字段 30 项，涉及 20 局；9项已派生覆盖不计新问题（8局混血阵营、1局夜死）。

## 最高优先级

- BV1Abgy6tEP8：第2夜女巫毒8，但夜死字段peaceful[]，game_flow仍列8存活，terminal=null。
- BV12Mur6nEns：第2夜女巫毒5，但夜死peaceful[]，game_flow仍列5存活，terminal=null。
- BV1DFM26ME2o：女巫毒11错写第3夜；原始复盘和已接受终局都指向第4夜。
- BV1xm3J6wEbr：通灵师查盗宝7应反馈猎人，正式result为盗宝大师。
- BV1jYKV6SEwK/BV1fPKY6gEFp/BV1tj8p6RE2h：假面查询的在/不在舞池反馈混入角色名。
- BV1oXMB6fEQ4：第2夜原刀写9而复盘与死亡播报均指3；终局day3与第4天放逐12冲突。

以上都是只读候选，不直接改动已有事实。5个重点已回读原始字幕/ASR时间窗并固化SHA，见top_b_primary_text_windows.json；不能称为原音直接复核。

## 逐局覆盖与新增候选

|局ID|新增候选数|结论|
|---|---:|---|
|bili-BV1WEN86gE1i-p01-g03|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1WEN86gERp-p01-g04|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1BPNB6QE1s-p01-g01|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1BPNB6QE1V-p01-g02|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1BPNB6QE4z-p01-g03|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1jYKV6SETU-p01-g01|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1jYKV6SEwK-p01-g02|1|发现明确原字段候选差异或已有推导未同步项|
|bili-BV1dYKV6UEYM-p01-g03|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV12pNo6HEtA-p01-g01|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV12pNo6HEuV-p01-g02|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV12pNo6HEiz-p01-g03|2|发现明确原字段候选差异或已有推导未同步项|
|bili-BV1oNKY6zE1Z-p01-g01|1|发现明确原字段候选差异或已有推导未同步项|
|bili-BV1fPKY6gEFp-p01-g02|2|发现明确原字段候选差异或已有推导未同步项|
|bili-BV1bWKY6tEri-p01-g03|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1Pxgy68EQC-p01-g01|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1Nsgy6cEiG-p01-g02|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1Abgy6tEP8-p01-gunknown|1|发现明确原字段候选差异或已有推导未同步项|
|bili-BV1RGgx6xEun-p01-g01|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV19Ggx6xEqE-p01-g02|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1RGgx6xEP9-p01-g03|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1iMgq6ZE5t-p01-g01|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1iMgq6ZEtz-p01-g02|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1iMgq6ZEWn-p01-g03|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1mE3z6XEB1-p01-g01|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1h33z6tEqx-p01-g02|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV13g3z6FEdh-p01-g03|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV12m3J6wE3m-p01-g01|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1xm3J6wEbr-p01-g02|2|发现明确原字段候选差异或已有推导未同步项|
|bili-BV1413J6YEh2-p01-g03|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1hQ3t6hEbS-p01-g01|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1aQ3t6hEcU-p01-g02|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1aQ3t6hEcB-p01-g03|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1iDGK61EYt-p01-g01|1|发现明确原字段候选差异或已有推导未同步项|
|bili-BV1iDGK61E2z-p01-g02|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1iDGK61E1c-p01-g03|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1q9MB6FEhU-p01-g01|0|已知主要字段在连续复盘文本范围内未见新增明确冲突；已有派生覆盖保留，不建议重开|
|bili-BV179MB6FE36-p01-g02|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV179MB6FEne-p01-g03|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1oXMB6fEQ4-p01-g04|2|发现明确原字段候选差异或已有推导未同步项|
|bili-BV1DFM26ME2R-p01-g01|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1hFM26ME7o-p01-g02|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1DFM26MEWR-p01-g03|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1DFM26ME2o-p01-g04|1|发现明确原字段候选差异或已有推导未同步项|
|bili-BV1TDun6wEqw-p01-g01|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1mDun6wEhp-p01-g02|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1mDun6wE3m-p01-g03|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1pSuN62EoT-p01-g01|1|发现明确原字段候选差异或已有推导未同步项|
|bili-BV1pSuN62Ekr-p01-g02|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1CSuN62Ee2-p01-g03|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1CSuN62Eey-p01-g04|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV11Mur6nEZb-p01-g01|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1KMur6HE7b-p01-g02|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV12Mur6nEns-p01-g03|1|发现明确原字段候选差异或已有推导未同步项|
|bili-BV1JNgj6gEty-p01-g01|1|发现明确原字段候选差异或已有推导未同步项|
|bili-BV1JNgj6gEaf-p01-g02|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1JNgj6gEta-p01-g03|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1GXgW6HEmA-p01-g01|0|已知主要字段在连续复盘文本范围内未见新增明确冲突；已有派生覆盖保留，不建议重开|
|bili-BV1aXgW6nE6E-p01-g02|3|发现明确原字段候选差异或已有推导未同步项|
|bili-BV1XXgW6nEZ5-p01-g03|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1PigN6nEjA-p01-g01|0|已知主要字段在连续复盘文本范围内未见新增明确冲突；已有派生覆盖保留，不建议重开|
|bili-BV1yigN6JE5Y-p01-g02|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1WigN6JEVS-p01-g03|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1dc836KEjJ-p01-g01|1|发现明确原字段候选差异或已有推导未同步项|
|bili-BV1jc836TEt1-p01-g02|1|发现明确原字段候选差异或已有推导未同步项|
|bili-BV17f8g6BEFQ-p01-g03|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1tj8p6REqy-p01-g01|2|发现明确原字段候选差异或已有推导未同步项|
|bili-BV1tj8p6RE2h-p01-g02|3|发现明确原字段候选差异或已有推导未同步项|
|bili-BV1tj8p6RE1V-p01-g03|2|发现明确原字段候选差异或已有推导未同步项|
|bili-BV1kG8A6dEfF-p01-g01|0|已知主要字段在连续复盘文本范围内未见新增明确冲突；已有派生覆盖保留，不建议重开|
|bili-BV1kG8A6dEye-p01-g02|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1kG8A6dE7A-p01-g03|0|连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实|
|bili-BV1jM8B6jE2i-p01-g01|0|已知主要字段在连续复盘文本范围内未见新增明确冲突；已有派生覆盖保留，不建议重开|
|bili-BV1jM8B6jEkF-p01-g02|1|发现明确原字段候选差异或已有推导未同步项|
|bili-BV18W8B6KE7C-p01-g03|1|发现明确原字段候选差异或已有推导未同步项|

## 具体字段

|局ID|字段|候选|结论|
|---|---|---|---|
|bili-BV1jYKV6SEwK-p01-g02|R2.night.masquerade_verify.result|{"result": "不在舞池"}|假面查询的是目标是否在舞池，原始字幕明确12号平民不在舞池；正式result=假面混入角色名。|
|bili-BV12pNo6HEiz-p01-g03|R1.day.badge|{"action": "unknown", "targets": [], "note": "删除首日重复移交；保留R2的6→11"}|6号首日当选、次夜中刀后才移交11；正式首日另记actor=null的移交11，和R2移交重复。既有AI回答也明确移交在第二夜死亡之后。|
|bili-BV12pNo6HEiz-p01-g03|R3.night.wolf_attack / mechanical_action|{"wolf_attack": {"action": "attack", "actor": 9, "targets": [1]}, "mechanical_action": {"action": "pass", "targets": []}}|复盘把小刀击杀1与破盾技能刀通过分开；正式把杀1填入机械技能槽且普通刀unknown，疑似普通刀/技能刀混淆。需结合本季槽位契约确认，不改变死者。|
|bili-BV1oNKY6zE1Z-p01-g01|R2.night.seer_check|{"action": "check", "actor": 7, "targets": [11], "result": "狼人"}|连续复盘明确第二夜预言家验证11号狼人，正式该槽仍unknown。|
|bili-BV1fPKY6gEFp-p01-g02|R2.night.masquerade_verify.result|{"result": "不在舞池"}|原始转写明确假面验1号舞者不在舞池，正式result却为假面。|
|bili-BV1fPKY6gEFp-p01-g02|R3.night.masquerade_verify|{"action": "verify", "actor": 4, "targets": [12], "result": "在舞池"}|复盘连续说12号平民在舞池并给12扣面具；正式查验槽unknown。|
|bili-BV1Abgy6tEP8-p01-gunknown|R2.day.night_deaths|{"action": "die", "targets": [8]}|守5挡狼刀只说明狼刀未杀人，同夜女巫毒8；正式却记整夜peaceful[]，导致game_flow仍列8存活且terminal=null。已有AI结论也将8前夜已毒死作为后夜推导前提。|
|bili-BV1xm3J6wEbr-p01-g02|R1.night.seer_check.result|{"result": "猎人"}|盗宝大师7当夜选择猎人；复盘明确通灵师验7反馈猎人，不是物理底牌盗宝大师。|
|bili-BV1xm3J6wEbr-p01-g02|R1.night.dreamer_action|{"action": "dream", "actor": 1, "targets": [6]}|复盘明确首夜摄梦人梦游6号毒师，正式首夜梦游槽unknown。|
|bili-BV1iDGK61EYt-p01-g01|R2.night.seer_check.result|{"result": "好人"}|预言家的好人反馈被目标的真实平民底牌替代；保留查验目标，反馈与底牌分开。|
|bili-BV1oXMB6fEQ4-p01-g04|R2.night.wolf_attack|{"action": "attack", "targets": [3]}|复盘明确追刀3号女巫；正式写刀9（通灵师），旁证第2日死亡补充又明确3号倒牌，原刀目标与同局后续存活矛盾。|
|bili-BV1oXMB6fEQ4-p01-g04|endgame.phases[0].day|{"day": 4, "note": "候选：第三天7号自爆之后入夜刀6，次白天放逐12后才拍刀"}|正式endgame.day=3且note说第三天放逐12；dossier将12放逐放第4天，连续复盘也为D3自爆→入夜刀6→白天放逐12→拍刀。存在终局挂错日的源内矛盾。|
|bili-BV1DFM26ME2o-p01-g04|R3.night.witch_poison / R4.night.witch_poison|{"R3": {"action": "pass", "targets": []}, "R4": {"action": "poison", "actor": 6, "targets": [11]}}|复盘R3女巫通过，R4才毒最后机械狼11终局；正式毒11提早一夜。既有AI已判R3空过、终局也由causal_terminal限定R4夜，但毒药事实未跟随校正。|
|bili-BV1pSuN62EoT-p01-g01|R1.night.seer_check.result|{"result": "好人"}|预言家反馈是好人；复盘中的平民为目标真实身份修饰语，正式result误记平民。|
|bili-BV12Mur6nEns-p01-g03|R2.day.night_deaths|{"action": "die", "targets": [5]}|守7挡刀形成狼刀平安，但女巫毒5仍应出局；正式整夜peaceful[]。终局复盘称11自爆后仅12末狼交牌，进一步排除5仍活；game_flow现仍列5且terminal=null。|
|bili-BV1JNgj6gEty-p01-g01|R1.day.badge|{"action": "transfer", "actor": 4, "targets": [12]}|复盘明确4号被放逐后警徽交12女巫，正式徽处理仍unknown。|
|bili-BV1aXgW6nE6E-p01-g02|R1.night.seer_check|{"action": "check", "actor": 8, "targets": [5], "result": "狼王"}|连续复盘明确首夜通灵师验5反馈狼王，正式该槽unknown。|
|bili-BV1aXgW6nE6E-p01-g02|R2.night.treasure_choice|{"action": "choose", "actor": 7, "result": "平民"}|复盘明确盗宝7第二夜切为平民，正式选择槽unknown。|
|bili-BV1aXgW6nE6E-p01-g02|R2.night.seer_check.result|{"result": "平民"}|正式已知通灵验7，但结果null；复盘明确反馈平民（盗宝已切平民）。|
|bili-BV1dc836KEjJ-p01-g01|R1.night.seer_check.result|{"result": "好人"}|预言家的好人反馈被目标的真实平民底牌替代；保留查验目标，反馈与底牌分开。|
|bili-BV1jc836TEt1-p01-g02|R2.night.seer_check.result|{"result": "好人"}|预言家查6反馈好人；平民是复盘对目标的底牌说明，不是查验反馈。|
|bili-BV1tj8p6REqy-p01-g01|R2.night.seer_check.result|{"result": "好人"}|预言家查4反馈好人，正式误记平民。|
|bili-BV1tj8p6REqy-p01-g01|R3.night.seer_check.result|{"result": "好人"}|预言家查7反馈好人，正式误记猎人；不是通灵师精确底牌查验。|
|bili-BV1tj8p6RE2h-p01-g02|R2.night.masquerade_verify.result|{"result": "不在舞池"}|复盘明确验6号舞者不在舞池；正式反馈误填目标底牌舞者。|
|bili-BV1tj8p6RE2h-p01-g02|R3.night.masquerade_verify.result|{"result": "在舞池"}|复盘明确验5号白神在舞池；正式反馈误填底牌白痴。|
|bili-BV1tj8p6RE2h-p01-g02|R2.night.seer_check.result|{"result": "好人"}|预言家查4反馈好人，正式误填平民。|
|bili-BV1tj8p6RE1V-p01-g03|R2.day.night_deaths|{"action": "die", "targets": [12]}|第二夜狼刀12、守7、机械女巫空过，12唯一死因成立；正式死亡unknown且game_flow第2日仍unknown，既有AI已确认刀12但死亡未落盘。|
|bili-BV1tj8p6RE1V-p01-g03|R4.night.wolf_attack|{"action": "attack", "actor": 6, "targets": [11]}|复盘明确机械狼普通刀11被守挡，再另用毒8；正式只存毒8，普通刀槽unknown。保留两动作而不把平安刀当整夜无死。|
|bili-BV1jM8B6jEkF-p01-g02|R2.night.seer_check.result|{"result": "好人", "note": "原目标4，号码交换后实际验到6号魔术师"}|完整原句明确查4实际验6魔术师为好人，正式查验目标4保留正确但结果null。|
|bili-BV18W8B6KE7C-p01-g03|R1.night.mechanical_action|{"action": "pass", "actor": 7, "targets": [], "note": "首夜未学习；第二夜才学1守卫"}|复盘明示首夜未学/未模仿并通过，既有AI亦已接受该学习时点；正式首夜动作仍unknown，不能把未知等同已确认空过。|
