import Link from "next/link";
import type { Metadata } from "next";
import { getLeaderboard, getOverview } from "@/lib/api";
import { DataProblem } from "@/components/data-state";
import { PageIntro } from "@/components/page-intro";
import { LeaderboardScroll } from "@/components/leaderboard-scroll";
import { LeaderboardMetricDetails, LeaderboardSampleLink } from "@/components/leaderboard-metric-details";
import { LeaderboardCalculationRules } from "@/components/leaderboard-calculation-rules";
import type { LeaderboardItem, Metric, SearchParams } from "@/lib/types";
import { formatNumber } from "@/lib/format";
import styles from "./leaderboard.module.css";

export const metadata: Metadata = { title: "赛季积分榜", description: "按赛季和比赛阶段查看选手积分、出场、胜率与投票表现。" };
function first(value: string | string[] | undefined): string { return Array.isArray(value) ? (value[0] ?? "") : (value ?? ""); }
function safeSeason(value: string): string { return /^[A-Za-z0-9_-]{1,20}$/.test(value) ? value : "S23"; }
function safePhase(value: string): "all" | "finals_week" { return value === "finals_week" ? "finals_week" : "all"; }
function percentage(rate: number | null): string { return typeof rate === "number" && Number.isFinite(rate) ? `${(rate * 100).toFixed(1)}%` : "—"; }
function RateCell({ value, label, player, samples = true }: { value: Metric; label: string; player: LeaderboardItem; samples?: boolean }) {
  return <td><strong>{percentage(value.rate)}</strong><div className="leaderboard-rate-detail">
    {samples ? <LeaderboardSampleLink label={label} metric={{ numerator: value.numerator, denominator: value.denominator, excluded: value.excluded, samples: value.samples }} playerId={player.id} playerName={player.name} />
      : <span className="leaderboard-rate-equation">{formatNumber(value.numerator)} / {formatNumber(value.denominator)}</span>}
  </div></td>;
}
function BluffCountCell({ player, season }: { player: LeaderboardItem; season: string }) {
  const count = player.bluff_count_complete ? formatNumber(player.bluff_count)
    : player.bluff_count ? `≥${formatNumber(player.bluff_count)}` : "—";
  return <td><strong>{count}</strong>{player.bluff_review_count ? <Link className="bluff-review-flag" href={`/leaderboard/bluff-review?${new URLSearchParams({ season, player: player.id })}`} title="查看悍跳归属或成功结果的疑问与原文证据">待复核</Link> : null}</td>;
}
function TableHeading() {
  return <><colgroup><col className="leaderboard-rank-col" /><col className="leaderboard-name-col" /><col span={24} /></colgroup><thead>
    <tr className="leaderboard-group-head"><th scope="col" rowSpan={2}>名次</th><th scope="col" rowSpan={2}>选手</th><th scope="colgroup" colSpan={6}>综合表现</th><th scope="colgroup" colSpan={9}>好人表现</th><th scope="colgroup" colSpan={9}>狼人表现</th></tr>
    <tr><th scope="col">积分</th><th scope="col">整季出场</th><th scope="col">出场率</th><th scope="col">总胜场</th><th scope="col">整季胜率</th><th scope="col">上警率</th><th scope="col">好人胜场</th><th scope="col">好人胜率</th><th scope="col">投狼次数</th><th scope="col">投狼率</th><th scope="col">放逐弃票</th><th scope="col">好人上警率</th><th scope="col">好人警下率</th><th scope="col">警徽正确率</th><th scope="col">好人站边率</th><th scope="col">狼人场次</th><th scope="col">狼人胜场</th><th scope="col">狼人胜率</th><th scope="col">拿狼率</th><th scope="col">自爆率</th><th scope="col">狼人上警率</th><th scope="col">悍跳次数</th><th scope="col">悍跳率</th><th scope="col">悍跳成功率</th></tr>
  </thead></>;
}

