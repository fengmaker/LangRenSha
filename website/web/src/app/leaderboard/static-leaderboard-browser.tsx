"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { fetchLeaderboard, updateStaticQuery } from "@/lib/static-browser";
import type { Leaderboard, Overview, SnapshotManifest } from "@/lib/types";
import { readLeaderboardSort, type LeaderboardSortField } from "./leaderboard-ranking";
import { LeaderboardView } from "./leaderboard-view";

function LeaderboardQuery({ onChange }: { onChange: (query: string) => void }) {
  const search = useSearchParams();
  useEffect(() => onChange(search.toString()), [onChange, search]);
  return null;
}

export function StaticLeaderboardBrowser({ initialData, snapshotId, seasons, seasonOptions }: {
  initialData: Leaderboard;
  snapshotId: string;
  seasons: SnapshotManifest["seasons"];
  seasonOptions: Overview["seasons"];
}) {
  const [queryString, setQueryString] = useState("");
  const query = useMemo(() => new URLSearchParams(queryString), [queryString]);
  const [loaded, setLoaded] = useState<Leaderboard>();
  const [failure, setFailure] = useState<{ season: string; phase: Leaderboard["phase"]; message: string }>();

  const requestedSeason = query.get("season") || initialData.season;
  const selectedSeason = seasons.find(({ id }) => id === requestedSeason) ?? seasons.at(-1)!;
  const season = selectedSeason.id;
  const phase = query.get("phase") === "finals_week" && selectedSeason.phases?.includes("finals_week") ? "finals_week" : "all";
  const sort = readLeaderboardSort(query.get("sort"));
  const data = [initialData, loaded].find((board) => board?.season === season && board.phase === phase);
  const error = failure?.season === season && failure.phase === phase ? failure.message : null;

  useEffect(() => {
    if (requestedSeason !== season || (query.get("phase") === "finals_week" && phase !== "finals_week")) {
      const next = new URLSearchParams(query);
      next.set("season", season);
      next.set("phase", phase);
      updateStaticQuery(next, true);
    }
  }, [requestedSeason, season, query, phase]);

  useEffect(() => {
    if (data) return;
    let active = true;
    setFailure(undefined);
    fetchLeaderboard(snapshotId, season, phase)
      .then((result) => { if (active) setLoaded(result); })
      .catch((reason: unknown) => {
        if (active) setFailure({ season, phase, message: reason instanceof Error ? reason.message : "无法读取积分榜。" });
      });
    return () => { active = false; };
  }, [snapshotId, season, phase, data]);

  function changeSort(field: LeaderboardSortField) {
    const next = new URLSearchParams(window.location.search);
    next.set("season", season);
    next.set("phase", phase);
    if (field === "points") next.delete("sort");
    else next.set("sort", field);
    updateStaticQuery(next);
  }

  return <>
    <Suspense><LeaderboardQuery onChange={setQueryString} /></Suspense>
    {error ? <div className="page-wrap" role="alert"><p>{error}</p><a href="">刷新页面</a></div>
      : data ? <LeaderboardView data={data} seasonOptions={seasonOptions} availablePhases={selectedSeason.phases}
        sortField={sort} onSort={changeSort} snapshotId={snapshotId} />
        : <p className="page-wrap" role="status">正在载入积分榜…</p>}
  </>;
}
