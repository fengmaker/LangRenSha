# S22前74局复盘字段交叉审计

固定基线 `3476a56af155f36a0d0050abc1660ed0d6fd538a`。74局已连续阅读复盘并对照主要字段；原媒体直接复听/目视0局。

{"baseline_commit": "3476a56af155f36a0d0050abc1660ed0d6fd538a", "season": "S22", "assigned_games": 74, "games_with_recap_file": 73, "games_with_raw_source_hash_verified": 74, "games_with_manually_read_recap_context": 74, "direct_original_media_reviewed_games": 0, "source_field_conflicts": 21, "known_fact_not_encoded": 16, "descriptive_label_errors": 3, "games_with_findings": 26, "official_data_modified": false, "limits": "同一字幕的TXT/JSON和报告摘录不是独立证据；全部结论限文字证据层。无差异不是全字段真实准确性认证。"}

## 具体候选（未写入正式数据）

### 1. bili-BV1kGVC6cEyg-p01-g01 2026-06-02
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。

### 2. bili-BV1CGVC6cE8T-p01-g02 2026-06-02
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。
- 保留定案：相关双平票/夜间终局/梦死禁枪/机械守卫反毒/傀儡底牌/绑票或DQ等既有定案保留；不将本轮程序推断覆盖现场结算。

### 3. bili-BV1pGVC6cEbW-p01-g03 2026-06-02
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。
- 保留定案：相关双平票/夜间终局/梦死禁枪/机械守卫反毒/傀儡底牌/绑票或DQ等既有定案保留；不将本轮程序推断覆盖现场结算。

### 4. bili-BV1hb7R6XEtD-p01-g01 2026-06-03
- **S22-A-004-01 source_field_conflict** R1 night.seer_check：复盘先说平民身份，紧接着改口“好人身份”；应区分底牌和查验反馈。 来源 5023385–5028230ms；SHA256 `8b65b96a0abf18ded79f0cc75869599a552a7ebea4a0e79b83b6259c9c212a00`。候选 `{"result": "好人"}`。未发现该具体字段已有反向用户定案；本项不改变既有用户规则。
- 保留定案：相关双平票/夜间终局/梦死禁枪/机械守卫反毒/傀儡底牌/绑票或DQ等既有定案保留；不将本轮程序推断覆盖现场结算。

### 5. bili-BV1vH7R6tEQp-p01-g02 2026-06-03
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。

### 6. bili-BV1dJ7R6fEUw-p01-g03 2026-06-03
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。

### 7. bili-BV12GEA6iEx5-p01-g01 2026-06-04
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。

### 8. bili-BV117EA6AEcV-p01-g02 2026-06-04
- **S22-A-008-01 source_field_conflict** R1 night.seer_check：查验8号反馈为摄梦人，正式结果误为行动者自身的通灵师。 来源 5266010–5270310ms；SHA256 `290cb8340902bd39f8ad4ca276c2f1b5bd61de0b2816383c4833171165c350ad`。候选 `{"result": "摄梦人"}`。旧技能复核仅更正N2毒口及死亡；未更改N1查验反馈。
- 保留定案：相关双平票/夜间终局/梦死禁枪/机械守卫反毒/傀儡底牌/绑票或DQ等既有定案保留；不将本轮程序推断覆盖现场结算。

### 9. bili-BV1FX7C6BEAC-p01-g01 2026-06-05
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。

### 10. bili-BV1fX7C6qESY-p01-g02 2026-06-05
- **S22-A-010-01 known_fact_not_encoded** R2 night.seer_check：连续复盘明确预言家查验8号狼人，正式槽位仍unknown。 来源 5424420–5434680ms；SHA256 `226b0c98f3df423f00002cd29f3c74604e965bb71a7291db663a5fc5ca8ab27d`。候选 `{"action": "check", "actor": 2, "targets": [8], "result": "狼人"}`。未发现该具体字段已有反向用户定案；本项不改变既有用户规则。
- **S22-A-010-02 source_field_conflict** R2 night.masquerade_verify：假面验证的是是否在舞池；正式result=假面不是本次验证反馈。 来源 5414750–5420185ms；SHA256 `226b0c98f3df423f00002cd29f3c74604e965bb71a7291db663a5fc5ca8ab27d`。候选 `{"result": "不在舞池"}`。未发现该具体字段已有反向用户定案；本项不改变既有用户规则。
- **S22-A-010-03 source_field_conflict** R3 night.masquerade_verify：原文12号平民不在舞池，正式反馈误写假面。 来源 5449720–5455960ms；SHA256 `226b0c98f3df423f00002cd29f3c74604e965bb71a7291db663a5fc5ca8ab27d`。候选 `{"result": "不在舞池"}`。未发现该具体字段已有反向用户定案；本项不改变既有用户规则。
- **S22-A-010-04 source_field_conflict** R4 night.masquerade_verify：原文1号白神不在舞池，正式反馈误写假面。 来源 5464120–5474115ms；SHA256 `226b0c98f3df423f00002cd29f3c74604e965bb71a7291db663a5fc5ca8ab27d`。候选 `{"result": "不在舞池"}`。未发现该具体字段已有反向用户定案；本项不改变既有用户规则。