export default async function LeaderboardPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const query = await searchParams;
  const season = safeSeason(first(query.season) || "S23");
  const phase = safePhase(first(query.phase));
  let data: Awaited<ReturnType<typeof getLeaderboard>>;
  let overview: Awaited<ReturnType<typeof getOverview>> | null;
  try {
    [data, overview] = await Promise.all([getLeaderboard(season, phase), getOverview().catch(() => null)]);
  } catch (error) {
    return <div className="page-wrap"><PageIntro title="赛季积分榜" /><DataProblem error={error} /></div>;
  }
  let seasons = overview?.seasons.map(({ id, name }) => ({ id, name })) ?? [];
  if (!seasons.some((item) => item.id === season)) seasons = [{ id: season, name: season }, ...seasons];
  const href = (nextPhase: "all" | "finals_week") => `/leaderboard?season=${encodeURIComponent(season)}&phase=${nextPhase}`;
  const seasonCompleted = data.season_status === "completed";
  return <div className={"page-wrap leaderboard-page " + styles.page}>
    <PageIntro title={`${season} 积分榜`} />
    <section className="leaderboard-controls filter-panel">
      <form method="get" action="/leaderboard" className="leaderboard-season-form"><label className="filter-field"><span>赛季</span><select name="season" defaultValue={season}>{seasons.map((item) => <option value={item.id} key={item.id}>{item.name} · {item.id}</option>)}</select></label><input type="hidden" name="phase" value={phase} /><button className="button button-primary" type="submit">切换赛季 <span>→</span></button></form>
      <nav className="leaderboard-tabs" aria-label="积分榜阶段"><Link href={href("all")} aria-current={phase === "all" ? "page" : undefined}>整季积分榜</Link><Link href={href("finals_week")} aria-current={phase === "finals_week" ? "page" : undefined}>决赛周冠军榜</Link></nav>
    </section>
    <section className={`leaderboard-summary${seasonCompleted ? " leaderboard-summary-completed" : ""}`}>
      <article><span>计分对局</span><strong>{formatNumber(data.game_count)} 局</strong></article>{!seasonCompleted ? <article><span>待结算出场</span><strong>{formatNumber(data.pending_games)}</strong></article> : null}
    </section>
    <section className="leaderboard-table-section">
      <div className="section-heading"><h2>选手排名</h2></div>
      {data.items.length ? <LeaderboardMetricDetails sampleGames={data.sample_games}><LeaderboardScroll heading={<TableHeading />}><table className="leaderboard-table leaderboard-comparison"><TableHeading /><tbody>{data.items.map((player) => <tr key={player.id}>
        <td><span className="rank-badge">{formatNumber(player.rank)}</span></td><td><Link className="leaderboard-player" href={`/players/${encodeURIComponent(player.id)}?season=${encodeURIComponent(season)}`}><strong>{player.name}</strong></Link></td>
        <td className="leaderboard-points"><strong>{player.points_complete ? formatNumber(player.points) : `已知小计 ${formatNumber(player.points)}`}</strong>{player.points_complete ? null : <small>{formatNumber(player.pending_games)} 场{seasonCompleted ? "结果待核" : "待结算"}；非最终积分</small>}</td>
        <td>{formatNumber(player.appearances)}</td><RateCell label="出场率" player={player} value={player.attendance} samples={false} /><td>{formatNumber(player.wins)}</td><RateCell label="整季胜率" player={player} value={player.total_win_rate} samples={false} /><RateCell label="上警率" player={player} value={player.sheriff_registration_rate} />
        <td>{formatNumber(player.good_win_rate.numerator)}</td><RateCell label="好人胜率" player={player} value={player.good_win_rate} samples={false} /><td>{formatNumber(player.wolf_vote_rate.numerator)}</td><RateCell label="投狼率" player={player} value={player.wolf_vote_rate} /><td>{formatNumber(player.exile_abstentions)}</td><RateCell label="好人上警率" player={player} value={player.good_sheriff_registration_rate} /><RateCell label="好人警下率" player={player} value={player.good_off_police_rate} /><RateCell label="警徽正确率" player={player} value={player.sheriff_seer_vote_rate} /><RateCell label="好人站边率" player={player} value={player.seer_follow_rate} />
        <td>{formatNumber(player.werewolf_appearances)}</td><td>{formatNumber(player.werewolf_win_rate.numerator)}</td><RateCell label="狼人胜率" player={player} value={player.werewolf_win_rate} samples={false} /><RateCell label="拿狼率" player={player} value={player.werewolf_draw_rate} samples={false} /><RateCell label="自爆率" player={player} value={player.werewolf_self_explosion_rate} /><RateCell label="狼人上警率" player={player} value={player.werewolf_sheriff_registration_rate} />
        <BluffCountCell player={player} season={season} /><RateCell label="悍跳率" player={player} value={player.bluff_rate} /><RateCell label="悍跳成功率" player={player} value={player.bluff_success_rate} />
      </tr>)}</tbody></table></LeaderboardScroll></LeaderboardMetricDetails> : <div className="empty-state"><span className="empty-number">—</span><p>当前阶段还没有可展示的积分记录。</p></div>}
    </section>
    <details className="methodology-details"><summary>数据说明与版本</summary><p>悍跳次数与比例依据逐局复核结果统计；归属不明确时显示“≥已识别次数”或“—”，并从悍跳率分母排除；成功结果不确定时不计入成功率分母。<Link href={`/leaderboard/bluff-review?season=${encodeURIComponent(season)}`}>查看悍跳证据与复核结果 →</Link></p>{data.notes.length ? <ul>{data.notes.map((note, index) => <li key={index}>{note}</li>)}</ul> : null}<p>数据版本：<code>{data.release_id}</code></p></details>
    <LeaderboardCalculationRules scoring={data.scoring} />
  </div>;
}
