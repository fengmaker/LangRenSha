import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getGames, getOverview, getStats } from "@/lib/api";
import { isStaticSite } from "@/lib/site-mode";
import { DataProblem } from "@/components/data-state";

import { SeasonView } from "./season-view";
import { StaticSeasonBrowser } from "./static-season-browser";

function gamesParams(season: string, pageSize: number, phase?: string): URLSearchParams {
  const params = new URLSearchParams({ season, page: "1", page_size: String(pageSize) });
  if (phase) params.set("phase", phase);
  return params;
}

function safeSeasonId(id: string): string {
  return id.replace(/[^A-Za-z0-9_-]/g, "").slice(0, 16) || "档案";
}

export const generateStaticParams = isStaticSite ? async () => [{ id: "__static__" }] : undefined;

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  return { title: isStaticSite ? "赛季档案" : "赛季档案 " + safeSeasonId(id) };
}

export default async function SeasonPage({ params }: { params: Promise<{ id: string }> }) {
  if (isStaticSite) return <StaticSeasonBrowser />;
  const { id } = await params;
  let overview: Awaited<ReturnType<typeof getOverview>>;
  try {
    overview = await getOverview();
  } catch (error) {
    return <div className="page-wrap"><DataProblem error={error} /></div>;
  }

  const season = overview.seasons.find((item) => item.id === id);
  if (!season) notFound();

  let regular: Awaited<ReturnType<typeof getGames>>;
  let finalsWeek: Awaited<ReturnType<typeof getGames>>;
  let recent: Awaited<ReturnType<typeof getGames>>;
  let stats: Awaited<ReturnType<typeof getStats>>;
  try {
    [regular, finalsWeek, recent, stats] = await Promise.all([
      getGames(gamesParams(id, 1, "regular")),
      getGames(gamesParams(id, 1, "finals_week")),
      getGames(gamesParams(id, 12)),
      getStats(id),
    ]);
  } catch (error) {
    return <div className="page-wrap"><DataProblem error={error} /></div>;
  }

  return <SeasonView season={season} stats={stats} recent={recent.items} regularCount={regular.total} finalsCount={finalsWeek.total} />;
}