### 11. bili-BV1zX7C6qEmR-p01-g03 2026-06-05
- **S22-A-011-01 source_field_conflict** R1 night.seer_check：通灵师查验5号反馈守卫，不是笼统好人。 来源 3602340–3605149ms；SHA256 `28095fb5717366e274d0c19f4369cf75353f86a79546aae794f217e9b3a2da3a`。候选 `{"result": "守卫"}`。未发现该具体字段已有反向用户定案；本项不改变既有用户规则。

### 12. bili-BV1iaE26kE1w-p01-g01 2026-06-09
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。

### 13. bili-BV1jaE26kELR-p01-g02 2026-06-09
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。
- 保留定案：相关双平票/夜间终局/梦死禁枪/机械守卫反毒/傀儡底牌/绑票或DQ等既有定案保留；不将本轮程序推断覆盖现场结算。

### 14. bili-BV1jaE26kE8T-p01-g03 2026-06-09
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。

### 15. bili-BV1xYEo6QE3H-p01-g01 2026-06-10
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。

### 16. bili-BV1xYEo6QE3E-p01-g02 2026-06-10
- **S22-A-016-01 known_fact_not_encoded** R3 night.wolf_attack：复盘明确假面击杀12号舞者；正式狼刀槽位未知，已记录的夜死包含12。 来源 3838930–3845670ms；SHA256 `607f458edf4d0d8a1adbd7c34b0f258079996dfb9205e2c7be845651697e72f7`。候选 `{"action": "attack", "targets": [12]}`。未发现该具体字段已有反向用户定案；本项不改变既有用户规则。

### 17. bili-BV1sYEo6QEyS-p01-g03 2026-06-10
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。
- 保留定案：相关双平票/夜间终局/梦死禁枪/机械守卫反毒/傀儡底牌/绑票或DQ等既有定案保留；不将本轮程序推断覆盖现场结算。

### 18. bili-BV1xYEo6QEGV-p01-g04 2026-06-10
- **S22-A-018-01 source_field_conflict** R3 night.mechanical_action：第三夜机械通灵师验5号守卫，现字段重复了第二夜9号猎人。 来源 3957699–3964950ms；SHA256 `c965f5418b43544ee16a296583531d9d16547834c1ec9fd4b9650ddea2ee58bb`。候选 `{"action": "check", "actor": 1, "targets": [5], "result": "守卫"}`。旧疑点复核明确修正N2普通验10/机械验9；N3只修guard空过，未修N3机械查验。
- **S22-A-018-02 known_fact_not_encoded** R3 night.seer_check：紧接机械验5，复盘又明确普通通灵师验5守卫；正式普通查验unknown。 来源 3962010–3968170ms；SHA256 `c965f5418b43544ee16a296583531d9d16547834c1ec9fd4b9650ddea2ee58bb`。候选 `{"action": "check", "actor": 7, "targets": [5], "result": "守卫"}`。未发现该具体字段已有反向用户定案；本项不改变既有用户规则。

### 19. bili-BV13tEB6VE1J-p01-g01 2026-06-11
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。

