"use client";

import type { BluffReview, GameDetail, GameSummary, Leaderboard, Overview, PageResult, PlayerDetail, PlayerSummary, Release, Stats } from "@/lib/types";
import type { SnapshotManifest } from "@/lib/snapshot-data";
import { basePath } from "@/lib/site-mode";
import { ApiError } from "@/lib/api-error";

let manifestPromise: Promise<SnapshotManifest> | undefined;

async function requestJson<T>(url: string, cache?: RequestCache): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, { cache, headers: { Accept: "application/json" } });
  } catch {
    throw new ApiError("unavailable", "暂时无法读取档案数据，请稍后刷新重试。");
  }
  if (!response.ok) throw new ApiError(response.status === 404 ? "not-found" : "unavailable", `静态数据读取失败 (${response.status})。请稍后刷新重试。`);
  try {
    return await response.json() as T;
  } catch {
    throw new ApiError("invalid", "静态数据内容无法读取，请稍后刷新重试。");
  }
}

async function readSnapshotManifest(): Promise<SnapshotManifest> {
  const manifest = await requestJson<SnapshotManifest>(`${basePath}/data/manifest.json`, "no-store");
  if (!manifest.snapshot_id || !Array.isArray(manifest.seasons) || !manifest.seasons.length) throw new ApiError("invalid", "静态数据清单缺少快照或赛季信息。");
  return manifest;
}

export function fetchSnapshotManifest(): Promise<SnapshotManifest> {
  if (!manifestPromise) {
    // The manifest is mutable; release JSON is immutable and pinned for this document.
    const request = readSnapshotManifest();
    manifestPromise = request;
    void request.catch(() => {
      if (manifestPromise === request) manifestPromise = undefined;
    });
  }
  return manifestPromise;
}

export async function fetchStaticJson<T>(relativePath: string): Promise<T> {
  const safePath = relativePath.split("/").map(encodeURIComponent).join("/");
  const { snapshot_id: snapshotId } = await fetchSnapshotManifest();
  try {
    return await requestJson<T>(`${basePath}/data/releases/${encodeURIComponent(snapshotId)}/${safePath}`);
  } catch (error) {
    if (!(error instanceof ApiError) || error.kind !== "not-found") throw error;
    const latestManifest = await readSnapshotManifest();
    if (latestManifest.snapshot_id !== snapshotId) {
      window.location.reload();
      throw new ApiError("unavailable", "静态数据已更新，正在重新载入页面。");
    }
    throw new ApiError("not-found", `静态数据读取失败 (404)：${relativePath}`);
  }
}

export function staticRouteId(family: "games" | "players" | "seasons"): string {
  const pathname = basePath && window.location.pathname.startsWith(`${basePath}/`) ? window.location.pathname.slice(basePath.length) : window.location.pathname;
  const segments = pathname.split("/").filter(Boolean);
  if (segments[0] !== family || !segments[1] || segments[1] === "__static__") throw new ApiError("not-found", "没有找到这条档案记录。");
  return decodeURIComponent(segments[1]);
}

export function updateStaticQuery(query: URLSearchParams, replace = false) {
  const value = query.toString();
  const href = window.location.pathname + (value ? `?${value}` : "");
  if (replace) window.history.replaceState(null, "", href);
  else window.history.pushState(null, "", href);
}

export const fetchOverview = () => fetchStaticJson<Overview>("overview.json");
export const fetchGame = (id: string) => fetchStaticJson<GameDetail>(`games/${id}.json`);
export const fetchReleases = () => fetchStaticJson<{ items: Release[] }>("releases.json");
export const fetchGamesIndex = () => fetchStaticJson<{ release_id: string; total: number; items: (GameSummary & { search_text?: string })[] }>("games/index.json");
export const fetchPlayersForSeason = (season: string) => fetchStaticJson<PageResult<PlayerSummary>>(`players/by-season/${season}.json`);
export const fetchPlayerRange = (id: string, start: string, end: string) => fetchStaticJson<PlayerDetail>(`players/${id}/${start}--${end}.json`);
export const fetchStatsRange = (start: string, end: string) => fetchStaticJson<Stats>(`stats/${start}--${end}.json`);
export const fetchLeaderboard = (season: string, phase: "all" | "finals_week") => fetchStaticJson<Leaderboard>(`leaderboards/${season}/${phase}.json`);
export const fetchBluffReview = (season: string) => fetchStaticJson<BluffReview>(`bluff-review/${season}.json`);
