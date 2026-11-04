"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import type { Release, Stats } from "@/lib/types";
import type { SnapshotManifest } from "@/lib/snapshot-data";
import { fetchStatsRange } from "@/lib/static-browser";
import { StatsView } from "./stats-view";

export function StaticStatsBrowser({ manifest, initialStart, initialStats, releases }: { manifest: SnapshotManifest; initialStart: string; initialStats: Stats; releases: { items: Release[] } }) {
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  const available = manifest.seasons.map((item) => item.id);
  const latest = available.at(-1) ?? initialStart;
  const legacySeason = search.get("season");
  const rawStart = search.get("season_start") || legacySeason || initialStart;
  const start = available.includes(rawStart) ? rawStart : initialStart;
  const rawEnd = search.get("season_end") || (legacySeason && !search.get("season_start") ? start : "latest");
  let end = rawEnd === "latest" ? latest : available.includes(rawEnd) ? rawEnd : latest;
  if (available.indexOf(end) < available.indexOf(start)) end = start;
  const [stats, setStats] = useState(initialStats);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const next = new URLSearchParams(search.toString());
    let changed = false;
    if (rawStart !== start) { next.set("season_start", start); changed = true; }
    if (rawEnd !== "latest" && rawEnd !== end) { next.set("season_end", end); changed = true; }
    if (changed) router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  }, [rawStart, start, rawEnd, end, search, router, pathname]);

  useEffect(() => {
    if (stats.scope.season_start === start && stats.scope.season_end === end) return;
    let active = true;
    setLoading(true); setError("");
    fetchStatsRange(start, end).then((data) => { if (active) setStats(data); })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "无法读取统计数据。"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [start, end, stats.scope.season_start, stats.scope.season_end]);

  function applyRange(nextStart: string, nextEnd: string) {
    const query = new URLSearchParams(search.toString());
    query.delete("season"); query.set("season_start", nextStart); query.set("season_end", nextEnd);
    router.push(`${pathname}?${query.toString()}`, { scroll: false });
  }

  return <>
    {error ? <div className="page-wrap" role="alert"><p>{error}</p></div> : null}
    {loading ? <p className="page-wrap" role="status">正在载入统计范围…</p> : null}
    <StatsView stats={stats} releases={releases} start={start} end={rawEnd} onRangeChange={applyRange} />
  </>;
}