### 20. bili-BV13tEB6VEVV-p01-g02 2026-06-11
- **S22-A-020-01 source_field_conflict** R4 day.sequential_prince_skill：定序王子翻牌发生在第三天9号被放逐之前，正式记到第四天。 来源 4367770–4376600ms；SHA256 `be6b7324afc1c2e455bda6c49d29b4be8d37bbdbe571eac0f32c6538e8a5c77f`。候选 `{"move_to_round": 3, "action": "reveal", "actor": 10}`。投票因果复核已补D3初轮和技能复投；既有结论支持D3，不需重问。
- **S22-A-020-02 source_field_conflict** R3 day.badge：前一日延期竞选再次自爆，明确警徽流失；不存在12号移徽9号。 来源 4354300–4361019ms；SHA256 `be6b7324afc1c2e455bda6c49d29b4be8d37bbdbe571eac0f32c6538e8a5c77f`。候选 `{"action": "none", "actor": null, "targets": []}`。正式voting无警长票，既有投票规则及复盘均为两次自爆流徽；本项查dossier残留移徽。

### 21. bili-BV1uaEB66E7q-p01-g03 2026-06-11
- **S22-A-021-01 source_field_conflict** R1 day.sheriff_result：5号是在竞选环节自爆；正式记5号当选。原稿局中1236490–1245420亦先退水自爆后入夜，次日1530020宣布流徽。 来源 4205880–4208440ms；SHA256 `b2de82f3083314fe0806d3345e4cf20eccf59ece99eeab0a786c074056cb1106`。候选 `{"action": "deferred", "targets": []}`。voting只含D3/D4放逐票，election流程应保持已接受延期/流徽结论。

### 22. bili-BV1wmEB68Exu-p01-g04 2026-06-11
- **S22-A-022-01 source_field_conflict** R2 day.night_deaths：守4挡刀不代表整夜平安；女巫毒6，复盘和局中3588700–3601500均明确6倒牌移徽3。 来源 7540930–7549330ms；SHA256 `24d35d6f401f8001eda548a36ae58f2825afbbd1c683220a675abb889745378a`。候选 `{"action": "die", "targets": [6]}`。旧疑点仅修N1奶穿12和N3守3，未修N2毒6死亡；voting game_flow继续保留6且D3/D4默认弃票，故派生层未覆盖。

### 23. bili-BV1sKJ56PEey-p01-g01 2026-06-12
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。

### 24. bili-BV11KJ56PEPY-p01-g03 2026-06-12
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。
- 保留定案：相关双平票/夜间终局/梦死禁枪/机械守卫反毒/傀儡底牌/绑票或DQ等既有定案保留；不将本轮程序推断覆盖现场结算。

### 25. bili-BV1yKJ56PEak-p01-gunknown 2026-06-12
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。
- 保留定案：相关双平票/夜间终局/梦死禁枪/机械守卫反毒/傀儡底牌/绑票或DQ等既有定案保留；不将本轮程序推断覆盖现场结算。

### 26. bili-BV1W6jG6HEeT-p01-g01 2026-06-16
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。

### 27. bili-BV1W6jG6HELj-p01-g02 2026-06-16
- **S22-A-027-01 known_fact_not_encoded** R2 night.magician_exchange：复盘明确魔术师交换自己2号与6号；正式槽位未知。 来源 6495160–6501429ms；SHA256 `daff172da767a1236e8d826100427edd8d080ab1141f8097a893c72f8e7b0be8`。候选 `{"action": "exchange", "actor": 2, "targets": [2, 6]}`。未发现该具体字段已有反向用户定案；本项不改变既有用户规则。
- **S22-A-027-02 known_fact_not_encoded** R2 night.seer_check：原稿“武汉家”疑为“5号玩家”，上下文支持验5狼人；需原音确认数字，不能当高置信补值。 来源 6506189–6509930ms；SHA256 `daff172da767a1236e8d826100427edd8d080ab1141f8097a893c72f8e7b0be8`。候选 `{"action": "check", "actor": 7, "targets": [5], "result": "狼人"}`。未发现该具体字段已有反向用户定案；本项不改变既有用户规则。
- **S22-A-027-03 descriptive_label_error** R3 day.sequential_prince_skill：actor=11正确，描述误把前句“10号玩家高票”当定序王子座位。 来源 6525500–6531020ms；SHA256 `daff172da767a1236e8d826100427edd8d080ab1141f8097a893c72f8e7b0be8`。候选 `{"result": "11号定序王子翻牌；10号是原首轮高票对象"}`。未发现该具体字段已有反向用户定案；本项不改变既有用户规则。

