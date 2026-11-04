import type { Metadata } from "next";
import { Suspense } from "react";
import { notFound } from "next/navigation";
import BluffReviewPage from "@/app/leaderboard/bluff-review/page";
import { getBluffReview } from "@/lib/api";
import { getSnapshotManifest } from "@/lib/snapshot-data";
import { isStaticSite } from "@/lib/site-mode";
import { DataProblem } from "@/components/data-state";
import { PageIntro } from "@/components/page-intro";
import type { SearchParams } from "@/lib/types";
import { StaticBluffReviewBrowser } from "@/app/leaderboard/bluff-review/static-bluff-review-browser";

export const metadata: Metadata = { title: "S23 悍跳推断与复核" };

export const generateStaticParams = isStaticSite ? async () => {
  const manifest = await getSnapshotManifest();
  return manifest.seasons.some((season) => season.id === "S23") ? [{ id: "S23" }] : [];
} : undefined;

export default async function S23BluffReview({ params, searchParams }: {
  params: Promise<{ id: string }>; searchParams: Promise<SearchParams>;
}) {
  const { id } = await params;
  if (id !== "S23") notFound();
  if (isStaticSite) {
    try {
      const manifest = await getSnapshotManifest();
      const data = await getBluffReview("S23", "all", "");
      return <Suspense fallback={<div className="page-wrap"><PageIntro title="S23 悍跳推断与复核" /></div>}><StaticBluffReviewBrowser initialSeason="S23" initialData={data} seasons={manifest.seasons.map((season) => season.id)} forcedSeason="S23" /></Suspense>;
    } catch (error) {
      return <div className="page-wrap"><PageIntro title="S23 悍跳推断与复核" /><DataProblem error={error} /></div>;
    }
  }
  const query = await searchParams;
  return <BluffReviewPage searchParams={Promise.resolve({ ...query, season: "S23" })} />;
}
