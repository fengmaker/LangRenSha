import Link from "next/link";
import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getPlayers } from "@/lib/api";
import type { SearchParams } from "@/lib/types";
import { DataProblem } from "@/components/data-state";
import { PageIntro } from "@/components/page-intro";
import { Pagination } from "@/components/pagination";
import { formatNumber } from "@/lib/format";
import styles from "./players.module.css";

const PAGE_SIZE = 48;
export const metadata: Metadata = { title: "选手索引", description: "检索大师赛选手档案、身份分布与相关对局。" };
function first(value: string | string[] | undefined): string { return Array.isArray(value) ? (value[0] ?? "") : (value ?? ""); }
function positiveInt(value: string): number { const n = Number(value); return Number.isInteger(n) && n > 0 ? n : 1; }

export default async function PlayersPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const query = await searchParams;
  const q = first(query.q);
  const season = first(query.season) || "S22";
  const phase = "all";
  const page = positiveInt(first(query.page));
  const params = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE), season, phase });
  if (q) params.set("q", q);
  let data: Awaited<ReturnType<typeof getPlayers>>;
  try {
    data = await getPlayers(params);
  } catch (error) {
    return <div className={`page-wrap ${styles.directory}`}><PageIntro title="选手索引" description="按赛季搜索选手并查看出场与胜率。" /><DataProblem error={error} /></div>;
  }
  const pageSize = data.page_size || PAGE_SIZE;
  const lastPage = Math.max(1, Math.ceil(data.total / pageSize));
  if (data.total > 0 && page > lastPage) {
    params.set("page", String(lastPage));
    params.set("page_size", String(pageSize));
    redirect("/players?" + params.toString());
  }
    const browserParams = new URLSearchParams();
    if (q) browserParams.set("q", q);
    browserParams.set("season", season);
    browserParams.set("phase", phase);
    return <div className={`page-wrap ${styles.directory}`}>
      <PageIntro title="选手索引" description="按赛季搜索选手并查看出场与胜率。" action={<Link className="button button-outline" href={`/leaderboard?season=${encodeURIComponent(season)}&phase=all`}>查看积分榜 <span>→</span></Link>} />
      <section className="filter-panel player-filter-panel"><form method="get" action="/players" className="player-search-form"><label className="filter-field filter-search"><span>选手姓名</span><input name="q" type="search" placeholder="搜索选手姓名" defaultValue={q} /></label><label className="filter-field"><span>赛季</span><input name="season" type="text" defaultValue={season} /></label><button className="button button-primary" type="submit">筛选选手 <span>→</span></button>{q || season !== "S22" || phase !== "all" ? <Link className="clear-link" href="/players">清除</Link> : null}</form></section>
      <section className="player-directory">
        {data.items.length ? <div className="player-grid">{data.items.map((player) => <Link href={`/players/${encodeURIComponent(player.id)}?season=${encodeURIComponent(season)}&phase=${phase}`} className="player-card player-photo-card" key={player.id}>
          <div className="player-card-photo">{player.photo ? <img loading="lazy" decoding="async" src={player.photo.url} alt={`${player.name} · ${player.photo.season}`} /> : <span className="player-photo-placeholder">{player.name.slice(0, 1)}</span>}<span className="row-arrow">↗</span></div>
          <div className="player-card-copy"><h3>{player.name}</h3><p>{formatNumber(player.stats?.appearances ?? player.appearances)} 场出场{player.stats ? ` · ${formatNumber(player.stats.wins)} 胜 ${formatNumber(player.stats.losses)} 负` : ""}</p>
          {player.stats ? <div className="player-card-rate"><span>总胜率</span><strong>{typeof player.stats.total_win_rate.rate === "number" ? `${(player.stats.total_win_rate.rate * 100).toFixed(1)}%` : "—"}</strong></div> : null}
          </div>
        </Link>)}</div> : <div className="empty-state"><span className="empty-number">—</span><p>没有找到匹配的选手档案。</p></div>}
        <Pagination page={data.page} pageSize={data.page_size} total={data.total} params={browserParams} />
      </section>
    </div>;
}