### 28. bili-BV1W6jG6HEkC-p01-g03 2026-06-16
- **S22-A-028-01 descriptive_label_error** R1 night.mechanical_action：actor=8正确，但result叙述写机械狼1号。 来源 3227900–3240360ms；SHA256 `045855cfb4562e339ffcb99668d5483dc34c7b3f5bbd4380d8af4f19f2de0be4`。候选 `{"result": "机械狼8号模仿3号狼人同伴"}`。未发现该具体字段已有反向用户定案；本项不改变既有用户规则。

### 29. bili-BV1KkL96MEuH-p01-g01 2026-06-17
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。
- 保留定案：拍刀6/7/12候选按既有S22_拍刀交叉复核.json不晋升：该段战术讨论并称交牌，无明确法官拍刀结算。保留endgame.phases=[]，不重开定案。

### 30. bili-BV1KkL96MEim-p01-g02 2026-06-17
- **S22-A-030-01 known_fact_not_encoded** R3 night.masquerade_verify：复盘明确验证1号在舞池；正式槽位未知。 来源 3217150–3226460ms；SHA256 `dd02dc47cfcd856774308b05bad80225e8744a0696bae2f62c7511dfe69d909c`。候选 `{"action": "verify", "actor": 9, "targets": [1], "result": "在舞池"}`。未发现该具体字段已有反向用户定案；本项不改变既有用户规则。
- **S22-A-030-02 known_fact_not_encoded** R3 night.masquerade_mask：复盘明确给1号面具导致1号共舞出局；正式槽位未知。 来源 3217150–3228320ms；SHA256 `dd02dc47cfcd856774308b05bad80225e8744a0696bae2f62c7511dfe69d909c`。候选 `{"action": "give_mask", "actor": 9, "targets": [1]}`。未发现该具体字段已有反向用户定案；本项不改变既有用户规则。
- **S22-A-030-03 known_fact_not_encoded** R4 night.wolf_attack：复盘明确击杀5号舞者、5/10双死，正式刀口未知。 来源 3243280–3246680ms；SHA256 `dd02dc47cfcd856774308b05bad80225e8744a0696bae2f62c7511dfe69d909c`。候选 `{"action": "attack", "targets": [5]}`。未发现该具体字段已有反向用户定案；本项不改变既有用户规则。

### 31. bili-BV1xkL96MEsd-p01-g03 2026-06-17
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。

### 32. bili-BV1Ajja66EuC-p01-g01 2026-06-18
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。

### 33. bili-BV1Hjja6zEZa-p01-g02 2026-06-18
- **S22-A-033-01 descriptive_label_error** R3 day.guile_exchange_result：事件位于R3正确，但result开头错写R2夜。 来源 4912179–4930040ms；SHA256 `d259dba4acaa09e96cfcc5d2201878694724b647fab69d7fc5b7ecbb6a1b7a48`。候选 `{"result": "R3夜魔术师与诡术师同选4号、5号，双方技能抵消"}`。未发现该具体字段已有反向用户定案；本项不改变既有用户规则。

### 34. bili-BV1Wjja66EFz-p01-g03 2026-06-18
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。

### 35. bili-BV17kj669ED5-p01-g01 2026-06-19
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。

### 36. bili-BV1Hej66FE1Y-p01-g02 2026-06-19
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。
- 保留定案：相关双平票/夜间终局/梦死禁枪/机械守卫反毒/傀儡底牌/绑票或DQ等既有定案保留；不将本轮程序推断覆盖现场结算。

### 37. bili-BV1nBj664EFS-p01-g03 2026-06-19
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。
- 保留定案：相关双平票/夜间终局/梦死禁枪/机械守卫反毒/傀儡底牌/绑票或DQ等既有定案保留；不将本轮程序推断覆盖现场结算。

### 38. bili-BV18ijD6BExh-p01-g01 2026-06-23
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。

### 39. bili-BV1DijD6BE4g-p01-g02 2026-06-23
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。

### 40. bili-BV18ijD6BExE-p01-g03 2026-06-23
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。

### 41. bili-BV1QAjo6sEEc-p01-g01 2026-06-24
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。

### 42. bili-BV1QAjo6sEaN-p01-g02 2026-06-24
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。

