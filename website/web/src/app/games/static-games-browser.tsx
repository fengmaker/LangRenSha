"use client";

import { ArchiveLink } from "@/components/archive-link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import type { GameSummary, Overview, PageResult } from "@/lib/types";
import { filterAndSortGames, validateGameFilters } from "@/lib/game-query";
import { parsePositivePage } from "@/lib/query-state";
import { publicPath } from "@/lib/site-mode";
import { GameArchiveList } from "@/components/game-archive-list";
import { Pagination } from "@/components/pagination";
import styles from "./games.module.css";

type IndexedGame = GameSummary & { search_text?: string };
const PAGE_SIZE = 24;

export function StaticGamesBrowser({ games, overview }: { games: { release_id: string; items: IndexedGame[] }; overview: Overview }) {
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  const [filters, setFilters] = useState({
    q: search.get("q") ?? "", season: search.get("season") ?? "", phase: search.get("phase") ?? "",
    board: search.get("board") ?? "", player: search.get("player") ?? "", date_from: search.get("date_from") ?? "", date_to: search.get("date_to") ?? "",
  });
  const pageValue = search.get("page");
  const page = parsePositivePage(pageValue);
  const applied = {
    q: search.get("q") || undefined, season: search.get("season") || undefined, phase: search.get("phase") || undefined,
    board: search.get("board") || undefined, player: search.get("player") || undefined,
    date_from: search.has("date_from") ? search.get("date_from") ?? "" : undefined,
    date_to: search.has("date_to") ? search.get("date_to") ?? "" : undefined,
  };
  const validationError = validateGameFilters(applied);

  useEffect(() => setFilters({
    q: search.get("q") ?? "", season: search.get("season") ?? "", phase: search.get("phase") ?? "",
    board: search.get("board") ?? "", player: search.get("player") ?? "", date_from: search.get("date_from") ?? "", date_to: search.get("date_to") ?? "",
  }), [search]);

  const result = useMemo<PageResult<GameSummary>>(() => {
    const filtered = filterAndSortGames(games.items, applied);
    const size = Math.min(100, PAGE_SIZE);
    return { items: filtered.slice((page - 1) * size, page * size), total: filtered.length, page, page_size: size, release_id: games.release_id };
  }, [games, applied.q, applied.season, applied.phase, applied.board, applied.player, applied.date_from, applied.date_to, page]);

  useEffect(() => {
    if (validationError) return;
    const lastPage = Math.max(1, Math.ceil(result.total / result.page_size));
    if ((pageValue !== null && String(page) !== pageValue) || page > lastPage) {
      const next = new URLSearchParams(search.toString());
      if (pageValue !== null && String(page) !== pageValue) next.delete("page");
      else next.set("page", String(lastPage));
      router.replace(`${pathname}?${next.toString()}`, { scroll: false });
    }
  }, [page, pageValue, result.total, result.page_size, validationError, search, router, pathname]);

  function updateUrl(nextValues: Record<string, string>, replace = false) {
    const next = new URLSearchParams(search.toString());
    for (const [key, value] of Object.entries(nextValues)) value ? next.set(key, value) : next.delete(key);
    next.set("page", "1");
    const href = `${pathname}?${next.toString()}`;
    replace ? router.replace(href, { scroll: false }) : router.push(href, { scroll: false });
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    updateUrl(filters);
  }

  return <>
    <section className={styles.filters} aria-label="对局筛选">
      <form method="get" action={publicPath("/games")} className={styles.form} onSubmit={submit}>
        <label className={styles.search}><span>关键词</span><input name="q" type="search" maxLength={120} placeholder="选手名、日期或对局编号" value={filters.q} onChange={(event) => setFilters({ ...filters, q: event.target.value })} /></label>
        <label><span>赛季</span><select name="season" aria-label="赛季" value={filters.season} onChange={(event) => setFilters({ ...filters, season: event.target.value })}><option value="">全部赛季</option>{overview.seasons.map((season) => <option key={season.id} value={season.id}>{season.id} · {season.name}</option>)}</select></label>
        <label><span>比赛阶段</span><select name="phase" aria-label="比赛阶段" value={filters.phase} onChange={(event) => setFilters({ ...filters, phase: event.target.value })}><option value="">全部阶段</option><option value="regular">正赛</option><option value="finals_week">决赛周</option></select></label>
        <label><span>版型</span><select name="board" aria-label="版型" value={filters.board} onChange={(event) => setFilters({ ...filters, board: event.target.value })}><option value="">全部版型</option>{overview.boards.map((board) => <option key={board.code} value={board.code}>{board.name}</option>)}</select></label>
        <label><span>选手</span><input name="player" type="search" maxLength={120} placeholder="输入选手姓名" value={filters.player} onChange={(event) => setFilters({ ...filters, player: event.target.value })} /></label>
        <label><span>开始日期</span><input name="date_from" type="date" value={filters.date_from} onChange={(event) => setFilters({ ...filters, date_from: event.target.value })} /></label>
        <label><span>截止日期</span><input name="date_to" type="date" min={filters.date_from || undefined} value={filters.date_to} onChange={(event) => setFilters({ ...filters, date_to: event.target.value })} /></label>
        <div className={styles.actions}><button className="button button-primary" type="submit">检索对局</button><ArchiveLink href="/games">清除条件</ArchiveLink></div>
      </form>
    </section>
    <section className={styles.results} aria-labelledby="games-heading"><h2 id="games-heading">对局列表</h2>{validationError ? <div className="empty-state" role="alert"><p>{validationError}</p><p>请修正筛选条件后再检索。</p></div> : <><GameArchiveList games={result.items} /><Pagination page={result.page} pageSize={result.page_size} total={result.total} params={new URLSearchParams(search.toString())} /></>}</section>
  </>;
}
