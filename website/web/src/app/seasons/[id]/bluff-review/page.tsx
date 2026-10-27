import type { Metadata } from "next";
import { notFound } from "next/navigation";
import BluffReviewPage from "@/app/leaderboard/bluff-review/page";
import type { SearchParams } from "@/lib/types";

export const metadata: Metadata = { title: "S23 悍跳推断与复核" };

export default async function S23BluffReview({ params, searchParams }: {
  params: Promise<{ id: string }>; searchParams: Promise<SearchParams>;
}) {
  if ((await params).id !== "S23") notFound();
  const query = await searchParams;
  return <BluffReviewPage searchParams={Promise.resolve({ ...query, season: "S23" })} />;
}
