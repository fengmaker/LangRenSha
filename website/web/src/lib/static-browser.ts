"use client";

import type { BluffReview, GameSummary, Leaderboard, PageResult, PlayerDetail, PlayerSummary, Stats } from "@/lib/types";
import { basePath } from "@/lib/site-mode";

let snapshotIdPromise: Promise<string> | undefined;

async function getSnapshotId(): Promise<string> {
  if (!snapshotIdPromise) {
    snapshotIdPromise = fetch(`${basePath}/data/manifest.json`, { headers: { Accept: "application/json" } })
      .then(async (response) => {
        if (!response.ok) throw new Error(`静态数据清单读取失败 (${response.status})`);
        const manifest = await response.json() as { snapshot_id?: string };
        if (!manifest.snapshot_id) throw new Error("静态数据清单缺少 snapshot_id。");
        return manifest.snapshot_id;
      });
  }
  return snapshotIdPromise;
}

export async function fetchStaticJson<T>(relativePath: string): Promise<T> {
  const safePath = relativePath.split("/").map(encodeURIComponent).join("/");
  const snapshotId = await getSnapshotId();
  const response = await fetch(`${basePath}/data/releases/${encodeURIComponent(snapshotId)}/${safePath}`, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`静态数据读取失败 (${response.status})：${relativePath}`);
  return await response.json() as T;
}

export const fetchGamesIndex = () => fetchStaticJson<{ release_id: string; total: number; items: (GameSummary & { search_text?: string })[] }>("games/index.json");
export const fetchPlayersForSeason = (season: string) => fetchStaticJson<PageResult<PlayerSummary>>(`players/by-season/${season}.json`);
export const fetchPlayerRange = (id: string, start: string, end: string) => fetchStaticJson<PlayerDetail>(`players/${id}/${start}--${end}.json`);
export const fetchStatsRange = (start: string, end: string) => fetchStaticJson<Stats>(`stats/${start}--${end}.json`);
export const fetchLeaderboard = (season: string, phase: "all" | "finals_week") => fetchStaticJson<Leaderboard>(`leaderboards/${season}/${phase}.json`);
export const fetchBluffReview = (season: string) => fetchStaticJson<BluffReview>(`bluff-review/${season}.json`);
