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
} from "@/lib/types";
import { cache } from "react";

const API_BASE_URL = (process.env.API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(readonly kind: "unavailable" | "not-found" | "invalid", message: string) {
    super(message);
    this.name = "ApiError";
  }
}

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
  return request<Overview>("/api/v1/overview");
}

export function getGames(params: URLSearchParams) {
  return request<PageResult<GameSummary>>(`/api/v1/games?${params.toString()}`);
}

const getGameRequest = (id: string) => {
  return request<GameDetail>(`/api/v1/games/${encodeURIComponent(id)}`);
}

export const getGame = cache(getGameRequest);

export function getPlayers(params: URLSearchParams) {
  return request<PageResult<PlayerSummary>>(`/api/v1/players?${params.toString()}`);
}

const getPlayerRequest = (id: string, params: URLSearchParams) => {
  return request<PlayerDetail>(`/api/v1/players/${encodeURIComponent(id)}?${params.toString()}`);
}

export const getPlayer = cache((id: string, season = "S23", phase = "all", seasonEnd?: string, minimumAppearances = 0) => {
  const params = new URLSearchParams({ season, phase });
  if (seasonEnd) { params.set("season_start", season); params.set("season_end", seasonEnd); }
  if (minimumAppearances !== 0) params.set("minimum_appearances", String(minimumAppearances));
  return getPlayerRequest(id, params);
});

export function getLeaderboard(season = "S23", phase: "all" | "finals_week" = "all") {
  const params = new URLSearchParams({ season, phase });
  return request<Leaderboard>(`/api/v1/leaderboard?${params.toString()}`);
}

export function getBluffReview(season = "S22", status: "all" | "pending" | "assistant_pending" = "pending", player = "") {
  return request<BluffReview>(`/api/v1/bluff-review?${new URLSearchParams({ season, status, player })}`);
}

export function getStats(season = "S22", seasonEnd?: string) {
  const params = new URLSearchParams({ season });
  if (seasonEnd) { params.set("season_start", season); params.set("season_end", seasonEnd); }
  return request<Stats>(`/api/v1/stats?${params.toString()}`);
}

export function getReleases() {
  return request<{ items: Release[] }>("/api/v1/releases");
}
