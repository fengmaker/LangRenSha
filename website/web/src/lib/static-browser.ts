"use client";

import type { BluffReview, GameDetail, GameSummary, Leaderboard, Overview, PageResult, PlayerDetail, PlayerSummary, Release, Stats } from "@/lib/types";
import type { SnapshotManifest } from "@/lib/snapshot-data";
import { basePath, publicPath } from "@/lib/site-mode";
import { ApiError } from "@/lib/api-error";
import { restorePlayerRankings, type SharedPlayerRankings } from "@/lib/player-rankings";
import type { PlayerPhoto } from "@/lib/types";

let manifestPromise: Promise<SnapshotManifest> | undefined;
const playerRankings = new Map<string, Promise<SharedPlayerRankings>>();

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
  if (![1, 2].includes(manifest.schema_version) || !manifest.snapshot_id || !Array.isArray(manifest.seasons) || !manifest.seasons.length) throw new ApiError("invalid", "静态数据清单的格式、快照或赛季信息无效。");
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
function withPlayerPhotoThumbnail<T extends { photo?: PlayerPhoto | null }>(player: T, manifest: SnapshotManifest): T {
  if (!player.photo) return player;
  const thumbnail = manifest.player_photo_thumbnails?.[player.photo.url];
  return thumbnail ? { ...player, photo: { ...player.photo, url: thumbnail, original_url: player.photo.url } } : player;
}

function preloadPlayerPhoto(photo: PlayerPhoto | null | undefined) {
  if (!photo || typeof document === "undefined") return;
  const sources: { url: string; priority: "auto" | "high" }[] = photo.original_url
    ? [{ url: photo.url, priority: "auto" }, { url: photo.original_url, priority: "high" }]
    : [{ url: photo.url, priority: "high" }];
  for (const { url, priority } of sources) {
    const href = publicPath(url);
    const alreadyPreloaded = Array.from(document.head.querySelectorAll('link[rel="preload"][as="image"]'))
      .some((link) => link.getAttribute("href") === href);
    if (alreadyPreloaded) continue;
    const link = document.createElement("link");
    link.rel = "preload";
    link.as = "image";
    link.href = href;
    link.fetchPriority = priority;
    document.head.append(link);
  }
}

export async function fetchPlayersForSeason(season: string): Promise<PageResult<PlayerSummary>> {
  const [manifest, result] = await Promise.all([
    fetchSnapshotManifest(),
    fetchStaticJson<PageResult<PlayerSummary>>(`players/by-season/${season}.json`),
  ]);
  return { ...result, items: result.items.map((player) => withPlayerPhotoThumbnail(player, manifest)) };
}

export async function fetchPlayerRange(id: string, start: string, end: string): Promise<PlayerDetail> {
  const manifest = await fetchSnapshotManifest();
  const profile = fetchStaticJson<PlayerDetail>(`players/${id}/${start}--${end}.json`);
  if (manifest.schema_version === 1) {
    const detail = withPlayerPhotoThumbnail(await profile, manifest);
    preloadPlayerPhoto(detail.photo);
    return detail;
  }
  const range = `${start}--${end}`;
  let sharedRequest = playerRankings.get(range);
  if (!sharedRequest) {
    const request = fetchStaticJson<SharedPlayerRankings>(`rankings/${range}.json`);
    sharedRequest = request;
    playerRankings.set(range, request);
    void request.catch(() => {
      if (playerRankings.get(range) === request) playerRankings.delete(range);
    });
  }
  const detail = withPlayerPhotoThumbnail(await profile, manifest);
  preloadPlayerPhoto(detail.photo);
  const shared = await sharedRequest;
  return restorePlayerRankings(detail, shared);
}
export const fetchStatsRange = (start: string, end: string) => fetchStaticJson<Stats>(`stats/${start}--${end}.json`);
export const fetchLeaderboard = (season: string, phase: "all" | "finals_week") => fetchStaticJson<Leaderboard>(`leaderboards/${season}/${phase}.json`);
export const fetchBluffReview = (season: string) => fetchStaticJson<BluffReview>(`bluff-review/${season}.json`);
