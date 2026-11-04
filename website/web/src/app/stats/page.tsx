import type { Metadata } from "next";
import { Suspense } from "react";
import { getReleases, getStats } from "@/lib/api";
import { isStaticSite } from "@/lib/site-mode";
import type { SearchParams } from "@/lib/types";
import { DataProblem } from "@/components/data-state";
import { PageIntro } from "@/components/page-intro";
import { StatsView } from "./stats-view";
import { StaticStatsBrowser } from "./static-stats-browser";

export const metadata: Metadata = { title: "数据说明", description: "按赛季范围查看身份分布、版型胜率与统计口径。" };
function first(value: string | string[] | undefined): string { return Array.isArray(value) ? (value[0] ?? "") : (value ?? ""); }

export default async function StatsPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  if (isStaticSite) {
    return <Suspense fallback={<div className="page-wrap" role="status">正在读取统计数据…</div>}><StaticStatsBrowser /></Suspense>;
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
