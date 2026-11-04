"use client";

import { ArchiveLink } from "@/components/archive-link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import type { Overview, PageResult, PlayerSummary } from "@/lib/types";
import { fetchPlayersForSeason } from "@/lib/static-browser";
import { publicPath } from "@/lib/site-mode";
import { parsePositivePage } from "@/lib/query-state";
import { Pagination } from "@/components/pagination";
import { PageIntro } from "@/components/page-intro";
import { formatNumber } from "@/lib/format";
import styles from "./players.module.css";

const PAGE_SIZE = 48;

export function StaticPlayersBrowser({ overview, initialSeason, initialPlayers }: { overview: Overview; initialSeason: string; initialPlayers: PageResult<PlayerSummary> }) {
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  const season = search.get("season") || initialSeason;
  const q = search.get("q") ?? "";
  const pageValue = search.get("page");
  const page = parsePositivePage(pageValue);
  const [players, setPlayers] = useState(initialPlayers);
  const [playersSeason, setPlayersSeason] = useState(initialSeason);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [queryText, setQueryText] = useState(q);
  const [draftSeason, setDraftSeason] = useState(season);

  useEffect(() => { setQueryText(q); setDraftSeason(season); }, [q, season]);
  useEffect(() => {
    if (season === playersSeason) return;
    let active = true;
    setLoading(true);
    setError("");
    fetchPlayersForSeason(season).then((data) => { if (active) { setPlayers(data); setPlayersSeason(season); } })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "无法读取选手索引。"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [season, playersSeason]);

  const result = useMemo(() => {
    const filtered = q ? players.items.filter((player) => player.name.toLocaleLowerCase().includes(q.toLocaleLowerCase())) : players.items;
    return { filtered, items: filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE), total: filtered.length };
  }, [players, q, page]);

  useEffect(() => {
    const lastPage = Math.max(1, Math.ceil(result.total / PAGE_SIZE));
    if ((pageValue !== null && String(page) !== pageValue) || page > lastPage) {
      const next = new URLSearchParams(search.toString()); next.set("page", String(lastPage));
      if (pageValue !== null && String(page) !== pageValue) next.delete("page");
      router.replace(`${pathname}?${next.toString()}`, { scroll: false });
    }
  }, [page, pageValue, result.total, search, router, pathname]);

  function setQuery(values: { q?: string; season?: string; page?: number }) {
    const next = new URLSearchParams(search.toString());
    if (values.q !== undefined) values.q ? next.set("q", values.q) : next.delete("q");
    if (values.season !== undefined) values.season ? next.set("season", values.season) : next.delete("season");
    if (values.page !== undefined) next.set("page", String(values.page)); else next.set("page", "1");
    next.set("phase", "all");
    router.push(`${pathname}?${next.toString()}`, { scroll: false });
  }

  function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setQuery({ q: queryText, season: draftSeason }); }
  const seasons = overview.seasons.some((item) => item.id === season) ? overview.seasons : [{ id: season, name: season, games: 0, days: 0 }, ...overview.seasons];
  const browserParams = new URLSearchParams(search.toString());
  browserParams.set("season", season); browserParams.set("phase", "all");

  return <div className={`page-wrap ${styles.directory}`}>
    <PageIntro title="选手索引" description="按赛季搜索选手并查看出场与胜率。" action={<ArchiveLink className="button button-outline" href={`/leaderboard?season=${encodeURIComponent(season)}&phase=all`}>查看积分榜 <span>→</span></ArchiveLink>} />
    <section className="filter-panel player-filter-panel"><form method="get" action={publicPath("/players")} className="player-search-form" onSubmit={submit}>
      <label className="filter-field filter-search"><span>选手姓名</span><input name="q" type="search" placeholder="搜索选手姓名" value={queryText} onChange={(event) => setQueryText(event.target.value)} /></label>
      <label className="filter-field"><span>赛季</span><select name="season" value={draftSeason} onChange={(event) => setDraftSeason(event.target.value)}>{seasons.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.id}</option>)}</select></label>
      <button className="button button-primary" type="submit">筛选选手 <span>→</span></button>{q || season !== initialSeason ? <ArchiveLink className="clear-link" href="/players">清除</ArchiveLink> : null}
    </form></section>
    <section className="player-directory" aria-busy={loading || undefined}>
      {error ? <div className="empty-state" role="alert"><p>{error}</p></div> : null}
      {loading ? <p role="status">正在读取选手索引…</p> : null}
      {!loading && !error ? result.items.length ? <div className="player-grid">{result.items.map((player) => <ArchiveLink href={`/players/${encodeURIComponent(player.id)}?season=${encodeURIComponent(season)}&phase=all`} className="player-card player-photo-card" key={player.id}>
        <div className="player-card-photo">{player.photo ? <img loading="lazy" decoding="async" src={publicPath(player.photo.url)} alt={`${player.name} · ${player.photo.season}`} /> : <span className="player-photo-placeholder">{player.name.slice(0, 1)}</span>}<span className="row-arrow">↗</span></div>
        <div className="player-card-copy"><h3>{player.name}</h3><p>{formatNumber(player.stats?.appearances ?? player.appearances)} 场出场{player.stats ? ` · ${formatNumber(player.stats.wins)} 胜 ${formatNumber(player.stats.losses)} 负` : ""}</p>{player.stats ? <div className="player-card-rate"><span>总胜率</span><strong>{typeof player.stats.total_win_rate.rate === "number" ? `${(player.stats.total_win_rate.rate * 100).toFixed(1)}%` : "—"}</strong></div> : null}</div>
      </ArchiveLink>)}</div> : <div className="empty-state"><span className="empty-number">—</span><p>没有找到匹配的选手档案。</p></div> : null}
      <Pagination page={page} pageSize={PAGE_SIZE} total={result.total} params={browserParams} />
    </section>
  </div>;
}
