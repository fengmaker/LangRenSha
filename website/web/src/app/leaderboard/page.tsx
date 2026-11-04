import type { Metadata } from "next";
import { Suspense } from "react";
import { getLeaderboard, getOverview } from "@/lib/api";
import { isStaticSite } from "@/lib/site-mode";
import { getSnapshotManifest } from "@/lib/snapshot-data";
import { DataProblem } from "@/components/data-state";
import { PageIntro } from "@/components/page-intro";
import type { SearchParams } from "@/lib/types";
import { LeaderboardView } from "./leaderboard-view";
import { StaticLeaderboardBrowser } from "./static-leaderboard-browser";

export const metadata: Metadata = { title: "赛季积分榜", description: "按赛季和比赛阶段查看选手积分、出场、胜率与投票表现。" };
function first(value: string | string[] | undefined): string { return Array.isArray(value) ? (value[0] ?? "") : (value ?? ""); }
function safeSeason(value: string, fallback: string): string { return /^[A-Za-z0-9_-]{1,20}$/.test(value) ? value : fallback; }
function safePhase(value: string): "all" | "finals_week" { return value === "finals_week" ? "finals_week" : "all"; }

export default async function LeaderboardPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  if (isStaticSite) {
    try {
      const [manifest, overview] = await Promise.all([getSnapshotManifest(), getOverview()]);
      const initialSeason = manifest.seasons.at(-1)?.id ?? overview.seasons.at(-1)?.id ?? "";
      const initialData = await getLeaderboard(initialSeason, "all");
      return <Suspense fallback={<div className="page-wrap"><PageIntro title="赛季积分榜" /></div>}><StaticLeaderboardBrowser initialSeason={initialSeason} initialData={initialData} overview={overview} seasons={manifest.seasons} /></Suspense>;
    } catch (error) {
      return <div className="page-wrap"><PageIntro title="赛季积分榜" /><DataProblem error={error} /></div>;
    }
  }

  const query = await searchParams;
  let data: Awaited<ReturnType<typeof getLeaderboard>>;
  let overview: Awaited<ReturnType<typeof getOverview>>;
  try {
    overview = await getOverview();
    const fallback = overview.seasons.at(-1)?.id ?? "S23";
    const season = safeSeason(first(query.season) || fallback, fallback);
    const phase = safePhase(first(query.phase));
    data = await getLeaderboard(season, phase);
    return <LeaderboardView data={data} overview={overview} season={season} phase={phase} />;
  } catch (error) {
    return <div className="page-wrap"><PageIntro title="赛季积分榜" /><DataProblem error={error} /></div>;
  }
}