### 43. bili-BV13Ajo6xEY8-p01-g03 2026-06-24
- **S22-A-043-01 source_field_conflict** R2 night.mechanical_action：普通女巫5毒11、机械女巫9毒5；正式机械毒口误为11。 来源 4106055–4118670ms；SHA256 `1f24ad124a8bfa10297388c64c5fd7b762109e0b3924c6750a2b17ccc1221197`。候选 `{"action": "poison", "actor": 9, "targets": [5]}`。S22_疑点推理复核.json该局已明确接受此结论，但changes只修死亡与查验，未修行动主体/毒口。属于定案落库缺口。
- **S22-A-043-02 known_fact_not_encoded** R2 night.witch_poison：普通女巫毒11已在旧结论及原文明确，但正式槽位未知。 来源 4106055–4118670ms；SHA256 `1f24ad124a8bfa10297388c64c5fd7b762109e0b3924c6750a2b17ccc1221197`。候选 `{"action": "poison", "actor": 5, "targets": [11]}`。同局旧疑点复核已接受“普通女巫毒11、机械女巫毒5”，不重新开启人工定案。

### 44. bili-BV1Pt7v6XEP4-p01-g01 2026-06-25
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。
- 保留定案：相关双平票/夜间终局/梦死禁枪/机械守卫反毒/傀儡底牌/绑票或DQ等既有定案保留；不将本轮程序推断覆盖现场结算。

### 45. bili-BV1yt7v6QEny-p01-g02 2026-06-25
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。

### 46. bili-BV1yt7v6QE3Q-p01-g03 2026-06-25
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。
- 保留定案：示例局没有独立复盘原文文件，但已直接读取平台字幕2029–2084秒，身份/胜方/主流程一致。首夜解药未知按现有示例README保留，本次不因“女王救起”机器字串自动改值。

### 47. bili-BV1o47L6DECA-p01-g01 2026-06-26
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。

### 48. bili-BV1747L6QETh-p01-g02 2026-06-26
- **S22-A-048-01 known_fact_not_encoded** R1 night.dreamer_action：首夜摄梦人梦10号通灵师，正式槽位未知。 来源 4496620–4499020ms；SHA256 `252d4078ee6cf1aacd78abf547fa0bf2d287545bb205e6997dce4e2a5a88e92f`。候选 `{"action": "dream", "actor": 1, "targets": [10]}`。未发现该具体字段已有反向用户定案；本项不改变既有用户规则。
- **S22-A-048-02 known_fact_not_encoded** R2 night.seer_check：复盘明确通灵师夜验3号蒙面人；正式槽位未知。 来源 4519379–4524870ms；SHA256 `252d4078ee6cf1aacd78abf547fa0bf2d287545bb205e6997dce4e2a5a88e92f`。候选 `{"action": "check", "actor": 10, "targets": [3], "result": "蒙面人"}`。未发现该具体字段已有反向用户定案；本项不改变既有用户规则。

### 49. bili-BV1d47L6DEoo-p01-g03 2026-06-26
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。

### 50. bili-BV1cJ7L64EBW-p01-g04 2026-06-26
- **S22-A-050-01 source_field_conflict** R1 night.seer_check：预言家反馈是狼人，诡术师是被验者底牌，不应混入反馈字段。 来源 4685810–4690350ms；SHA256 `62b7a7440905476277647e26d9834105d28e69834eaead8311c4a2d49594e269`。候选 `{"result": "狼人"}`。未发现该具体字段已有反向用户定案；本项不改变既有用户规则。

### 51. bili-BV1YmTc6yEFd-p01-g01 2026-06-30
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。

### 52. bili-BV1GmTc61EMA-p01-g02 2026-06-30
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。
- 保留定案：相关双平票/夜间终局/梦死禁枪/机械守卫反毒/傀儡底牌/绑票或DQ等既有定案保留；不将本轮程序推断覆盖现场结算。

### 53. bili-BV1Y2Tc6LEt4-p01-g03 2026-06-30
- **S22-A-053-01 source_field_conflict** R1 night.seer_check：通灵师验已学习的机械双刀狼反馈狼人；正式result写“2号为机械双刀狼”混入底牌/形态。 来源 6184900–6188240ms；SHA256 `b3dbcdc540f351110ee16185d6e1468a01112f296896e7ab22809368c4ae57aa`。候选 `{"result": "狼人"}`。未发现该具体字段已有反向用户定案；本项不改变既有用户规则。

