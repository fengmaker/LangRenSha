import Link from "next/link";
import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getGames, getOverview } from "@/lib/api";
import type { SearchParams } from "@/lib/types";
import { DataProblem } from "@/components/data-state";
import { GameArchiveList } from "@/components/game-archive-list";
import { Pagination } from "@/components/pagination";
import styles from "./games.module.css";

const PAGE_SIZE = 24;
export const metadata: Metadata = { title: "对局档案", description: "检索大师赛各赛季的对局、票型和选手记录。" };
function first(value: string | string[] | undefined): string { return Array.isArray(value) ? (value[0] ?? "") : (value ?? ""); }
function positiveInt(value: string, fallback: number): number { const n = Number(value); return Number.isInteger(n) && n > 0 ? n : fallback; }

function ArchiveIntro() {
  return <header className={styles.intro}><h1>对局档案</h1><p>按赛季、阶段、版型或选手，找到想看的对局。</p></header>;
}

export default async function GamesPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const query = await searchParams;
  const filters = {
    season: first(query.season),
    phase: first(query.phase),
    board: first(query.board),
    player: first(query.player),
    q: first(query.q),
  };
  const page = positiveInt(first(query.page), 1);
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value); });
  params.set("page", String(page));
  params.set("page_size", String(PAGE_SIZE));
  let data: Awaited<ReturnType<typeof getGames>>;
  let overview: Awaited<ReturnType<typeof getOverview>>;
  try {
    [data, overview] = await Promise.all([getGames(params), getOverview()]);
  } catch (error) {
    return <div className={"page-wrap " + styles.page}><ArchiveIntro /><DataProblem error={error} /></div>;
  }
  const pageSize = data.page_size || PAGE_SIZE;
  const lastPage = Math.max(1, Math.ceil(data.total / pageSize));
  if (data.total > 0 && page > lastPage) {
    params.set("page", String(lastPage));
    params.set("page_size", String(pageSize));
    redirect("/games?" + params.toString());
  }
  const browserParams = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => { if (value) browserParams.set(key, value); });
  return <div className={"page-wrap " + styles.page}>
    <ArchiveIntro />
    <section className={styles.filters} aria-label="对局筛选">
      <form method="get" action="/games" className={styles.form}>
        <label className={styles.search}><span>关键词</span><input name="q" type="search" placeholder="选手名、日期或对局编号" defaultValue={filters.q} /></label>
        <label><span>赛季</span><select name="season" aria-label="赛季" defaultValue={filters.season}><option value="">全部赛季</option>{overview.seasons.map((season) => <option key={season.id} value={season.id}>{season.id} · {season.name}</option>)}</select></label>
        <label><span>比赛阶段</span><select name="phase" aria-label="比赛阶段" defaultValue={filters.phase}><option value="">全部阶段</option><option value="regular">正赛</option><option value="finals_week">决赛周</option></select></label>
        <label><span>版型</span><select name="board" aria-label="版型" defaultValue={filters.board}><option value="">全部版型</option>{overview.boards.map((board) => <option key={board.code} value={board.code}>{board.name}</option>)}</select></label>
        <label><span>选手</span><input name="player" type="search" placeholder="输入选手姓名" defaultValue={filters.player} /></label>
        <div className={styles.actions}><button className="button button-primary" type="submit">检索对局</button><Link href="/games">清除条件</Link></div>
      </form>
    </section>
    <section className={styles.results} aria-labelledby="games-heading">
      <h2 id="games-heading">对局列表</h2>
      <GameArchiveList games={data.items} />
      <Pagination page={data.page} pageSize={data.page_size} total={data.total} params={browserParams} />
    </section>
  </div>;
}
