"use client";

import { StaticData } from "@/components/static-data";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import type { Leaderboard, Overview } from "@/lib/types";
import { fetchLeaderboard, fetchSnapshotManifest, fetchOverview, updateStaticQuery } from "@/lib/static-browser";
import type { SnapshotManifest } from "@/lib/snapshot-data";
import { LeaderboardView } from "./leaderboard-view";

function LoadedLeaderboardBrowser({ initialSeason, initialData, overview, seasons }: { initialSeason: string; initialData: Leaderboard; overview: Overview; seasons: SnapshotManifest["seasons"] }) {
  const search = useSearchParams();
  const requestedSeason = search.get("season") || initialSeason;
  const availableSeason = seasons.some((item) => item.id === requestedSeason) ? requestedSeason : initialSeason;
  const season = seasons.find((item) => item.id === availableSeason)!;
  const requestedPhase = search.get("phase") === "finals_week" ? "finals_week" : "all";
  const phase = requestedPhase === "finals_week" && season.phases?.includes("finals_week") ? "finals_week" : "all";
  const [data, setData] = useState(initialData);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (requestedSeason !== availableSeason || (search.get("phase") === "finals_week" && phase !== "finals_week")) {
      const next = new URLSearchParams(search.toString());
      next.set("season", availableSeason); next.set("phase", phase);
      updateStaticQuery(next, true);
    }
  }, [requestedSeason, availableSeason, search, phase]);

  useEffect(() => {
    if (data.season === availableSeason && data.phase === phase) {
      setLoading(false); setError("");
      return;
    }
    let active = true;
    setLoading(true); setError("");
    fetchLeaderboard(availableSeason, phase).then((result) => { if (active) setData(result); })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "无法读取积分榜。"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [availableSeason, phase, data.season, data.phase]);

  if (error) return <div className="page-wrap" role="alert"><p>{error}</p><a href="">刷新页面</a></div>;
  if (loading || data.season !== availableSeason || data.phase !== phase) return <p className="page-wrap" role="status">正在载入积分榜…</p>;
  return <LeaderboardView data={data} overview={overview} season={availableSeason} phase={phase} availablePhases={season.phases} />;
}

async function loadLeaderboard() {
  const search = new URLSearchParams(window.location.search);
  const [manifest, overview] = await Promise.all([fetchSnapshotManifest(), fetchOverview()]);
  const requestedSeason = search.get("season");
  const initialSeason = manifest.seasons.some((item) => item.id === requestedSeason) ? requestedSeason! : manifest.seasons.at(-1)!.id;
  const season = manifest.seasons.find((item) => item.id === initialSeason)!;
  const requestedPhase = search.get("phase") === "finals_week" ? "finals_week" : "all";
  const initialPhase = requestedPhase === "finals_week" && season.phases?.includes("finals_week") ? "finals_week" : "all";
  const initialData = await fetchLeaderboard(initialSeason, initialPhase);
  return { initialSeason, initialData, overview, seasons: manifest.seasons };
}

export function StaticLeaderboardBrowser() {
  return <StaticData load={loadLeaderboard}>{(data) => <LoadedLeaderboardBrowser {...data} />}</StaticData>;
}
