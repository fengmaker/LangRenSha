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
  BluffReview,
  RankingEntry,
} from "@/lib/types";
import { cache } from "react";
import { filterAndSortGames, validateGameFilters, type GameFilters } from "@/lib/game-query";
import { filterRankingEntries } from "@/lib/ranking-filter";
import { filterBluffReview } from "@/lib/bluff-filter";
import { parsePositivePage } from "@/lib/query-state";
import { isStaticSite } from "@/lib/site-mode";
import { ApiError } from "@/lib/api-error";
export { ApiError } from "@/lib/api-error";
import {
  getSnapshotBluffReview, getSnapshotGame, getSnapshotGames, getSnapshotLeaderboard,
  getSnapshotManifest, getSnapshotOverview, getSnapshotPlayer, getSnapshotPlayers,
  getSnapshotReleases, getSnapshotStats,
} from "@/lib/snapshot-data";

const API_BASE_URL = (process.env.API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

async function request<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
      headers: { Accept: "application/json" },
    });
  } catch {
    throw new ApiError("unavailable", "数据服务暂时无法连接。请稍后刷新，或确认数据 API 已启动。");
  }

  if (response.status === 404) throw new ApiError("not-found", "没有找到这条档案记录。");
  if (!response.ok) throw new ApiError("unavailable", "暂时无法读取档案数据，请稍后刷新重试。");

  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError("invalid", "数据服务返回内容无法读取，请稍后重试。");
  }
}

export function getOverview() {
  if (isStaticSite) return getSnapshotOverview();
  return request<Overview>("/api/v1/overview");
}

export function getGames(params: URLSearchParams) {
  if (isStaticSite) return getStaticGames(params);
  return request<PageResult<GameSummary>>(`/api/v1/games?${params.toString()}`);
}

const getGameRequest = (id: string) => {
  if (isStaticSite) return getSnapshotGame(id);
  return request<GameDetail>(`/api/v1/games/${encodeURIComponent(id)}`);
}

export const getGame = cache(getGameRequest);

export function getPlayers(params: URLSearchParams) {
  if (isStaticSite) return getStaticPlayers(params);
  return request<PageResult<PlayerSummary>>(`/api/v1/players?${params.toString()}`);
}

const getPlayerRequest = (id: string, params: URLSearchParams) => {
  if (isStaticSite) return getStaticPlayer(id, params);
  return request<PlayerDetail>(`/api/v1/players/${encodeURIComponent(id)}?${params.toString()}`);
}

export const getPlayer = cache((id: string, season = "S23", phase = "all", seasonEnd?: string, minimumAppearances = 0) => {
  const params = new URLSearchParams({ season, phase });
  if (seasonEnd) { params.set("season_start", season); params.set("season_end", seasonEnd); }
  if (minimumAppearances !== 0) params.set("minimum_appearances", String(minimumAppearances));
  return getPlayerRequest(id, params);
});

export function getLeaderboard(season = "S23", phase: "all" | "finals_week" = "all") {
  if (isStaticSite) return getSnapshotLeaderboard(season, phase);
  const params = new URLSearchParams({ season, phase });
  return request<Leaderboard>(`/api/v1/leaderboard?${params.toString()}`);
}

export function getBluffReview(season = "S22", status: "all" | "pending" | "assistant_pending" = "pending", player = "") {
  if (isStaticSite) return getStaticBluffReview(season, status, player);
  return request<BluffReview>(`/api/v1/bluff-review?${new URLSearchParams({ season, status, player })}`);
}

export function getStats(season = "S22", seasonEnd?: string) {
  if (isStaticSite) return getStaticStats(season, seasonEnd);
  const params = new URLSearchParams({ season });
  if (seasonEnd) { params.set("season_start", season); params.set("season_end", seasonEnd); }
  return request<Stats>(`/api/v1/stats?${params.toString()}`);
}

export function getReleases() {
  if (isStaticSite) return getSnapshotReleases();
  return request<{ items: Release[] }>("/api/v1/releases");
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

async function getStaticBluffReview(season: string, status: "all" | "pending" | "assistant_pending", player: string) {
  const data = await getSnapshotBluffReview(season);
  return filterBluffReview(data, status, player);
}
