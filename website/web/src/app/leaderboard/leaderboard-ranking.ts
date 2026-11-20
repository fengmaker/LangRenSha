import type { LeaderboardItem } from "@/lib/types";

export const leaderboardColumnGroups = [
  { label: "综合表现", columns: [
    ["points", "积分"],
    ["appearances", "整季出场"],
    ["attendance", "出场率"],
    ["wins", "总胜场"],
    ["total_win_rate", "整季胜率"],
    ["sheriff_registration_rate", "上警率"],
  ] },
  { label: "好人表现", columns: [
    ["good_wins", "好人胜场"],
    ["good_win_rate", "好人胜率"],
    ["wolf_votes", "投狼次数"],
    ["wolf_vote_rate", "投狼率"],
    ["exile_abstentions", "放逐弃票"],
    ["good_sheriff_registration_rate", "好人上警率"],
    ["good_off_police_rate", "好人警下率"],
    ["sheriff_seer_vote_rate", "警徽正确率"],
    ["seer_follow_rate", "跟真预言家投票率"],
  ] },
  { label: "狼人表现", columns: [
    ["werewolf_appearances", "狼人场次"],
    ["werewolf_wins", "狼人胜场"],
    ["werewolf_win_rate", "狼人胜率"],
    ["werewolf_draw_rate", "拿狼率"],
    ["werewolf_self_explosion_rate", "自爆率"],
    ["werewolf_sheriff_registration_rate", "狼人上警率"],
    ["bluff_count", "悍跳次数"],
    ["bluff_rate", "悍跳率"],
    ["bluff_success_rate", "悍跳成功率"],
  ] },
] as const;

export type LeaderboardSortField = (typeof leaderboardColumnGroups)[number]["columns"][number][0];

export function readLeaderboardSort(value: string | null): LeaderboardSortField {
  for (const { columns } of leaderboardColumnGroups) {
    for (const [field] of columns) {
      if (value === field) return field;
    }
  }
  return "points";
}

function sortValue(player: LeaderboardItem, field: LeaderboardSortField): number | null {
  switch (field) {
    case "good_wins": return player.good_win_rate.numerator;
    case "wolf_votes": return player.wolf_vote_rate.numerator;
    case "werewolf_wins": return player.werewolf_win_rate.numerator;
    case "bluff_count": return player.bluff_count_complete ? player.bluff_count : null;
    default: {
      const value = player[field];
      return typeof value === "number" ? value : value.rate;
    }
  }
}

export function rankLeaderboard(items: readonly LeaderboardItem[], field: LeaderboardSortField) {
  if (field === "points") return items.map((player) => ({ player, rank: player.rank }));

  const sorted = items.map((player) => ({ player, value: sortValue(player, field) }))
    .sort((a, b) => a.value === b.value ? 0 : (b.value ?? -Infinity) - (a.value ?? -Infinity));
  let previousValue: number | null = null;
  let rank = 0;
  return sorted.map(({ player, value }, index) => {
    if (value === null) return { player, rank: null };
    if (value !== previousValue) rank = index + 1;
    previousValue = value;
    return { player, rank };
  });
}
