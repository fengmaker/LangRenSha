"use client";

import { StaticData } from "@/components/static-data";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import type { BluffReview } from "@/lib/types";
import { fetchBluffReview, fetchSnapshotManifest, staticRouteId, updateStaticQuery } from "@/lib/static-browser";
import { filterBluffReview } from "@/lib/bluff-filter";
import { BluffReviewView } from "./bluff-review-view";

function LoadedBluffReviewBrowser({ initialSeason, initialData, seasons, forcedSeason }: { initialSeason: string; initialData: BluffReview; seasons: string[]; forcedSeason?: string }) {
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
    if (season === data.season) { setError(""); return; }
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
    updateStaticQuery(next, true);
  }, [requestedSeason, season, player, rawPlayer, rawStatus, forcedSeason, rawSeason, search]);

  if (error) return <div className="page-wrap" role="alert"><p>{error}</p><a href="">刷新页面</a></div>;
  if (data.season !== season) return <p className="page-wrap" role="status">正在读取悍跳复核资料…</p>;
  return <BluffReviewView data={filterBluffReview(data, status, player)} season={season} status={status} player={player} publicReadOnly />;
}

async function loadBluffReview(seasonRoute: boolean) {
  const manifest = await fetchSnapshotManifest();
  const seasons = manifest.seasons.map((season) => season.id);
  const forcedSeason = seasonRoute ? staticRouteId("seasons") : undefined;
  const initialSeason = forcedSeason ?? (seasons.includes("S22") ? "S22" : seasons[0]);
  const initialData = await fetchBluffReview(initialSeason);
  document.title = `${initialSeason} 悍跳推断与复核 · 大师赛档案`;
  return { initialSeason, initialData, seasons, forcedSeason };
}

const loadGeneralReview = () => loadBluffReview(false);
const loadSeasonReview = () => loadBluffReview(true);

export function StaticBluffReviewBrowser({ seasonRoute = false }: { seasonRoute?: boolean }) {
  return <StaticData load={seasonRoute ? loadSeasonReview : loadGeneralReview}>{(data) => <LoadedBluffReviewBrowser {...data} />}</StaticData>;
}
