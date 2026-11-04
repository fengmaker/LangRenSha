import type { Metadata } from "next";
import { Suspense } from "react";
import { getBluffReview } from "@/lib/api";
import { isStaticSite } from "@/lib/site-mode";
import { DataProblem } from "@/components/data-state";
import { PageIntro } from "@/components/page-intro";
import type { BluffReview, SearchParams } from "@/lib/types";
import { BluffReviewView } from "./bluff-review-view";
import { StaticBluffReviewBrowser } from "./static-bluff-review-browser";

export const metadata: Metadata = { title: "悍跳推断与复核" };
function first(value: string | string[] | undefined) { return Array.isArray(value) ? value[0] ?? "" : value ?? ""; }

export default async function BluffReviewPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  if (isStaticSite) {
    return <Suspense fallback={<div className="page-wrap" role="status">正在读取悍跳复核资料…</div>}><StaticBluffReviewBrowser /></Suspense>;
  }
  const query = await searchParams;
  const rawSeason = first(query.season) || "S22";
  const season = /^[A-Za-z0-9_-]{1,20}$/.test(rawSeason) ? rawSeason : "S22";
  const status: BluffReview["status"] = first(query.status) === "all" ? "all" : first(query.status) === "assistant_pending" ? "assistant_pending" : "pending";
  const rawPlayer = first(query.player);
  const player = /^[A-Za-z0-9_-]{1,100}$/.test(rawPlayer) ? rawPlayer : "";
  try {
    const data = await getBluffReview(season, status, player);
    return <BluffReviewView data={data} season={season} status={status} player={player} />;
  } catch (error) {
    return <div className="page-wrap"><PageIntro title="悍跳推断与复核" description="按逐局原文证据回查悍跳归属与成功结果。" /><DataProblem error={error} /></div>;
  }
}
