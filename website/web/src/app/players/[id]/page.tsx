import Link from "next/link";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ApiError, getPlayer } from "@/lib/api";
import type { Metric, PlayerLedgerEntry, SearchParams } from "@/lib/types";
import { formatDate, formatNumber, phaseLabel, factionLabel } from "@/lib/format";
import { DataProblem } from "@/components/data-state";
import styles from "./player-detail.module.css";

const PHASES = ["all", "regular", "finals_week"] as const;
type PlayerPageProps = { params: Promise<{ id: string }>; searchParams: Promise<SearchParams> };
function first(value: string | string[] | undefined): string { return Array.isArray(value) ? (value[0] ?? "") : (value ?? ""); }
function allowedPhase(value: string): (typeof PHASES)[number] { return PHASES.includes(value as (typeof PHASES)[number]) ? value as (typeof PHASES)[number] : "all"; }
function controlFlow(error: unknown): boolean {
  return typeof error === "object" && error !== null && "digest" in error && typeof error.digest === "string" && (error.digest.startsWith("NEXT_REDIRECT") || error.digest.startsWith("NEXT_NOT_FOUND"));
}
function rateText(rate: number | null | undefined): string { return typeof rate === "number" && Number.isFinite(rate) ? `${(rate * 100).toFixed(1)}%` : "—"; }
function MetricSamples({ metric, games }: { metric: Metric; games: PlayerLedgerEntry[] }) {
  const byId = new Map(games.map((game) => [game.game_id, game]));
  return <details className="metric-samples"><summary>查看样本与口径</summary><div>
    <p>{metric.denominator ? `${formatNumber(metric.numerator)} / ${formatNumber(metric.denominator)} 个有效样本` : "暂无有效样本"}{metric.excluded ? ` · 排除 ${formatNumber(metric.excluded)}` : ""}</p>
    {metric.game_ids.length ? <ul>{metric.game_ids.map((id) => {
      const game = byId.get(id);
      const label = game ? [formatDate(game.date), game.game_number ? `第 ${game.game_number} 局` : null, game.board_name || "版型待核"].filter(Boolean).join(" · ") : id;
      return <li key={id}><Link href={`/games/${encodeURIComponent(id)}`}>{label}</Link></li>;
    })}</ul> : null}
  </div></details>;
}
function MetricCard({ label, value, metric, games, note }: { label: string; value: string; metric?: Metric; games: PlayerLedgerEntry[]; note?: string }) {
  return <article className="profile-stat-card"><span>{label}</span><strong>{value}</strong>{note ? <small>{note}</small> : null}{metric ? <MetricSamples metric={metric} games={games} /> : null}</article>;
}
function LedgerTable({ ledger }: { ledger: PlayerLedgerEntry[] }) {
  if (!ledger.length) return <div className="empty-state"><span className="empty-number">—</span><p>当前筛选没有可展示的积分明细。</p></div>;
  return <div className="data-table-scroll"><table className="ledger-table"><thead><tr><th scope="col">对局</th><th scope="col">阶段 / 版型</th><th scope="col">身份</th><th scope="col">结果</th><th scope="col">本局积分</th><th scope="col">整季累计</th></tr></thead><tbody>{ledger.map((entry, index) => <tr key={`${entry.game_id}-${index}`}>
    <td><Link href={`/games/${encodeURIComponent(entry.game_id)}`}>{formatDate(entry.date)} · {entry.game_number ? `第 ${entry.game_number} 局` : entry.game_id}</Link></td>
    <td>{phaseLabel(entry.phase)}<small>{entry.board_name || "版型待核"}</small></td><td>{entry.role || "身份待核"}<small>{factionLabel(entry.faction)}{entry.faction_inferred ? " · 随榜样" : ""}</small></td>
    <td>{entry.result === "win" ? <span className="ledger-win">胜</span> : entry.result === "loss" ? <span className="ledger-loss">负</span> : <span className="ledger-pending">待结算</span>}</td>
    <td className={entry.points === null ? "ledger-pending" : entry.points > 0 ? "ledger-win" : "ledger-loss"}>{entry.points === null ? "待结算" : `${entry.points > 0 ? "+" : ""}${entry.points.toFixed(1)}`}</td><td>{entry.cumulative_points.toFixed(1)}{entry.pending_count ? <small>另有 {entry.pending_count} 场待结算</small> : null}</td>
  </tr>)}</tbody></table></div>;
}

