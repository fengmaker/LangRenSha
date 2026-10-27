import Link from "next/link";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ApiError, getPlayer } from "@/lib/api";
import type { Metric, MetricRanking, PlayerLedgerEntry, RankingEntry, SearchParams } from "@/lib/types";
import { formatDate, formatNumber, phaseLabel, factionLabel } from "@/lib/format";
import { DataProblem } from "@/components/data-state";
import styles from "./player-detail.module.css";
import { SeasonRangeFilter } from "./season-range-filter";
import { MetricSamples, type SampleLabels } from "./metric-samples";
import { MetricRank, type RankingContext } from "./metric-rank";

type PlayerPageProps = { params: Promise<{ id: string }>; searchParams: Promise<SearchParams> };
function first(value: string | string[] | undefined): string { return Array.isArray(value) ? (value[0] ?? "") : (value ?? ""); }
function range(query: SearchParams) {
  const start = first(query.season_start) || first(query.season) || "S22";
  const end = first(query.season_end) || (first(query.season) && !first(query.season_start) ? start : "latest");
  return { start, end };
}
function controlFlow(error: unknown): boolean {
  return typeof error === "object" && error !== null && "digest" in error && typeof error.digest === "string" && (error.digest.startsWith("NEXT_REDIRECT") || error.digest.startsWith("NEXT_NOT_FOUND"));
}
function rateText(rate: number | null | undefined): string { return typeof rate === "number" && Number.isFinite(rate) ? `${(rate * 100).toFixed(1)}%` : "—"; }
function MetricCard({ label, value, note, metric, games, sampleLabels, ranking, rankLabel, provisional, rankingBoard, rankContext }: { label: string; value: string; note?: string; metric?: Metric; games?: PlayerLedgerEntry[]; sampleLabels?: SampleLabels; ranking?: MetricRanking | null; rankLabel?: string; provisional?: boolean; rankingBoard?: RankingEntry[]; rankContext: RankingContext }) {
  const sampleIds = new Set((metric?.samples ?? []).map((sample) => sample.game_id));
  const hasSamples = metric && sampleLabels;
  return (
    <article className="profile-stat-card">
      {/* 四区位置、字号和行高统一由 player-detail.module.css 控制。 */}
      <div className="metric-copy">
        <span>{label}</span>
        <strong>{value}</strong>
        {note ? <small>{note}</small> : null}
      </div>
      <div className="metric-actions">
        <div className="profile-metric-ranks">
          <MetricRank
            ranking={ranking}
            label={rankLabel}
            provisional={provisional}
            entries={rankingBoard}
            metricLabel={rankLabel ?? label}
            format={label.includes("率") ? "percent" : label === "赛季积分" ? "points" : "count"}
            sampleUnit={sampleLabels?.unit}
            context={rankContext}
          />
        </div>
        {hasSamples ? (
          <MetricSamples
            label={label}
            metric={metric}
            games={(games ?? []).filter((game) => sampleIds.has(game.game_id))}
            labels={sampleLabels}
          />
        ) : null}
      </div>
    </article>
  );
}
function LedgerTable({ ledger, singleSeason }: { ledger: PlayerLedgerEntry[]; singleSeason: boolean }) {
  if (!ledger.length) return <div className="empty-state"><span className="empty-number">—</span><p>当前时间范围内暂无对局记录。</p></div>;
  return <div className="data-table-scroll"><table className="ledger-table"><thead><tr><th scope="col">对局</th><th scope="col">阶段 / 版型</th><th scope="col">身份</th><th scope="col">结果</th>{singleSeason ? <th scope="col">赛季累计积分</th> : null}</tr></thead><tbody>{ledger.map((entry, index) => <tr key={`${entry.game_id}-${index}`}>
    <td><Link href={`/games/${encodeURIComponent(entry.game_id)}`}>{entry.season ? `${entry.season} · ` : ""}{formatDate(entry.date)} · {entry.game_number ? `第 ${entry.game_number} 局` : entry.game_id}</Link></td>
    <td>{phaseLabel(entry.phase)}<small>{entry.board_name || "版型待核"}</small></td><td>{entry.role || "身份待核"}<small>{factionLabel(entry.faction)}{entry.faction_inferred ? " · 随榜样" : ""}</small></td>
    <td>{entry.result === "win" ? <span className="ledger-win">胜</span> : entry.result === "loss" ? <span className="ledger-loss">负</span> : <span className="ledger-pending">待结算</span>}</td>
    {singleSeason ? <td>{entry.cumulative_points.toFixed(1)}{entry.pending_count ? <small>另有 {entry.pending_count} 场待结算</small> : null}</td> : null}
  </tr>)}</tbody></table></div>;
}

export async function generateMetadata({ params, searchParams }: PlayerPageProps): Promise<Metadata> {
  const { id } = await params; const query = await searchParams;
  try {
    const { start, end } = range(query);
    const player = await getPlayer(id, start, "all", end);
    return { title: `${player.name} · 选手档案`, description: `${player.name} 的照片、胜率、竞选指标与对局记录。` };
  } catch (error) {
    if (controlFlow(error)) throw error;
    if (error instanceof ApiError && error.kind === "not-found") return { title: "选手未找到" };
    return { title: "选手档案" };
  }
}