### 54. bili-BV1gvTi66EFF-p01-g01 2026-07-01
- **S22-A-054-01 source_field_conflict** R2 day.sheriff_result：延期竞选第二次自爆后流徽，不再deferred。 来源 3612440–3616060ms；SHA256 `8668f5ed9cd1491ccb3972e43b0d21ae560b63cd8c9c56e7326474257634e6ab`。候选 `{"action": "none", "targets": [], "result": "第二天再次自爆，警徽流失"}`。用户已确认最多延期一次；沿用规则，不重开规则定案。

### 55. bili-BV1gvTi66E7y-p01-g02 2026-07-01
- **S22-A-055-01 known_fact_not_encoded** R3 day.sequential_prince_skill：复盘明确第三天定序王子翻牌后放逐3，正式技能unknown。 来源 4260000–4264980ms；SHA256 `1547938177ea11739fc9fc134cb8e69839b2cd4729f648c60417aab5e62ae521`。候选 `{"action": "reveal", "actor": 10}`。未发现该具体字段已有反向用户定案；本项不改变既有用户规则。

### 56. bili-BV18vTi66EnN-p01-g03 2026-07-01
- **S22-A-056-01 known_fact_not_encoded** R1 night.guard：正式守护目标1号正确，行动者null；同段身份表确认守卫9号。 来源 4803950–4817830ms；SHA256 `4828041f9481ef6e6062158ad48f58218a9f49f1e8352a68a9ba4b20cca16cff`。候选 `{"actor": 9}`。未发现该具体字段已有反向用户定案；本项不改变既有用户规则。

### 57. bili-BV1K9TJ6WEBv-p01-g01 2026-07-02
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。

### 58. bili-BV119TJ6pEtC-p01-g02 2026-07-02
- **S22-A-058-01 source_field_conflict** R2 night.treasure_alignment：选平民技能牌不会改变个人阵营；正式treasure_alignment=good与用户定案及角色faction=werewolf冲突。 来源 6412300–6415910ms；SHA256 `8fa1a23e537d4b76042fc3f95549558cbc821a7ce305e120f738e88623000f5b`。候选 `{"action": "wolf", "actor": 7, "result": "盗宝大师始终狼人阵营；本夜仅切换平民形态"}`。config/S22_formal_rules.json及用户确认_20261025.txt已定案盗宝始终狼人；只修残留事件，不重问。

### 59. bili-BV149TJ6WETs-p01-g03 2026-07-02
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。
- 保留定案：相关双平票/夜间终局/梦死禁枪/机械守卫反毒/傀儡底牌/绑票或DQ等既有定案保留；不将本轮程序推断覆盖现场结算。

### 60. bili-BV1BjMh63EEK-p01-g01 2026-07-07
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。
- 保留定案：相关双平票/夜间终局/梦死禁枪/机械守卫反毒/傀儡底牌/绑票或DQ等既有定案保留；不将本轮程序推断覆盖现场结算。

### 61. bili-BV1BjMh63ED9-p01-g02 2026-07-07
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。

### 62. bili-BV1BjMh63EDf-p01-g03 2026-07-07
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。

### 63. bili-BV11uMG6PEkr-p01-g01 2026-07-08
- **S22-A-063-01 known_fact_not_encoded** R2 night.witch_poison：复盘明确女巫毒11平民，正式毒药槽位仍unknown。 来源 6313895–6319735ms；SHA256 `e773637c20d56e22cb550120e9a22c6e048a862d76f83f4ae8cd58454bcc1cd2`。候选 `{"action": "poison", "actor": 10, "targets": [11]}`。未发现该具体字段已有反向用户定案；本项不改变既有用户规则。

### 64. bili-BV1KuMG6NEez-p01-g02 2026-07-08
- **S22-A-064-01 known_fact_not_encoded** R1 night.puppet_select：复盘明确8号原底牌预言家被选为傀儡，正式选择槽位unknown；反向查验已有记录。 来源 3489350–3502490ms；SHA256 `4e42831425d3dfc83a0e21360f07afc3920b086a1f40a46e192e355c0231ddda`。候选 `{"action": "select", "targets": [8]}`。未发现该具体字段已有反向用户定案；本项不改变既有用户规则。
- 保留定案：相关双平票/夜间终局/梦死禁枪/机械守卫反毒/傀儡底牌/绑票或DQ等既有定案保留；不将本轮程序推断覆盖现场结算。

