"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import type { PlayerDetail } from "@/lib/types";
import type { SnapshotManifest } from "@/lib/snapshot-data";
import { fetchPlayerRange } from "@/lib/static-browser";
import { PlayerProfileView } from "./player-profile-view";

function nonNegativeInteger(value: string | null): number {
  if (value === null || !/^\d+$/.test(value)) return 0;
  const number = Number(value);
  return Number.isSafeInteger(number) && number >= 0 ? number : 0;
}

export function StaticPlayerBrowser({ id, defaultStart, manifest, initialPlayer }: { id: string; defaultStart: string; manifest: SnapshotManifest; initialPlayer: PlayerDetail }) {
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  const seasons = manifest.seasons.map((item) => item.id);
  const latest = seasons.at(-1) ?? defaultStart;
  const legacySeason = search.get("season");
  const rawStart = search.get("season_start") || legacySeason || defaultStart;
  const start = seasons.includes(rawStart) ? rawStart : defaultStart;
  const rawEnd = search.get("season_end") || (legacySeason && !search.get("season_start") ? start : "latest");
  let end = rawEnd === "latest" ? latest : seasons.includes(rawEnd) ? rawEnd : latest;
  if (seasons.indexOf(end) < seasons.indexOf(start)) end = start;
  const minimum = nonNegativeInteger(search.get("minimum_appearances"));
  const [player, setPlayer] = useState(initialPlayer);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const next = new URLSearchParams(search.toString());
    let changed = false;
    if (rawStart !== start) { next.set("season_start", start); changed = true; }
    if (rawEnd !== "latest" && search.get("season_end") && rawEnd !== end) { next.set("season_end", end); changed = true; }
    if (search.get("minimum_appearances") && String(minimum) !== search.get("minimum_appearances")) {
      if (minimum) next.set("minimum_appearances", String(minimum)); else next.delete("minimum_appearances");
      changed = true;
    }
    if (changed) router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  }, [rawStart, start, rawEnd, end, minimum, search, router, pathname]);

  useEffect(() => {
    const resolvedEnd = end === "latest" ? latest : end;
    if (player.scope?.season_start === start && player.scope?.season_end === resolvedEnd) return;
    let active = true;
    setLoading(true); setError("");
    fetchPlayerRange(id, start, resolvedEnd).then((data) => { if (active) setPlayer(data); })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "无法读取选手统计数据。"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [id, start, end, latest, player.scope?.season_start, player.scope?.season_end]);

  function applyRange(nextStart: string, nextEnd: string, nextMinimum: number) {
    const query = new URLSearchParams(search.toString());
    query.delete("season");
    query.set("season_start", nextStart);
    query.set("season_end", nextEnd);
    if (nextMinimum > 0) query.set("minimum_appearances", String(nextMinimum));
    else query.delete("minimum_appearances");
    router.push(`${pathname}?${query.toString()}`, { scroll: false });
  }

  return <>
    {error ? <div className="page-wrap" role="alert"><p>{error}</p></div> : null}
    {loading ? <p className="page-wrap" role="status">正在载入选手统计范围…</p> : null}
    <PlayerProfileView player={player} start={start} end={rawEnd} minimumAppearances={minimum} onRangeChange={applyRange} />
  </>;
}
