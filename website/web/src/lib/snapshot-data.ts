import "server-only";

import { readFile } from "node:fs/promises";
import path from "node:path";
import type { BluffReview, GameDetail, GameSummary, Leaderboard, Overview, PageResult, PlayerDetail, PlayerSummary, Release, Stats } from "@/lib/types";
import { restorePlayerRankings, type SharedPlayerRankings } from "@/lib/player-rankings";

export type SnapshotManifest = {
  schema_version: number;
  snapshot_id: string;
  build_id?: string | null;
  release_id: string;
  source_hash?: string;
  player_photo_thumbnails?: Record<string, string>;
  seasons: { id: string; game_count: number; phases?: string[] }[];
  ranges: { start: string; end: string; seasons: string[] }[];
  complete: boolean;
  partial?: { enabled: boolean; season?: string; game_id?: string; player_id?: string };
};

const snapshotRoot = path.join(process.cwd(), ".static-snapshot", "data");

export async function readSnapshotJson<T>(relativePath: string): Promise<T> {
  const safePath = relativePath.replace(/\\/g, "/");
  if (safePath.startsWith("/") || safePath.split("/").some((part) => part === "..")) {
    throw new Error("静态快照路径无效。");
  }
  const body = await readFile(path.join(snapshotRoot, safePath), "utf8");
  return JSON.parse(body) as T;
}

export async function getSnapshotManifest(): Promise<SnapshotManifest> {
  return readSnapshotJson<SnapshotManifest>("manifest.json");
}

async function releaseDir(): Promise<string> {
  const manifest = await getSnapshotManifest();
  if (!manifest.snapshot_id) throw new Error("静态快照缺少 snapshot_id。");
  return `releases/${manifest.snapshot_id}`;
}

export async function getSnapshotOverview() {
  return readSnapshotJson<Overview>(`${await releaseDir()}/overview.json`);
}

export async function getSnapshotGames() {
  return readSnapshotJson<{ release_id: string; total: number; items: (GameSummary & { search_text?: string })[] }>(`${await releaseDir()}/games/index.json`);
}

export async function getSnapshotGame(id: string) {
  return readSnapshotJson<GameDetail>(`${await releaseDir()}/games/${encodeURIComponent(id)}.json`);
}

export async function getSnapshotPlayers(season: string) {
  return readSnapshotJson<PageResult<PlayerSummary>>(`${await releaseDir()}/players/by-season/${encodeURIComponent(season)}.json`);
}

export async function getSnapshotPlayerIndex() {
  return readSnapshotJson<{ release_id: string; seasons: string[]; items: { id: string; name: string }[] }>(`${await releaseDir()}/players/index.json`);
}

export async function getSnapshotPlayer(id: string, start: string, end: string) {
  const manifest = await getSnapshotManifest();
  const root = `releases/${manifest.snapshot_id}`;
  const range = `${encodeURIComponent(start)}--${encodeURIComponent(end)}`;
  const profile = readSnapshotJson<PlayerDetail>(`${root}/players/${encodeURIComponent(id)}/${range}.json`);
  if (manifest.schema_version === 1) return profile;
  const [detail, shared] = await Promise.all([
    profile, readSnapshotJson<SharedPlayerRankings>(`${root}/rankings/${range}.json`),
  ]);
  return restorePlayerRankings(detail, shared);
}

export async function getSnapshotLeaderboard(season: string, phase: "all" | "finals_week") {
  return readSnapshotJson<Leaderboard>(`${await releaseDir()}/leaderboards/${encodeURIComponent(season)}/${phase}.json`);
}

export async function getSnapshotBluffReview(season: string) {
  return readSnapshotJson<BluffReview>(`${await releaseDir()}/bluff-review/${encodeURIComponent(season)}.json`);
}

export async function getSnapshotStats(start: string, end: string) {
  return readSnapshotJson<Stats>(`${await releaseDir()}/stats/${encodeURIComponent(start)}--${encodeURIComponent(end)}.json`);
}

export async function getSnapshotReleases(): Promise<{ items: Release[] }> {
  return readSnapshotJson<{ items: Release[] }>(`${await releaseDir()}/releases.json`);
}
