"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import type { BluffReview } from "@/lib/types";
import { fetchBluffReview } from "@/lib/static-browser";
import { filterBluffReview } from "@/lib/bluff-filter";
import { BluffReviewView } from "./bluff-review-view";

export function StaticBluffReviewBrowser({ initialSeason, initialData, seasons, forcedSeason }: { initialSeason: string; initialData: BluffReview; seasons: string[]; forcedSeason?: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  const requestedSeason = forcedSeason ?? search.get("season") ?? initialSeason;
  const rawSeason = search.get("season") ?? "";
  const season = seasons.includes(requestedSeason) ? requestedSeason : initialSeason;
  const rawStatus = search.get("status");
  const status: BluffReview["status"] = rawStatus === "all" ? "all" : rawStatus === "assistant_pending" ? "assistant_pending" : "pending";
  const rawPlayer = search.get("player") ?? "";
  const player = /^[A-Za-z0-9_-]{1,100}$/.test(rawPlayer) ? rawPlayer : "";
  const [data, setData] = useState(initialData);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    if (season === data.season) return;
    setError("");
    fetchBluffReview(season).then((result) => { if (active) setData(result); })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "无法读取悍跳复核资料。"); });
    return () => { active = false; };
  }, [season, data.season]);

  useEffect(() => {
    const validStatus = rawStatus === null || rawStatus === "all" || rawStatus === "pending" || rawStatus === "assistant_pending";
    if (requestedSeason === season && player === rawPlayer && validStatus && (!forcedSeason || !rawSeason || rawSeason === forcedSeason)) return;
    const next = new URLSearchParams(search.toString());
    next.set("season", season);
    if (player) next.set("player", player); else next.delete("player");
    if (!validStatus && rawStatus !== null) next.set("status", "pending");
    router.replace(pathname + "?" + next.toString(), { scroll: false });
  }, [requestedSeason, season, player, rawPlayer, rawStatus, forcedSeason, rawSeason, search, router, pathname]);

  return <>
    {error ? <div className="page-wrap" role="alert"><p>{error}</p></div> : null}
    <BluffReviewView data={filterBluffReview(data, status, player)} season={season} status={status} player={player} publicReadOnly />
  </>;
}
