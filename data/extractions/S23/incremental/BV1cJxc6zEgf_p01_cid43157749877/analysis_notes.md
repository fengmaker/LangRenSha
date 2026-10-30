# S23 2026-10-29 第1局复核

```json
{
  "game": "BV1cJxc6zEgf",
  "source_path": "data/raw/bilibili/BV1cJxc6zEgf/p01/subtitle.01.raw.json",
  "source_sha256": "369936391c50840aae2a8e26ac455fbd18d7879be0a887f9e13ca1a77f3ef4de",
  "transcript_read": "reading.txt fully, segments 0 through 2737 (subtitle source fully read)",
  "visual_review": [
    "official Weibo post 5359379076612741 long text and 12-player card montage visually reviewed",
    "all 12 Bilibili seat-introduction frames visually reviewed; lower-third/table placard text, not faces, used for seat/name mapping"
  ],
  "known_names": 12,
  "known_physical_roles": 12,
  "ballots": 2,
  "ballot_votes": [
    3,
    12
  ],
  "key_facts": {
    "day1_registration": "on=[1,2,4,5,7,8,10,11,12]; off=[3,6,9]",
    "sheriff_ballot": "3->11;6->1;9->11; 11 elected",
    "day1_exile": "1->11;2->1;3->1;4->11;5->11;6->11;7->11;8->11;9->1;10->11;11->1;12->11; 11 exiled",
    "badge": "11->5 after day1 exile; 5->1 after night2 deaths",
    "end": "wolves surrender day2; good wins"
  },
  "gaps": [
    "第一夜已确认混血12号选择5号、狼人刀11号、女巫救11号、预言家验6号；其余首夜行动没有被复盘逐项证实，保留unknown，不解释成pass。",
    "第二夜已确认狼人刀5号、女巫毒2号、预言家验10号及2/5双死；其余夜间行动未见直接结论，保留unknown。",
    "首轮警长名单字幕疑似把候选1号/11号识成“11号/12号”；三张逐票播报的目标为1号或11号，且复盘确认11号得徽，因此候选池记为1号、11号。"
  ],
  "validation": {
    "candidate": "analyze_incremental.validate_candidate passed twice",
    "derivation": "game_derivations.derive_game completed",
    "rules_issues": []
  }
}
```
