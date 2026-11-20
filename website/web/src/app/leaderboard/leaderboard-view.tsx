"use client";

import { ArchiveLink } from "@/components/archive-link";
import { LeaderboardScroll } from "@/components/leaderboard-scroll";
import { LeaderboardMetricDetails, LeaderboardSampleLink } from "@/components/leaderboard-metric-details";
import { LeaderboardCalculationRules } from "@/components/leaderboard-calculation-rules";
import type { Leaderboard, LeaderboardItem, LeaderboardMetricKey, Overview } from "@/lib/types";
import { formatDate, formatNumber } from "@/lib/format";
import { publicPagePath } from "@/lib/site-mode";
import { fetchLeaderboardSamples, updateStaticQuery } from "@/lib/static-browser";
import { leaderboardColumnGroups, rankLeaderboard, type LeaderboardSortField } from "./leaderboard-ranking";
import styles from "./leaderboard.module.css";

function percentage(rate: number | null): string { return typeof rate === "number" && Number.isFinite(rate) ? `${(rate * 100).toFixed(1)}%` : "—"; }
function RateCell({ field, label, player, samples = true }: { field: LeaderboardMetricKey; label: string; player: LeaderboardItem; samples?: boolean }) {
  const value = player[field];
  return <td><strong>{percentage(value.rate)}</strong><div className="leaderboard-rate-detail">
    {samples ? <LeaderboardSampleLink label={label} field={field} metric={value} playerId={player.id} playerName={player.name} />
      : <span className="leaderboard-rate-equation">{formatNumber(value.numerator)} / {formatNumber(value.denominator)}</span>}
  </div></td>;
}
function BluffCountCell({ player }: { player: LeaderboardItem }) {
  const count = player.bluff_count_complete ? formatNumber(player.bluff_count) : player.bluff_count ? `≥${formatNumber(player.bluff_count)}` : "—";
  return <td><strong>{count}</strong></td>;
}
function TableHeading({ sortField, onSort }: { sortField: LeaderboardSortField; onSort?: (field: LeaderboardSortField) => void }) {
  return <><colgroup><col className="leaderboard-rank-col" /><col className="leaderboard-name-col" /></colgroup>{leaderboardColumnGroups.map(({ label, columns }) => <colgroup key={label}><col span={columns.length} /></colgroup>)}<thead>
    <tr className="leaderboard-group-head" aria-hidden={onSort ? true : undefined}><th scope="col" rowSpan={2}>名次</th><th scope="col" rowSpan={2}>选手</th>{leaderboardColumnGroups.map(({ label, columns }) => <th key={label} scope="colgroup" colSpan={columns.length}>{label}</th>)}</tr>
    <tr>{leaderboardColumnGroups.flatMap(({ columns }) => columns.map(([field, label]) => {
      const active = sortField === field;
      const text = <><span>{label}</span><span className={styles.sortArrow} aria-hidden="true" /></>;
      return <th key={field} scope="col" className={field === "points" ? `${styles.sortColumn} ${styles.pointsHeading}` : styles.sortColumn} aria-sort={!onSort && active ? "descending" : undefined}>
        {onSort ? <button type="button" className={styles.sortLabel} data-active={active} aria-label={`按${label}从高到低排名`} aria-pressed={active} onClick={() => onSort(field)}>{text}</button>
          : <span className={styles.sortLabel} data-active={active}>{text}</span>}
      </th>;
    }))}</tr>
  </thead></>;
}

