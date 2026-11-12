import type {
  GameDetail,
  Overview,
  PageResult,
  PlayerDetail,
  PlayerSummary,
  GameSummary,
  Stats,
  Release,
  Leaderboard,
  RankingEntry,
} from "@/lib/types";
import { cache } from "react";
import { filterAndSortGames, validateGameFilters, type GameFilters } from "@/lib/game-query";
import { filterRankingEntries } from "@/lib/ranking-filter";
import { parsePositivePage } from "@/lib/query-state";
import { ApiError } from "@/lib/api-error";
export { ApiError } from "@/lib/api-error";
import {
  getSnapshotGame, getSnapshotGames, getSnapshotLeaderboard,
  getSnapshotManifest, getSnapshotOverview, getSnapshotPlayer, getSnapshotPlayers,
  getSnapshotReleases, getSnapshotStats,
} from "@/lib/snapshot-data";

export function getOverview() {
  return getSnapshotOverview();
}

export function getGames(params: URLSearchParams) {
  return getStaticGames(params);
}

export const getGame = cache((id: string) => getSnapshotGame(id));

export function getPlayers(params: URLSearchParams) {
  return getStaticPlayers(params);
}

export const getPlayer = cache((id: string, season = "S23", phase = "all", seasonEnd?: string, minimumAppearances = 0) => {
  const params = new URLSearchParams({ season, phase });
  if (seasonEnd) { params.set("season_start", season); params.set("season_end", seasonEnd); }
  if (minimumAppearances !== 0) params.set("minimum_appearances", String(minimumAppearances));
  return getStaticPlayer(id, params);
});

export function getLeaderboard(season = "S23", phase: "all" | "finals_week" = "all") {
  return getSnapshotLeaderboard(season, phase);
}

export function getStats(season = "S22", seasonEnd?: string) {
  return getStaticStats(season, seasonEnd);
}

export function getReleases() {
  return getSnapshotReleases();
}

async function getStaticGames(params: URLSearchParams): Promise<PageResult<GameSummary>> {
  const source = await getSnapshotGames();
  const getFilter = (key: string) => params.has(key) ? params.get(key) ?? "" : undefined;
  const filters: GameFilters = {
    season: getFilter("season"), phase: getFilter("phase"), board: getFilter("board"),
    player: getFilter("player"), q: getFilter("q"), date_from: getFilter("date_from"), date_to: getFilter("date_to"),
  };
  const invalid = validateGameFilters(filters);
  if (invalid) throw new ApiError("invalid", invalid);
  const filtered = filterAndSortGames(source.items, filters);
  const page = parsePositivePage(params.get("page"));
  const pageSize = Math.max(1, Number(params.get("page_size")) || 24);
  return { items: filtered.slice((page - 1) * pageSize, page * pageSize), total: filtered.length, page, page_size: pageSize, release_id: source.release_id };
}

async function getStaticPlayers(params: URLSearchParams): Promise<PageResult<PlayerSummary>> {
  const season = params.get("season") ?? "S23";
  const source = await getSnapshotPlayers(season);
  const q = params.get("q") ?? "";
  const filtered = q ? source.items.filter((player) => player.name.toLocaleLowerCase().includes(q.toLocaleLowerCase())) : source.items;
  const page = parsePositivePage(params.get("page"));
  const pageSize = Math.max(1, Number(params.get("page_size")) || 48);
  return { items: filtered.slice((page - 1) * pageSize, page * pageSize), total: filtered.length, page, page_size: pageSize, release_id: source.release_id };
}

async function getStaticPlayer(id: string, params: URLSearchParams): Promise<PlayerDetail> {
  const manifest = await getSnapshotManifest();
  const defaultSeason = params.get("season") ?? manifest.seasons.at(-1)?.id ?? "";
  const start = params.get("season_start") ?? defaultSeason;
  const requestedEnd = params.get("season_end") ?? (params.has("season_start") ? "latest" : defaultSeason);
  const end = requestedEnd === "latest" ? manifest.seasons.at(-1)?.id ?? start : requestedEnd;
  const data = await getSnapshotPlayer(id, start, end);
  const minimum = Math.max(0, Number(params.get("minimum_appearances")) || 0);
  if (!minimum || !data.stats) return data;
  return applyMinimumAppearances(data, minimum);
}

function applyMinimumAppearances(player: PlayerDetail, minimum: number): PlayerDetail {
  const stats = player.stats;
  if (!stats) return player;
  const selectedId = player.id;
  const rankingBoards = { ...(stats.ranking_boards ?? {}) };
  const rankings = { ...(stats.rankings ?? {}) };
  const totalAppearancesByPlayer = new Map((rankingBoards.appearances ?? []).map((entry) => [entry.id, entry.appearances] as const));
  const updateBoard = (entries: RankingEntry[]) => filterRankingEntries(entries, { minimumAppearances: minimum, totalAppearancesByPlayer });
  const currentRanking = (entries: RankingEntry[] | undefined) => {
    const selected = entries?.find((entry) => entry.id === selectedId);
    return selected ? { rank: selected.rank, total: entries!.length, tied: selected.tied } : null;
  };
  for (const key of Object.keys(rankingBoards) as (keyof typeof rankingBoards)[]) {
    const source = rankingBoards[key];
    if (!source) { rankings[key] = null; continue; }
    const entries = updateBoard(source);
    rankingBoards[key] = entries;
    rankings[key] = currentRanking(entries);
  }
  const roles = stats.roles.map((role) => {
    const ranking_board = role.ranking_board ? updateBoard(role.ranking_board) : undefined;
    return { ...role, ranking_board, ranking: currentRanking(ranking_board) };
  });
  const boards = stats.boards?.map((board) => {
    const ranking_board = updateBoard(board.ranking_board);
    return { ...board, ranking_board, ranking: currentRanking(ranking_board) };
  });
  return { ...player, stats: { ...stats, ranking_boards: rankingBoards, rankings, roles, boards } };
}

async function getStaticStats(season: string, seasonEnd?: string) {
  const manifest = await getSnapshotManifest();
  const start = season;
  const requestedEnd = seasonEnd ?? start;
  const end = requestedEnd === "latest" ? manifest.seasons.at(-1)?.id ?? start : requestedEnd;
  return getSnapshotStats(start, end);
}
