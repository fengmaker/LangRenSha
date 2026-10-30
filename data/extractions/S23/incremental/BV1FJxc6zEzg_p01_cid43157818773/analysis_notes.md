# S23 2026-10-29 第2局复核

```json
{
  "game": "BV1FJxc6zEzg",
  "source_path": "data/raw/bilibili/BV1FJxc6zEzg/p01/subtitle.01.raw.json",
  "source_sha256": "4d9bce6fe96f2f4bc7f4242d9bc6643c94ede2a96dfd3495460a16a1fc4c1ce6",
  "transcript_read": "reading.txt and all 2331 subtitle segments read end-to-end; source contains Chinese subtitles, no ASR used",
  "visual_review": [
    "official Weibo announcement longTextContent read in full; 12 roster card images assembled and viewed for context only, no face-based name matching",
    "Bilibili 877s wide stage frame viewed for seat/table context",
    "Bilibili 4398s final role slate visually read; all 12 seat names and physical role labels visible; role mapping based on graphic text"
  ],
  "known_names": 12,
  "known_physical_roles": 12,
  "ballots": 0,
  "ballot_votes": 0,
  "roles": {
    "1": {
      "name": "郭小炜",
      "role": "假面"
    },
    "2": {
      "name": "李大花",
      "role": "狼人"
    },
    "3": {
      "name": "园长LA",
      "role": "平民"
    },
    "4": {
      "name": "小乖",
      "role": "狼人"
    },
    "5": {
      "name": "彭彭",
      "role": "狼人"
    },
    "6": {
      "name": "陈彬",
      "role": "平民"
    },
    "7": {
      "name": "小苍",
      "role": "舞者"
    },
    "8": {
      "name": "牛肉干",
      "role": "平民"
    },
    "9": {
      "name": "小鲸鱼",
      "role": "女巫"
    },
    "10": {
      "name": "陈明峻",
      "role": "白神"
    },
    "11": {
      "name": "小白",
      "role": "平民"
    },
    "12": {
      "name": "大卫",
      "role": "预言家"
    }
  },
  "voting": {
    "day1": "9 on-police, 3 off-police; #5 self-destruct interrupted initial sheriff election",
    "day2": "deferred election interrupted by #2 self-destruct; badge lost",
    "day3": "#4 self-destruct before any exile ballot",
    "ballots": []
  },
  "key_nights": [
    "N1: wolf attack #6; witch #9 saved #6; seer #12 checked #7 good.",
    "N2: #1 mask verified #11 outside dance pool and gave #4 a mask; dancer #7 pool [1,2,9], #9 out by dance, wolf attack #6; #12 checked #1 werewolf; dawn #6/#9 both out.",
    "N3: dancer #7 pool [7,10,12], mask #1 verified #3 and masked #11; wolf attack #7 formed peaceful night; #12 checked #8 good.",
    "N4: #7 repeated pool [1,3,11] and was disqualified; #1 repeated verify on #3 and was disqualified; #1 surrendered, good won; no D4."
  ],
  "gaps": [
    "全片中文字幕完整阅读，未见法官宣布出票、逐票播报、投票结束或正式PK后投票；首轮警选由5号自爆中断，延期警选由2号自爆中断并流徽，第三天由4号自爆直接入夜。因此本候选记录0个实际票轮、0张逐票；发言中的“投一号”“PK台”等是讨论/建议，不当作已举行投票。",
    "N2夜后法官明确播报6号与9号双死、无先后；复盘字幕把狼刀/舞池结算相邻句转写较差。已按可辨复盘记录狼刀6、舞池判离9；女巫9号当夜是否使用解药或毒药无可辨的独立宣布，两个药剂动作保留unknown。",
    "终局夜复盘明确舞者7号舞池为1、3、11，假面重复验证3号而出局；字幕对假面另一项“连续查验或连续戴面具”规则转写可辨，但未能确认终局夜是否另行执行赐面动作及其目标，该槽保留unknown。",
    "终局发生在第4夜，官方复盘随后即宣布假面交牌、游戏结束；不存在D4白天或D4放逐投票。终局夜后的D4槽位仅用模板既有not_held/none/unavailable表达未发生，不增加新事件槽。",
    "本局复盘图卡显示12席实体角色为3张狼人、1张假面、1张舞者、1张女巫、1张白神、1张预言家和4张平民；本地s23_masquerade配置另含1张白痴，因而配置列出的role_counts总数为13而与本局12席牌面不符。候选按本局复盘图卡记事实，配置问题留给主代理核对，不修改配置。",
    "规则冲突：{\"round\": 4, \"code\": \"dance_participant_reused\", \"phase\": \"night\", \"slot\": \"dancer_dance\", \"seats\": [1]}",
    "规则冲突：{\"code\": \"action_unavailable\", \"round\": 4, \"phase\": \"night\", \"slot\": \"masquerade_verify\", \"actor\": 1, \"reason\": \"masquerade_verify_target_repeat\"}",
    "规则冲突：{\"code\": \"illegal_targets\", \"round\": 4, \"phase\": \"night\", \"slot\": \"dancer_dance\", \"actor\": 7, \"targets\": [1], \"reason\": \"dance_three_living_players_once_per_game\"}"
  ],
  "validation": {
    "candidate": "analyze_incremental.validate_candidate passed before and after derive",
    "derive_game": "completed with terminal_observation round4/night",
    "rule_issues": [
      {
        "round": 4,
        "code": "dance_participant_reused",
        "phase": "night",
        "slot": "dancer_dance",
        "seats": [
          1
        ]
      },
      {
        "code": "action_unavailable",
        "round": 4,
        "phase": "night",
        "slot": "masquerade_verify",
        "actor": 1,
        "reason": "masquerade_verify_target_repeat"
      },
      {
        "code": "illegal_targets",
        "round": 4,
        "phase": "night",
        "slot": "dancer_dance",
        "actor": 7,
        "targets": [
          1
        ],
        "reason": "dance_three_living_players_once_per_game"
      }
    ]
  }
}
```