export function LeaderboardView({ data, seasonOptions, availablePhases, sortField, onSort, snapshotId }: {
  data: Leaderboard;
  seasonOptions: Overview["seasons"];
  availablePhases?: string[];
  sortField: LeaderboardSortField;
  onSort: (field: LeaderboardSortField) => void;
  snapshotId: string;
}) {
  const { season, phase } = data;
  const rankedPlayers = rankLeaderboard(data.items, sortField);
  const seasons = seasonOptions.map(({ id, name }) => ({ id, name }));
  if (!seasons.some((item) => item.id === season)) seasons.unshift({ id: season, name: season });
  const sortParam = sortField === "points" ? "" : `&sort=${encodeURIComponent(sortField)}`;
  const href = (nextPhase: Leaderboard["phase"]) => `/leaderboard?season=${encodeURIComponent(season)}&phase=${nextPhase}${sortParam}`;
  const seasonCompleted = data.season_status === "completed";
  const hasFinalsWeek = !availablePhases || availablePhases.includes("finals_week");
  return <div className={"page-wrap leaderboard-page " + styles.page}>
    <h1 className={styles.screenReaderTitle}>{`${season} 积分榜`}</h1>
    <section className={`filter-panel ${styles.filters}`} aria-label="积分榜筛选">
      <form key={season} method="get" action={publicPagePath("/leaderboard")} className={styles.seasonForm} onSubmit={(event) => {
        event.preventDefault();
        const fields = new FormData(event.currentTarget);
        updateStaticQuery(new URLSearchParams(Array.from(fields, ([name, value]) => [name, String(value)])));
      }}>
        <label className="filter-field">
          <span>赛季</span>
          <select name="season" defaultValue={season}>{seasons.map((item) => <option value={item.id} key={item.id}>{item.name} · {item.id}</option>)}</select>
        </label>
        <input type="hidden" name="phase" value={phase} />
        {sortParam ? <input type="hidden" name="sort" value={sortField} /> : null}
        <button className="button button-primary" type="submit">切换赛季 <span aria-hidden="true">→</span></button>
      </form>
      <nav className="leaderboard-tabs" aria-label="积分榜阶段">
        <ArchiveLink href={href("all")} aria-current={phase === "all" ? "page" : undefined}>整季积分榜</ArchiveLink>
        {hasFinalsWeek ? <ArchiveLink href={href("finals_week")} aria-current={phase === "finals_week" ? "page" : undefined}>决赛周冠军榜</ArchiveLink> : null}
      </nav>
      {phase === "finals_week" ? <p className={styles.phaseNote}>出场、胜率与投票指标按整季统计。</p> : null}
    </section>
    <dl className={styles.scope}>
      <div><dt>计分对局</dt><dd>{formatNumber(data.game_count)} 局</dd></div>
      {data.latest_date ? <div><dt>最新对局日期</dt><dd><time dateTime={data.latest_date}>{formatDate(data.latest_date)}</time></dd></div> : null}
    </dl>
    <div className={styles.results}>
      {rankedPlayers.length ? <LeaderboardMetricDetails key={`${season}/${phase}`} loadSamples={() => fetchLeaderboardSamples(snapshotId, season, phase)}><LeaderboardScroll heading={<TableHeading sortField={sortField} onSort={onSort} />}><table className="leaderboard-table leaderboard-comparison"><TableHeading sortField={sortField} /><tbody>{rankedPlayers.map(({ player, rank }) => <tr key={player.id}>
        <td><span className="rank-badge">{rank === null ? "—" : formatNumber(rank)}</span></td><td><ArchiveLink className="leaderboard-player" href={`/players/${encodeURIComponent(player.id)}?season=${encodeURIComponent(season)}`}><strong>{player.name}</strong></ArchiveLink></td>
        <td className="leaderboard-points"><strong>{player.points_complete ? formatNumber(player.points) : `已知小计 ${formatNumber(player.points)}`}</strong>{player.points_complete ? null : <small>{formatNumber(player.pending_games)} 场{seasonCompleted ? "结果待核" : "待结算"}；非最终积分</small>}</td>
        <td>{formatNumber(player.appearances)}</td><RateCell label="出场率" player={player} field="attendance" samples={false} /><td>{formatNumber(player.wins)}</td><RateCell label="整季胜率" player={player} field="total_win_rate" samples={false} /><RateCell label="上警率" player={player} field="sheriff_registration_rate" />
        <td>{formatNumber(player.good_win_rate.numerator)}</td><RateCell label="好人胜率" player={player} field="good_win_rate" samples={false} /><td>{formatNumber(player.wolf_vote_rate.numerator)}</td><RateCell label="投狼率" player={player} field="wolf_vote_rate" /><td>{formatNumber(player.exile_abstentions)}</td><RateCell label="好人上警率" player={player} field="good_sheriff_registration_rate" /><RateCell label="好人警下率" player={player} field="good_off_police_rate" /><RateCell label="警徽正确率" player={player} field="sheriff_seer_vote_rate" /><RateCell label="跟真预言家投票率" player={player} field="seer_follow_rate" />
        <td>{formatNumber(player.werewolf_appearances)}</td><td>{formatNumber(player.werewolf_win_rate.numerator)}</td><RateCell label="狼人胜率" player={player} field="werewolf_win_rate" samples={false} /><RateCell label="拿狼率" player={player} field="werewolf_draw_rate" samples={false} /><RateCell label="自爆率" player={player} field="werewolf_self_explosion_rate" /><RateCell label="狼人上警率" player={player} field="werewolf_sheriff_registration_rate" />
        <BluffCountCell player={player} /><RateCell label="悍跳率" player={player} field="bluff_rate" /><RateCell label="悍跳成功率" player={player} field="bluff_success_rate" />
      </tr>)}</tbody></table></LeaderboardScroll></LeaderboardMetricDetails> : <div className="empty-state"><span className="empty-number">—</span><p>当前阶段还没有可展示的积分记录。</p></div>}
    </div>
    <details className="methodology-details"><summary>统计范围与数据版本</summary><p>整季榜累计全部正式对局积分，决赛周冠军榜仅累计决赛周积分；出场、胜率与投票指标均按整季计算。待定记录不按失败或零分处理。</p><p>悍跳次数与成功结果按逐局已确认结论统计；归属不明时显示“≥已识别次数”或“—”，待定样本排除在相应比例之外。</p><p>数据版本：<code>{data.release_id}</code></p></details>
    <LeaderboardCalculationRules scoring={data.scoring} />
  </div>;
}
