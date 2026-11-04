"use client";

import { StaticData } from "@/components/static-data";
import { ApiError } from "@/lib/api-error";
import { fetchGamesIndex, fetchOverview, fetchStatsRange, staticRouteId } from "@/lib/static-browser";
import { filterAndSortGames } from "@/lib/game-query";
import { SeasonView } from "./season-view";

async function loadSeason() {
  const id = staticRouteId("seasons");
  const [overview, games, stats] = await Promise.all([fetchOverview(), fetchGamesIndex(), fetchStatsRange(id, id)]);
  const season = overview.seasons.find((item) => item.id === id);
  if (!season) throw new ApiError("not-found", "没有找到这条赛季档案。");
  const selected = filterAndSortGames(games.items, { season: id });
  document.title = `赛季档案 ${id} · 大师赛档案`;
  return { season, stats, recent: selected.slice(0, 12), regularCount: selected.filter((game) => game.phase === "regular").length, finalsCount: selected.filter((game) => game.phase === "finals_week").length };
}

export function StaticSeasonBrowser() {
  return <StaticData load={loadSeason}>{(data) => <SeasonView {...data} />}</StaticData>;
}
