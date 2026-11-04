import type { RankingEntry } from "@/lib/types";

export type RankingFilter = {
  minimumAppearances?: number;
  minimumEffectiveGames?: number;
  totalAppearancesByPlayer?: ReadonlyMap<string, number>;
};

/**
 * Filter a complete source ranking cohort, then assign ranks by the original rank groups.
 * This keeps exact source ties together without deriving rank from displayed rounded values.
 */
export function filterRankingEntries(entries: RankingEntry[], filter: RankingFilter = {}): RankingEntry[] {
  const minimumAppearances = Math.max(0, filter.minimumAppearances ?? 0);
  const minimumEffectiveGames = Math.max(0, filter.minimumEffectiveGames ?? 0);
  const cohort = entries.filter((entry) => (filter.totalAppearancesByPlayer
      ? filter.totalAppearancesByPlayer.get(entry.id) ?? 0
      : entry.appearances) >= minimumAppearances
    && (entry.effective_game_count ?? entry.sample_count) >= minimumEffectiveGames);
  const groupSizes = new Map<number, number>();
  for (const entry of cohort) groupSizes.set(entry.rank, (groupSizes.get(entry.rank) ?? 0) + 1);
  let previousSourceRank: number | undefined;
  let currentRank = 0;
  return cohort.map((entry, index) => {
    if (entry.rank !== previousSourceRank) {
      previousSourceRank = entry.rank;
      currentRank = index + 1;
    }
    return { ...entry, rank: currentRank, tied: (groupSizes.get(entry.rank) ?? 0) > 1 };
  });
}
