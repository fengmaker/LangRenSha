import Link from "next/link";
import type { Metadata } from "next";
import { getLeaderboard, getOverview } from "@/lib/api";
import { DataProblem } from "@/components/data-state";
import { PageIntro } from "@/components/page-intro";
import { LeaderboardScroll } from "@/components/leaderboard-scroll";
import { LeaderboardMetricDetails } from "@/components/leaderboard-metric-details";
import { LeaderboardCalculationRules } from "@/components/leaderboard-calculation-rules";
import type { LeaderboardItem, Metric, SearchParams } from "@/lib/types";
import { formatNumber } from "@/lib/format";
import styles from "./leaderboard.module.css";

export const metadata: Metadata = { title: "赛季积分榜", description: "按赛季和比赛阶段查看选手积分、出场、胜率与投票表现。" };
function first(value: string | string[] | undefined): string { return Array.isArray(value) ? (value[0] ?? "") : (value ?? ""); }
function safeSeason(value: string): string { return /^[A-Za-z0-9_-]{1,20}$/.test(value) ? value : "S22"; }
function safePhase(value: string): "all" | "finals_week" { return value === "finals_week" ? "finals_week" : "all"; }
function percentage(rate: number | null): string { return typeof rate === "number" && Number.isFinite(rate) ? `${(rate * 100).toFixed(1)}%` : "—"; }
function RateCell({ value }: { value: Metric }) {
  return <td><strong>{percentage(value.rate)}</strong><small className="leaderboard-rate-detail">
    <span className="leaderboard-rate-equation">{formatNumber(value.numerator)} / {formatNumber(value.denominator)}</span>
  </small></td>;
}
function PendingCell() {
  return <td aria-label="判定口径待确认"><strong>—</strong></td>;
}
function BluffCountCell({ player, season }: { player: LeaderboardItem; season: string }) {
  const count = player.bluff_count_complete ? formatNumber(player.bluff_count)
    : player.bluff_count ? `≥${formatNumber(player.bluff_count)}` : "—";
  return <td><strong>{count}</strong>{player.bluff_review_count ? <Link className="bluff-review-flag" href={`/leaderboard/bluff-review?${new URLSearchParams({ season, player: player.id })}`} title="查看悍跳归属或成功结果的疑问与原文证据">待复核</Link> : null}</td>;
}
function TableHeading() {
  return <><colgroup><col className="leaderboard-rank-col" /><col className="leaderboard-name-col" /><col span={24} /></colgroup><thead>
    <tr className="leaderboard-group-head"><th scope="col" rowSpan={2}>名次</th><th scope="col" rowSpan={2}>选手</th><th scope="colgroup" colSpan={6}>综合表现</th><th scope="colgroup" colSpan={7}>投票与好人表现</th><th scope="colgroup" colSpan={6}>狼人表现</th><th scope="colgroup" colSpan={5}>悍跳与技能</th></tr>
    <tr><th scope="col">积分</th><th scope="col">整季出场</th><th scope="col">出场率</th><th scope="col">总胜场</th><th scope="col">整季胜率</th><th scope="col">上警率</th><th scope="col">投狼次数</th><th scope="col">投狼率</th><th scope="col">放逐弃票</th><th scope="col">好人胜场</th><th scope="col">好人胜率</th><th scope="col">警徽正确率</th><th scope="col">好人站边率</th><th scope="col">狼人场次</th><th scope="col">拿狼率</th><th scope="col">自爆率</th><th scope="col">狼人上警率</th><th scope="col">狼人胜场</th><th scope="col">狼人胜率</th><th scope="col">悍跳次数</th><th scope="col">悍跳成功率</th><th scope="col">技能正确率</th><th scope="col">狼人技能正确率</th><th scope="col">好人技能正确率</th></tr>
  </thead></>;
}