### 65. bili-BV1suMG6PEYP-p01-g03 2026-07-08
- **S22-A-065-01 source_field_conflict** R5 night.wolf_attack：原文小刀12猎人、大刀11平民；正式普通刀11、技能刀12颠倒。 来源 6344055–6355035ms；SHA256 `173943bef0ca1b4d4a23c665d6b405d39c97f729b4a60d12e800869102f2c03b`。候选 `{"targets": [12]}`。endgame.note已保存正确刀种关系；旧疑点修身份和N3死亡，未修N5刀种。
- **S22-A-065-02 source_field_conflict** R5 night.mechanical_action：同一刀路的技能刀应11，不是12；需与ordinary wolf_attack联动纠正。 来源 6344055–6355035ms；SHA256 `173943bef0ca1b4d4a23c665d6b405d39c97f729b4a60d12e800869102f2c03b`。候选 `{"targets": [11], "result": "机械双刀大刀/技能刀击杀11号平民"}`。endgame.note已保存正确刀种关系；此为正式日夜字段与已接受终局备注不一致。

### 66. bili-BV13ZMp63EPs-p01-g01 2026-07-09
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。

### 67. bili-BV1hZMp63Esx-p01-g02 2026-07-09
- **S22-A-067-01 known_fact_not_encoded** R4 day.exile_result：复盘明确定序王子4翻牌后被公投出局终局；正式放逐槽位unknown，但技能result已叙述被公投。 来源 7137610–7147960ms；SHA256 `b477426ba0230185139817c0d51407f43788b91d9a55347e2407e3d8a198143f`。候选 `{"action": "exile", "targets": [4]}`。未发现该具体字段已有反向用户定案；本项不改变既有用户规则。
- 保留定案：相关双平票/夜间终局/梦死禁枪/机械守卫反毒/傀儡底牌/绑票或DQ等既有定案保留；不将本轮程序推断覆盖现场结算。

### 68. bili-BV13ZMp63EEB-p01-g03 2026-07-09
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。

### 69. bili-BV1GxNH6YESw-p01-g01 2026-07-10
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。

### 70. bili-BV1GxNH6YEht-p01-g02 2026-07-10
- **S22-A-070-01 source_field_conflict** R2 night.masquerade_verify：原文4号舞者不在舞池，正式result误为假面。 来源 2668710–2674550ms；SHA256 `feeed585eb01d3a52056d95df8b434b131d40af77c6214f61f29975e7e65920e`。候选 `{"result": "不在舞池"}`。未发现该具体字段已有反向用户定案；本项不改变既有用户规则。
- **S22-A-070-02 source_field_conflict** R3 night.masquerade_verify：原文7号平民在舞池，正式result误为假面。 来源 2700360–2706460ms；SHA256 `feeed585eb01d3a52056d95df8b434b131d40af77c6214f61f29975e7e65920e`。候选 `{"result": "在舞池"}`。未发现该具体字段已有反向用户定案；本项不改变既有用户规则。
- **S22-A-070-03 source_field_conflict** R3 day.self_destruct：复盘明说交牌，局中2611609–2614269亦明确交牌游戏结束；解说2473320“视为一手自爆”不可当实际自爆。 来源 2711960–2717140ms；SHA256 `feeed585eb01d3a52056d95df8b434b131d40af77c6214f61f29975e7e65920e`。候选 `{"action": "none", "actor": null, "result": "10号假面交牌认输，非自爆；应另记白天交牌终局"}`。既有投票day_outcomes也写10自爆，未覆盖；旧专项只修死亡和报名票型，没有关于真实自爆的用户定案。

### 71. bili-BV1VxNH6YETC-p01-g03 2026-07-10
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。

### 72. bili-BV1YxNH6YEqY-p01-g04 2026-07-10
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。

### 73. bili-BV1sEN86gEM2-p01-g01 2026-07-14
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。

### 74. bili-BV1PEN863EXG-p01-g02 2026-07-14
连续复盘未发现明确底牌/胜方/已知主流程冲突；不代表逐字段原媒体核实通过。
- 保留定案：相关双平票/夜间终局/梦死禁枪/机械守卫反毒/傀儡底牌/绑票或DQ等既有定案保留；不将本轮程序推断覆盖现场结算。
