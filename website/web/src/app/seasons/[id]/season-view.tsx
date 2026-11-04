import { ArchiveLink } from "@/components/archive-link";
import { GameArchiveList } from "@/components/game-archive-list";
import { PageIntro } from "@/components/page-intro";
import { formatNumber } from "@/lib/format";
import type { GameSummary, Overview, Stats } from "@/lib/types";

export function SeasonView({ season, stats, recent, regularCount, finalsCount }: {
  season: Overview["seasons"][number]; stats: Stats; recent: GameSummary[]; regularCount: number; finalsCount: number;
}) {
  const id = season.id;
  const boardTotal = stats.boards.reduce((sum, board) => sum + board.games, 0) || 1;
  const phaseLinks = [
    { label: "正赛", phase: "regular", count: regularCount, detail: "全部正赛对局" },
    { label: "决赛周", phase: "finals_week", count: finalsCount, detail: "全部决赛周对局" },
  ];

  return <div className="page-wrap season-page">
    <div className="breadcrumb"><ArchiveLink href="/">档案首页</ArchiveLink><span>/</span><span>赛季索引</span></div>
    <PageIntro title={season.name} description="查看本季对局、版型分布与阶段积分。" action={<span className="season-hero-code">{season.id}</span>} />
    <section className="season-summary-metrics">
      <article><span>对局</span><strong>{formatNumber(season.games)}</strong></article>
      <article><span>比赛日</span><strong>{formatNumber(season.days)}</strong></article>
      <article><span>版型</span><strong>{formatNumber(stats.boards.length)}</strong></article>
    </section>

    <section className="season-phase-section">
      <div className="section-heading"><h2>比赛阶段</h2></div>
      <div className="season-phase-grid">{phaseLinks.map((item) => <ArchiveLink key={item.phase} href={"/games?season=" + encodeURIComponent(id) + "&phase=" + encodeURIComponent(item.phase)} className="season-phase-card">
        <strong>{item.label}</strong><b>{formatNumber(item.count)} <span>局</span></b>
      </ArchiveLink>)}</div>
      <div className="season-leaderboard-links"><span>赛季积分与冠军</span><ArchiveLink href={`/leaderboard?season=${encodeURIComponent(id)}&phase=all`}>整季积分榜 <b>→</b></ArchiveLink><ArchiveLink href={`/leaderboard?season=${encodeURIComponent(id)}&phase=finals_week`}>决赛周冠军榜 <b>→</b></ArchiveLink></div>
      {id === "S23" ? <p><ArchiveLink className="button button-outline" href="/seasons/S23/bluff-review">S23 悍跳推断与复核 <span>→</span></ArchiveLink></p> : null}
    </section>

    <section className="season-board-section">
      <div className="section-heading"><h2>版型分布</h2></div>
      {stats.boards.length ? <div className="season-board-list">{stats.boards.map((board, index) => <div className="season-board-row" key={board.code}>
        <span className="board-order">{String(index + 1).padStart(2, "0")}</span><strong>{board.name}</strong><div className="bar-track"><span style={{ width: Math.max(0, Math.round(board.games / boardTotal * 100)) + "%" }} /></div><b>{formatNumber(board.games)}</b>
      </div>)}</div> : <div className="empty-state"><span className="empty-number">—</span><p>当前赛季还没有版型统计。</p></div>}
    </section>

    <section className="season-recent-section">
      <div className="section-heading"><h2>本季近期比赛</h2><ArchiveLink className="button button-outline" href={"/games?season=" + encodeURIComponent(id)}>全部对局 <span>→</span></ArchiveLink></div>
      <GameArchiveList games={recent} empty="当前赛季没有可展示的对局。" />
    </section>
    <details className="release-details"><summary>数据版本</summary><div className="release-detail-content"><span>{stats.release_id}</span></div></details>
  </div>;
}