export default async function LeaderboardPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const query = await searchParams;
  const season = safeSeason(first(query.season) || "S22");
  const phase = safePhase(first(query.phase));
  let data: Awaited<ReturnType<typeof getLeaderboard>>;
  try {
    data = await getLeaderboard(season, phase);
  } catch (error) {
    return <div className="page-wrap"><PageIntro title="赛季积分榜" description="整季表现统一统计；决赛周另列冠军榜。" /><DataProblem error={error} /></div>;
  }
  let seasons: { id: string; name: string }[] = [];
  try { seasons = (await getOverview()).seasons.map(({ id, name }) => ({ id, name })); } catch { /* Keep the selected season available if the overview endpoint is offline. */ }
  if (!seasons.some((item) => item.id === season)) seasons = [{ id: season, name: season }, ...seasons];
  const href = (nextPhase: "all" | "finals_week") => `/leaderboard?season=${encodeURIComponent(season)}&phase=${nextPhase}`;
  const seasonCompleted = data.season_status === "completed";
  return <div className={"page-wrap leaderboard-page " + styles.page}>
    <PageIntro title={`${season} 积分榜`} description="整季榜包含决赛周；冠军榜仅计算决赛周积分。" />
    <section className="leaderboard-controls filter-panel">
      <form method="get" action="/leaderboard" className="leaderboard-season-form"><label className="filter-field"><span>赛季</span><select name="season" defaultValue={season}>{seasons.map((item) => <option value={item.id} key={item.id}>{item.name} · {item.id}</option>)}</select></label><input type="hidden" name="phase" value={phase} /><button className="button button-primary" type="submit">切换赛季 <span>→</span></button></form>
      <nav className="leaderboard-tabs" aria-label="积分榜阶段"><Link href={href("all")} aria-current={phase === "all" ? "page" : undefined}>整季积分榜</Link><Link href={href("finals_week")} aria-current={phase === "finals_week" ? "page" : undefined}>决赛周冠军榜</Link></nav>
    </section>
    <section className={`leaderboard-summary${seasonCompleted ? " leaderboard-summary-completed" : ""}`}>
      <article><span>计分对局</span><strong>{formatNumber(data.game_count)} 局</strong></article>{!seasonCompleted ? <article><span>待结算出场</span><strong>{formatNumber(data.pending_games)}</strong></article> : null}<article><span>积分规则</span><strong>狼人胜 +{data.scoring.werewolf_win} · 好人胜 +{data.scoring.good_win} · 负 {data.scoring.loss}</strong></article>
    </section>
    <section className="leaderboard-table-section">
      <div className="section-heading"><div><h2>选手排名</h2><p className="section-subtitle">同分并列；除积分外，各项指标按整季统计。</p></div></div>
      {data.items.length ? <LeaderboardMetricDetails><LeaderboardScroll heading={<TableHeading />}><table className="leaderboard-table leaderboard-comparison"><TableHeading /><tbody>{data.items.map((player) => <tr key={player.id}>
        <td><span className="rank-badge">{formatNumber(player.rank)}</span></td><td><Link className="leaderboard-player" href={`/players/${encodeURIComponent(player.id)}?season=${encodeURIComponent(season)}`}><strong>{player.name}</strong></Link></td>
        <td className="leaderboard-points"><strong>{player.points_complete ? formatNumber(player.points) : `已知小计 ${formatNumber(player.points)}`}</strong>{player.points_complete ? null : <small>{formatNumber(player.pending_games)} 场{seasonCompleted ? "结果待核" : "待结算"}；非最终积分</small>}</td>
        <td>{formatNumber(player.appearances)}</td><RateCell value={player.attendance} /><td>{formatNumber(player.wins)}</td><RateCell value={player.total_win_rate} /><RateCell value={player.sheriff_registration_rate} />
        <td>{formatNumber(player.wolf_vote_rate.numerator)}</td><RateCell value={player.wolf_vote_rate} /><td>{formatNumber(player.exile_abstentions)}</td><td>{formatNumber(player.good_win_rate.numerator)}</td><RateCell value={player.good_win_rate} /><RateCell value={player.sheriff_seer_vote_rate} /><RateCell value={player.seer_follow_rate} />
        <td>{formatNumber(player.werewolf_appearances)}</td><RateCell value={player.werewolf_draw_rate} /><RateCell value={player.werewolf_self_explosion_rate} /><RateCell value={player.werewolf_sheriff_registration_rate} /><td>{formatNumber(player.werewolf_win_rate.numerator)}</td><RateCell value={player.werewolf_win_rate} />
        <BluffCountCell player={player} season={season} /><RateCell value={player.bluff_success_rate} /><PendingCell /><PendingCell /><PendingCell />
      </tr>)}</tbody></table></LeaderboardScroll></LeaderboardMetricDetails> : <div className="empty-state"><span className="empty-number">—</span><p>当前阶段还没有可展示的积分记录。</p></div>}
    </section>
    <details className="methodology-details"><summary>数据说明与版本</summary><p>悍跳次数与成功率依据逐局复核结果统计；归属不明确时显示“≥已识别次数”或“—”，不确定结果不计入成功率分母。三项技能正确率暂未统计。<Link href={`/leaderboard/bluff-review?season=${encodeURIComponent(season)}`}>查看悍跳证据与复核结果 →</Link></p>{data.notes.length ? <ul>{data.notes.map((note, index) => <li key={index}>{note}</li>)}</ul> : null}<p>数据版本：<code>{data.release_id}</code></p></details>
    <LeaderboardCalculationRules scoring={data.scoring} />
  </div>;
}