export default async function PlayerDetailPage({ params, searchParams }: PlayerPageProps) {
  const { id } = await params; const query = await searchParams;
  const { start, end } = range(query); const phase = "all";
  try {
    const player = await getPlayer(id, start, phase, end);
    const season = player.scope?.season_start ?? start;
    const endSeason = player.scope?.season_end ?? season;
    const singleSeason = season === endSeason;
    const rangeLabel = end === "latest" ? `${season} 至今` : singleSeason ? season : `${season} — ${endSeason}`;
    const stats = player.stats;
    const rankings = stats?.rankings;
    const ledger = [...(stats?.ledger ?? [])].sort((a, b) => b.date.localeCompare(a.date) || (b.game_number ?? -1) - (a.game_number ?? -1) || b.game_id.localeCompare(a.game_id));
    const roles = [...(stats?.roles ?? [])].sort((a, b) => b.appearances - a.appearances || a.role.localeCompare(b.role, "zh-CN"));
    const boards = [...(stats?.boards ?? [])]
      .map((board) => ({ ...board, code: board.code ?? "", name: board.name || board.code || "版型待核" }))
      .sort((a, b) => b.appearances - a.appearances || a.name.localeCompare(b.name, "zh-CN"));
    const availableSeasons = [...new Set([season, ...(player.available_seasons ?? [])])].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
    const baseHref = `/players/${encodeURIComponent(id)}`;
    const rankContext = { playerId: id, start: season, end: end === "latest" ? "latest" : endSeason, scopeLabel: rangeLabel };
    return <div className={`page-wrap player-profile ${styles.profile}`}>
      <div className="breadcrumb"><Link href={`/players?season=${encodeURIComponent(season)}&phase=${phase}`}>选手索引</Link><span>/</span><span>{player.name}</span></div>
      <section className="player-profile-hero">
        <div className="profile-photo-frame">{player.photo ? <img src={player.photo.url} alt={`${player.name} · ${player.photo.season} 官方海报`} /> : <div className="profile-photo-empty"><span>{season} 赛季</span><b>{player.name}</b></div>}</div>
        <div className="profile-hero-copy"><h1>{player.name}</h1><p className="profile-range-label">{rangeLabel}</p><SeasonRangeFilter action={baseHref} seasons={availableSeasons} start={season} end={end === "latest" ? "latest" : endSeason} /></div>
      </section>

      {stats ? <>
        <section className="profile-stat-grid">
          {singleSeason ? <MetricCard rankContext={rankContext} rankingBoard={stats.ranking_boards?.points} ranking={rankings?.points} provisional={!stats.points_complete} label="赛季积分" value={stats.points_complete ? formatNumber(stats.points) : `小计 ${formatNumber(stats.points)}`} note={!stats.points_complete && stats.pending_games > 0 ? `${formatNumber(stats.pending_games)} 场待结算；当前值不是最终积分` : undefined} /> : <MetricCard rankContext={rankContext} rankingBoard={stats.ranking_boards?.appearances} ranking={rankings?.appearances} label="出场次数" value={formatNumber(stats.appearances)} />}
          <MetricCard rankContext={rankContext} rankingBoard={stats.ranking_boards?.attendance} ranking={rankings?.attendance} label="出场率" value={rateText(stats.attendance.rate)} />
          <MetricCard rankContext={rankContext} rankingBoard={stats.ranking_boards?.total_win_rate} ranking={rankings?.total_win_rate} label="总胜率" value={rateText(stats.total_win_rate.rate)} metric={stats.total_win_rate} games={ledger} sampleLabels={{ positive: "获胜", negative: "失利", unit: "场", description: "正面样本为胜局，负面样本为负局。" }} />
          <MetricCard rankContext={rankContext} rankingBoard={stats.ranking_boards?.wins} ranking={rankings?.wins} rankLabel="胜场" label="总胜场 / 负场" value={`${formatNumber(stats.wins)} / ${formatNumber(stats.losses)}`} metric={stats.total_win_rate} games={ledger} sampleLabels={{ positive: "获胜", negative: "失利", unit: "场", description: "正面样本为胜局，负面样本为负局。" }} note={stats.pending_games > 0 ? `${formatNumber(stats.pending_games)} 场结果待结算` : undefined} />
          <MetricCard rankContext={rankContext} rankingBoard={stats.ranking_boards?.werewolf_win_rate} ranking={rankings?.werewolf_win_rate} label="狼人胜率" value={rateText(stats.werewolf_win_rate.rate)} metric={stats.werewolf_win_rate} games={ledger} sampleLabels={{ positive: "获胜", negative: "失利", unit: "场", description: "正面样本为胜局，负面样本为负局。" }} />
          <MetricCard rankContext={rankContext} rankingBoard={stats.ranking_boards?.good_win_rate} ranking={rankings?.good_win_rate} label="好人胜率" value={rateText(stats.good_win_rate.rate)} metric={stats.good_win_rate} games={ledger} sampleLabels={{ positive: "获胜", negative: "失利", unit: "场", description: "正面样本为胜局，负面样本为负局。" }} />
          <MetricCard rankContext={rankContext} rankingBoard={stats.ranking_boards?.sheriff_registration_rate} ranking={rankings?.sheriff_registration_rate} label="上警率" value={rateText(stats.sheriff_registration_rate.rate)} metric={stats.sheriff_registration_rate} games={ledger} sampleLabels={{ positive: "上警", negative: "未上警", unit: "场", description: "正面样本为首次报名上警的对局，负面样本为未上警的对局。" }} />
          <MetricCard rankContext={rankContext} rankingBoard={stats.ranking_boards?.seer_follow_rate} ranking={rankings?.seer_follow_rate} label="站边率" value={rateText(stats.seer_follow_rate.rate)} metric={stats.seer_follow_rate} games={ledger} sampleLabels={{ positive: "站边正确", negative: "站边错误", unit: "次", description: "按放逐投票轮次比较与真实预言家 / 通灵师的投向。同一局可能同时有站对与站错的轮次，会分别显示在两类样本中。" }} />
          <MetricCard rankContext={rankContext} rankingBoard={stats.ranking_boards?.sheriff_seer_vote_rate} ranking={rankings?.sheriff_seer_vote_rate} label="警徽票投对预言家率" value={rateText(stats.sheriff_seer_vote_rate.rate)} metric={stats.sheriff_seer_vote_rate} games={ledger} sampleLabels={{ positive: "投对", negative: "未投对", unit: "次", description: "按警徽投票轮次统计，正面样本为投给真实预言家 / 通灵师的记录，负面样本为未投对的记录；包含 PK 复投。" }} />
        </section>
        <section className="profile-two-col profile-performance">
          <div className="profile-block"><div className="section-heading compact"><div><h2>身份胜率分布</h2></div></div>
            {roles.length ? <div className="role-bars">{roles.map((role) => <div className="role-rate-row" key={role.role}><div className="role-rate-title"><strong>{role.role}</strong><span>{rateText(role.win_rate)}</span></div><div className="role-card-footer"><MetricRank ranking={role.ranking} entries={role.ranking_board} metricLabel={`${role.role}身份胜率`} format="percent" context={rankContext} title={role.ranking ? `当前筛选范围内，与同为${role.role}且有有效胜负的 ${role.ranking.total} 位选手比较` : undefined} />{role.metric ? <MetricSamples label={`${role.role}身份胜率`} metric={role.metric} games={ledger.filter((game) => (game.role || "身份未知") === role.role)} labels={{ positive: "获胜", negative: "失利", unit: "场", description: `仅展示当前筛选范围内，以${role.role}身份出场的对局。正面样本为胜局，负面样本为负局。` }} /> : null}</div></div>)}</div> : <p className="lane-empty">身份胜率记录尚未整理。</p>}
          </div>
          <div className="profile-block">
            <div className="section-heading compact"><div><h2>版型胜率分布</h2></div></div>
            {boards.length ? (
              <div className="role-bars board-rate-grid">
                {boards.map((board) => {
                  const boardGameIds = new Set(board.metric.game_ids);
                  return (
                    <div className="role-rate-row board-rate-row" key={board.code || board.name} data-board-code={board.code}>
                      <div className="role-rate-title"><strong>{board.name}</strong><span>{rateText(board.win_rate)}</span></div>
                      <div className="role-card-footer">
                        <MetricRank
                          ranking={board.ranking}
                          entries={board.ranking_board}
                          metricLabel={`${board.name}版型胜率`}
                          format="percent"
                          context={rankContext}
                          title={board.ranking ? `当前筛选范围内，与同样参加${board.name}且有有效胜负的 ${board.ranking.total} 位选手比较` : undefined}
                        />
                        <MetricSamples
                          label={`${board.name}版型胜率`}
                          metric={board.metric}
                          games={ledger.filter((game) => boardGameIds.has(game.game_id))}
                          labels={{ positive: "获胜", negative: "失利", unit: "场", description: `仅展示当前筛选范围内，参加${board.name}版型的对局。正面样本为胜局，负面样本为负局。` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : <p className="lane-empty">版型胜率记录尚未整理。</p>}
          </div>
        </section>
        <section className="profile-games"><div className="section-heading"><div><h2>对局记录</h2></div><span className="section-index">{ledger.length} 场</span></div><LedgerTable ledger={ledger} singleSeason={singleSeason} /></section>
      </> : <section className="profile-stat-grid profile-stat-fallback"><article><span>出场</span><strong>{formatNumber(player.appearances)}</strong><small>统计摘要暂未提供</small></article><article><span>身份种类</span><strong>{formatNumber(player.roles.length)}</strong><small>原始档案数量</small></article></section>}
      <details className="release-details"><summary>查看此页的数据版本</summary><div className="release-detail-content"><span>发布版本 <code>{player.release_id}</code></span><span>范围 <b>{rangeLabel}</b></span></div></details>
    </div>;
  } catch (error) {
    if (controlFlow(error)) throw error;
    if (error instanceof ApiError && error.kind === "not-found") notFound();
    return <div className="page-wrap"><DataProblem error={error} /></div>;
  }
}
