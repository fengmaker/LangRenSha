"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import type { Leaderboard, Overview } from "@/lib/types";
import { fetchLeaderboard } from "@/lib/static-browser";
import type { SnapshotManifest } from "@/lib/snapshot-data";
import { LeaderboardView } from "./leaderboard-view";

export function StaticLeaderboardBrowser({ initialSeason, initialData, overview, seasons }: { initialSeason: string; initialData: Leaderboard; overview: Overview; seasons: SnapshotManifest["seasons"] }) {
  const router = useRouter();
  const pathname = usePathname();
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
      router.replace(`${pathname}?${next.toString()}`, { scroll: false });
    }
  }, [requestedSeason, availableSeason, search, phase, router, pathname]);

  useEffect(() => {
    if (data.season === availableSeason && data.phase === phase) return;
    let active = true;
    setLoading(true); setError("");
    fetchLeaderboard(availableSeason, phase).then((result) => { if (active) setData(result); })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "无法读取积分榜。"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [availableSeason, phase, data.season, data.phase]);

  return <>
    {error ? <div className="page-wrap" role="alert"><p>{error}</p></div> : null}
    {loading ? <p className="page-wrap" role="status">正在载入积分榜…</p> : null}
    <LeaderboardView data={data} overview={overview} season={availableSeason} phase={phase} availablePhases={season.phases} />
  </>;
}
