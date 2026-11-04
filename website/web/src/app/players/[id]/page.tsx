import type { Metadata } from "next";
import { Suspense } from "react";
import { notFound } from "next/navigation";
import { ApiError, getPlayer } from "@/lib/api";
import { isStaticSite } from "@/lib/site-mode";
import type { SearchParams } from "@/lib/types";
import { DataProblem } from "@/components/data-state";
import { PlayerProfileView } from "./player-profile-view";
import { StaticPlayerBrowser } from "./static-player-browser";

type PlayerPageProps = { params: Promise<{ id: string }>; searchParams: Promise<SearchParams> };
function first(value: string | string[] | undefined): string { return Array.isArray(value) ? (value[0] ?? "") : (value ?? ""); }
function range(query: SearchParams) {
  const start = first(query.season_start) || first(query.season) || "S23";
  const end = first(query.season_end) || (first(query.season) && !first(query.season_start) ? start : "latest");
  const rawMinimum = first(query.minimum_appearances);
  const parsedMinimum = rawMinimum && /^\d+$/.test(rawMinimum) ? Number(rawMinimum) : 0;
  const minimumAppearances = Number.isSafeInteger(parsedMinimum) && parsedMinimum >= 0 ? parsedMinimum : 0;
  return { start, end, minimumAppearances };
}
function controlFlow(error: unknown): boolean {
  return typeof error === "object" && error !== null && "digest" in error && typeof error.digest === "string" && (error.digest.startsWith("NEXT_REDIRECT") || error.digest.startsWith("NEXT_NOT_FOUND"));
}

export const generateStaticParams = isStaticSite ? async () => [{ id: "__static__" }] : undefined;

export async function generateMetadata({ params, searchParams }: PlayerPageProps): Promise<Metadata> {
  if (isStaticSite) return { title: "选手档案" };
  const { id } = await params;
  try {
    const query = await searchParams;
    const { start, end, minimumAppearances } = range(query);
    const player = await getPlayer(id, start, "all", end, minimumAppearances);
    return { title: `${player.name} · 选手档案`, description: `${player.name} 的照片、胜率、竞选指标与对局记录。` };
  } catch (error) {
    if (controlFlow(error)) throw error;
    if (error instanceof ApiError && error.kind === "not-found") return { title: "选手未找到" };
    return { title: "选手档案" };
  }
}

export default async function PlayerDetailPage({ params, searchParams }: PlayerPageProps) {
  if (isStaticSite) {
    return <Suspense fallback={<div className="page-wrap" role="status">正在读取选手档案…</div>}><StaticPlayerBrowser /></Suspense>;
  }
  const { id } = await params;
  const query = await searchParams;
  const { start, end, minimumAppearances } = range(query);
  try {
    const player = await getPlayer(id, start, "all", end, minimumAppearances);
    return <PlayerProfileView player={player} start={start} end={end} minimumAppearances={player.scope?.minimum_appearances ?? minimumAppearances} />;
  } catch (error) {
    if (controlFlow(error)) throw error;
    if (error instanceof ApiError && error.kind === "not-found") notFound();
    return <div className="page-wrap"><DataProblem error={error} /></div>;
  }
}
