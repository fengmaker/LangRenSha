import type { Metadata } from "next";
import { Suspense } from "react";
import { notFound } from "next/navigation";
import BluffReviewPage from "@/app/leaderboard/bluff-review/page";
import { isStaticSite } from "@/lib/site-mode";
import type { SearchParams } from "@/lib/types";
import { StaticBluffReviewBrowser } from "@/app/leaderboard/bluff-review/static-bluff-review-browser";

export const metadata: Metadata = { title: isStaticSite ? "悍跳推断与复核" : "S23 悍跳推断与复核" };

export const generateStaticParams = isStaticSite ? async () => [{ id: "__static__" }] : undefined;

export default async function S23BluffReview({ params, searchParams }: {
  params: Promise<{ id: string }>; searchParams: Promise<SearchParams>;
}) {
  if (isStaticSite) {
    return <Suspense fallback={<div className="page-wrap" role="status">正在读取悍跳复核资料…</div>}><StaticBluffReviewBrowser seasonRoute /></Suspense>;
  }
  const { id } = await params;
  if (id !== "S23") notFound();
  const query = await searchParams;
  return <BluffReviewPage searchParams={Promise.resolve({ ...query, season: "S23" })} />;
}
