import type { PlayerDetail, PlayerStats } from "@/lib/types";
import { ApiError } from "@/lib/api-error";

export type SharedPlayerRankings = {
  release_id: string;
  analytics_version?: number;
  scope: PlayerDetail["scope"];
  ranking_boards?: PlayerStats["ranking_boards"];
};

export function restorePlayerRankings(profile: PlayerDetail, shared: SharedPlayerRankings): PlayerDetail {
  const scope = profile.scope;
  const sharedScope = shared.scope;
  if (profile.release_id !== shared.release_id || profile.analytics_version !== shared.analytics_version
      || !scope || !sharedScope || scope.season_start !== sharedScope.season_start
      || scope.season_end !== sharedScope.season_end || scope.minimum_appearances !== sharedScope.minimum_appearances
      || JSON.stringify(scope.seasons) !== JSON.stringify(sharedScope.seasons)) {
    throw new ApiError("invalid", "个人统计与共享排名的版本或赛季范围不一致。");
  }
  if (!("ranking_boards" in shared)) return profile;
  if (!profile.stats || "ranking_boards" in profile.stats) {
    throw new ApiError("invalid", "个人统计的共享排名格式无效。");
  }
  return { ...profile, stats: { ...profile.stats, ranking_boards: shared.ranking_boards } };
}
