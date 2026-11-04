import type { Metadata } from "next";
import { Suspense } from "react";
import { getReleases, getStats } from "@/lib/api";
import { isStaticSite } from "@/lib/site-mode";
import { getSnapshotManifest } from "@/lib/snapshot-data";
import type { SearchParams } from "@/lib/types";
import { DataProblem } from "@/components/data-state";
import { PageIntro } from "@/components/page-intro";
import { StatsView } from "./stats-view";
import { StaticStatsBrowser } from "./static-stats-browser";

export const metadata: Metadata = { title: "数据说明", description: "按赛季范围查看身份分布、版型胜率与统计口径。" };
function first(value: string | string[] | undefined): string { return Array.isArray(value) ? (value[0] ?? "") : (value ?? ""); }

export default async function StatsPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  if (isStaticSite) {
    try {
      const manifest = await getSnapshotManifest();
      const available = manifest.seasons.map((item) => item.id);
      const initialStart = available.includes("S22") ? "S22" : available[0] ?? "";
      const [stats, releases] = await Promise.all([getStats(initialStart, "latest"), getReleases()]);
      return <Suspense fallback={<div className="page-wrap"><PageIntro title="数据说明" /></div>}><StaticStatsBrowser manifest={manifest} initialStart={initialStart} initialStats={stats} releases={releases} /></Suspense>;
    } catch (error) {
      return <div className="page-wrap"><PageIntro title="数据说明" /><DataProblem error={error} /></div>;
    }
  }

  const query = await searchParams;
  const legacySeason = first(query.season);
  const start = first(query.season_start) || legacySeason || "S22";
  const end = first(query.season_end) || (legacySeason && !first(query.season_start) ? start : "latest");
  try {
    const [stats, releases] = await Promise.all([getStats(start, end), getReleases()]);
    return <StatsView stats={stats} releases={releases} start={start} end={end} />;
  } catch (error) {
    return <div className="page-wrap"><PageIntro title="数据说明" /><DataProblem error={error} /></div>;
  }
}
