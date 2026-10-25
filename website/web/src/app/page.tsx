import Link from "next/link";
import { getOverview } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import { DataProblem } from "@/components/data-state";
import { GameArchiveList } from "@/components/game-archive-list";
import styles from "./home.module.css";

export default async function HomePage() {
  try {
    const data = await getOverview();
    const totalGames = data.totals.games || 1;
    return <div className={"page-wrap home-page " + styles.home}>
      <section className="home-hero">
        <div className="hero-copy"><h1>每一局，<br /><em>都有迹可循。</em></h1><p>把桌上的每一个座位、夜里的每一次选择、白天的每一张票，整理成可以查阅的赛事档案。</p><div className="hero-actions"><Link className="button button-primary" href="/games">浏览全部对局 <span>↗</span></Link><Link className="text-link" href="/leaderboard?season=S22&phase=all">查看积分榜 <span>→</span></Link><Link className="text-link" href="/stats">阅读数据说明 <span>→</span></Link></div></div>
        <div className="hero-graphic" aria-label="12座位档案索引">
          <div className="seat-orbit orbit-one" /><div className="seat-orbit orbit-two" />
          <div className="hero-seats">{Array.from({ length: 12 }, (_, i) => <span key={i} className={"hero-seat hero-seat-" + i}>{String(i + 1).padStart(2, "0")}</span>)}</div>
          <div className="hero-center"><span>S22</span></div>
        </div>
      </section>

      <section className="overview-section">
        <div className="section-heading"><h2>档案概览</h2></div>
        <div className="metric-grid">
          <article className="metric-card metric-feature"><span>已整理对局</span><strong>{formatNumber(data.totals.games)}</strong></article>
          <article className="metric-card"><span>比赛日</span><strong>{formatNumber(data.totals.days)}</strong></article>
          <article className="metric-card"><span>选手档案</span><strong>{formatNumber(data.totals.players)}</strong></article>
          <article className="metric-card"><span>票型 / 投票</span><strong>{formatNumber(data.totals.ballots)}<small className="metric-inline"> / {formatNumber(data.totals.votes)}</small></strong></article>
        </div>
      </section>

      <section className="overview-split">
        <div className="overview-block">
          <div className="section-heading compact"><h2>版型分布</h2><Link href="/stats" className="inline-link">查看数据 <span>→</span></Link></div>
          <div className="board-distribution">{data.boards.map((board, index) => <div className="board-row" key={board.code}><span className="board-order">{String(index + 1).padStart(2, "0")}</span><div className="board-row-main"><strong>{board.name}</strong><div className="bar-track"><span style={{ width: Math.max(0, Math.round(board.games / totalGames * 100)) + "%" }} /></div></div><b>{formatNumber(board.games)}</b></div>)}</div>
        </div>
        <div className="overview-block season-block">
          <div className="section-heading compact"><h2>赛季索引</h2></div>
          <div className="season-list">{data.seasons.map((season) => <Link href={"/seasons/" + encodeURIComponent(season.id)} key={season.id} className="season-row"><span className="season-code">{season.id}</span><span><strong>{season.name}</strong><small>{formatNumber(season.days)} 个比赛日</small></span><span className="season-count">{formatNumber(season.games)}<small>局</small></span><span className="row-arrow">↗</span></Link>)}</div>
        </div>
      </section>

      <section className="recent-section" aria-labelledby="recent-games-heading">
        <div className="section-heading"><h2 id="recent-games-heading">近期比赛</h2><Link className="button button-outline" href="/games">全部对局 <span>→</span></Link></div>
        <GameArchiveList games={data.recent_games ?? []} empty="暂无近期比赛。" />
      </section>
    </div>;
  } catch (error) {
    return <div className="page-wrap"><DataProblem error={error} /></div>;
  }
}