export async function generateMetadata({ params, searchParams }: PlayerPageProps): Promise<Metadata> {
  const { id } = await params; const query = await searchParams;
  try {
    const player = await getPlayer(id, first(query.season) || "S22", allowedPhase(first(query.phase)));
    return { title: `${player.name} · 选手档案`, description: `${player.name} 的赛季照片、胜率、竞选指标与积分明细。` };
  } catch (error) {
    if (controlFlow(error)) throw error;
    if (error instanceof ApiError && error.kind === "not-found") return { title: "选手未找到" };
    return { title: "选手档案" };
  }
}

export default async function PlayerDetailPage({ params, searchParams }: PlayerPageProps) {
  const { id } = await params; const query = await searchParams;
  const season = first(query.season) || "S22"; const phase = "all";
  try {
    const player = await getPlayer(id, season, phase);
    const stats = player.stats;
    const ledger = stats?.ledger ?? [];
    const roles = stats?.roles ?? [];
    const availableSeasons = [...new Set([season, ...(player.available_seasons ?? [])])];
    const baseHref = `/players/${encodeURIComponent(id)}`;
    return <div className={`page-wrap player-profile ${styles.profile}`}>
      <div className="breadcrumb"><Link href={`/players?season=${encodeURIComponent(season)}&phase=${phase}`}>选手索引</Link><span>/</span><span>{player.name}</span></div>
      <section className="player-profile-hero">
        <div className="profile-photo-frame">{player.photo ? <img src={player.photo.url} alt={`${player.name} · ${player.photo.season} 官方海报`} /> : <div className="profile-photo-empty"><span>{season} 赛季</span><b>{player.name}</b></div>}</div>
        <div className="profile-hero-copy"><h1>{player.name}</h1><p>{season} 赛季档案；个人指标按整季累计，包含决赛周。</p><div className="profile-hero-meta"><span><b>{formatNumber(stats?.appearances ?? player.appearances)}</b> 场出场</span><span><b>{formatNumber(stats?.scope_games ?? player.games.length)}</b> 场整季对局</span></div>{player.photo?.source_date ? <small className="photo-credit">照片来源：{player.photo.source_url ? <a href={player.photo.source_url} target="_blank" rel="noreferrer">微博 · {formatDate(player.photo.source_date)}</a> : formatDate(player.photo.source_date)}</small> : null}</div>
      </section>
      <section className="profile-filter filter-panel"><form method="get" action={baseHref} className="profile-filter-form"><label className="filter-field"><span>赛季</span><select name="season" defaultValue={season}>{availableSeasons.map((value) => <option key={value} value={value}>{value}</option>)}</select></label><button className="button button-primary" type="submit">切换赛季 <span>→</span></button><Link className="inline-link" href={`/leaderboard?season=${encodeURIComponent(season)}&phase=finals_week`}>决赛周冠军榜 →</Link></form></section>

      {stats ? <>
        <section className="profile-stat-grid">
          <MetricCard label="整季积分" value={stats.points_complete ? formatNumber(stats.points) : `小计 ${formatNumber(stats.points)}`} note={!stats.points_complete && stats.pending_games > 0 ? `${formatNumber(stats.pending_games)} 场待结算；当前值不是最终积分` : undefined} games={ledger} />
          <MetricCard label="整季出场率" value={rateText(stats.attendance.rate)} metric={stats.attendance} games={ledger} />
          <MetricCard label="总胜率" value={rateText(stats.total_win_rate.rate)} metric={stats.total_win_rate} games={ledger} />
          <MetricCard label="总胜场 / 负场" value={`${formatNumber(stats.wins)} / ${formatNumber(stats.losses)}`} note={stats.pending_games > 0 ? `${formatNumber(stats.pending_games)} 场结果待结算` : undefined} games={ledger} />
          <MetricCard label="狼人胜率" value={rateText(stats.werewolf_win_rate.rate)} metric={stats.werewolf_win_rate} games={ledger} />
          <MetricCard label="好人胜率" value={rateText(stats.good_win_rate.rate)} metric={stats.good_win_rate} games={ledger} />
          <MetricCard label="上警率" value={rateText(stats.sheriff_registration_rate.rate)} metric={stats.sheriff_registration_rate} games={ledger} />
          <MetricCard label="站边率" value={rateText(stats.seer_follow_rate.rate)} metric={stats.seer_follow_rate} games={ledger} />
          <MetricCard label="警徽票投对预言家率" value={rateText(stats.sheriff_seer_vote_rate.rate)} metric={stats.sheriff_seer_vote_rate} games={ledger} />
        </section>
        <section className="profile-two-col profile-performance">
          <div className="profile-block"><div className="section-heading compact"><div><h2>身份胜率分布</h2><p className="section-subtitle">按已知胜负计算。</p></div></div>
            {roles.length ? <div className="role-bars">{roles.map((role) => <div className="role-rate-row" key={role.role}><div className="role-rate-title"><strong>{role.role}</strong><span>{rateText(role.win_rate)}</span></div><div className="bar-track"><span style={{ width: `${Math.max(0, Math.min(100, (role.win_rate ?? 0) * 100))}%` }} /></div><small>{role.wins} 胜 / {role.losses} 负{role.pending_games > 0 ? ` · ${role.pending_games} 场待结算` : ""} · {formatNumber(role.appearances)} 场</small></div>)}</div> : <p className="lane-empty">身份胜率记录尚未整理。</p>}
          </div>
          <div className="profile-block"><div className="section-heading compact"><div><h2>版型记录</h2></div></div>
            {player.boards.length ? <div className="board-chip-list">{player.boards.map((board) => <div className="board-chip" key={board.code}><span>{board.name}</span><b>{formatNumber(board.count)}</b></div>)}</div> : <p className="lane-empty">版型记录尚未整理。</p>}
          </div>
        </section>
        <section className="profile-games"><div className="section-heading"><div><h2>每局积分明细</h2><p className="section-subtitle">整季累计（含决赛周）：狼人胜 +1.5，好人胜 +1，负局 -1；待结算暂不计分。</p></div><span className="section-index">{ledger.length} 场</span></div><LedgerTable ledger={ledger} /></section>
      </> : <section className="profile-stat-grid profile-stat-fallback"><article><span>出场</span><strong>{formatNumber(player.appearances)}</strong><small>统计摘要暂未提供</small></article><article><span>身份种类</span><strong>{formatNumber(player.roles.length)}</strong><small>原始档案数量</small></article></section>}
      {stats ? <details className="methodology-details"><summary>查看指标口径{stats.notes.length ? "与待核说明" : ""}</summary><div className="metric-definition-note">百分率按有效样本计算，分母为 0 时显示“—”；出场率按整季对局计算，胜率按已知胜负计算。未知记录不会当作失败或 0%。上警率按每局首次报名计一次。站边率统计好人阵营中预言家 / 通灵师以外的选手，与真实预言家 / 通灵师同轮有票权且后者明确投票时，投向同一目标的比例，包含放逐 PK / 技能复投。警徽票正确率统计真实预言家 / 通灵师为合法候选时的好人选票，包含 PK 复投。混血儿按榜样阵营计算。</div>{stats.notes.length ? <ul>{stats.notes.map((note, index) => <li key={index}>{note}</li>)}</ul> : null}</details> : null}
      <details className="release-details"><summary>查看此页的数据版本</summary><div className="release-detail-content"><span>发布版本 <code>{player.release_id}</code></span><span>范围 <b>{player.scope?.season ?? season} · {phaseLabel(player.scope?.phase ?? phase)}</b></span></div></details>
    </div>;
  } catch (error) {
    if (controlFlow(error)) throw error;
    if (error instanceof ApiError && error.kind === "not-found") notFound();
    return <div className="page-wrap"><DataProblem error={error} /></div>;
  }
}
