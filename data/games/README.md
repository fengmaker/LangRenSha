# 最终对局

每局一份 `game.json`，`schema_version: 1`。字段保持网站业务格式：

- `id/season/date/phase/game_number/board/winner`：范围与赛果；S21 仍保留媒体档案和计分范围未确认的说明。
- `seats/players`：稳定人物 ID、物理底牌、个人阵营、榜样/学习与傀儡状态。
- `rounds/voting/endgame/terminal_observation/terminal_events`：真实日夜、每轮逐人票型和独立终局。
- `rules_state`：最终存活、夜死完整性、槽位资格和未知状态；统计必须消费这些结果。
- `bluffs`：最终悍跳归属、是否成功、人工纳入及确认/未知状态。`bluff_review_available` 决定该范围的悍跳信息完整性，不能因删除历史材料改变分母。
- `source.media`：BV、CID、分 P 和官方视频链接；`data_notes` 保存必要业务说明。

正式结果可以独立导出网站。当前增量的 `dossier/voting/endgame` 候选和 `rule_derivations` 仅在临时工作目录处理，经人工确认后固化成此格式；历史推导、输入指纹和回执不是发布依赖。
