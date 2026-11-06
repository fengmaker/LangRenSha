"use client";

import { ArchiveLink } from "@/components/archive-link";
import { StatsRangeFilter } from "./stats-range-filter";
import type { Release, Stats } from "@/lib/types";
import { PageIntro } from "@/components/page-intro";
import { MetricFormula } from "@/components/metric-formula";
import { formatDate, formatNumber } from "@/lib/format";
import styles from "./stats.module.css";

function percentage(wins: number, settled: number): string {
  return settled > 0 ? `${(wins / settled * 100).toFixed(1)}%` : "—";
}

export function StatsView({ stats, releases, start, end, onRangeChange }: {
  stats: Stats; releases: { items: Release[] }; start: string; end: string; onRangeChange?: (start: string, end: string) => void;
}) {
  const startSeason = stats.scope.season_start;
  const endSeason = stats.scope.season_end;
  const rangeLabel = end === "latest" ? `${start} 至今` : start === endSeason ? start : `${start} — ${endSeason}`;
  const totals = stats.boards.reduce((sum, board) => ({ good: sum.good + board.good_wins, werewolf: sum.werewolf + board.werewolf_wins }), { good: 0, werewolf: 0 });
  const settled = totals.good + totals.werewolf;
  return <div className={`page-wrap ${styles.statsPage}`}>
    <PageIntro title="数据说明" action={<ArchiveLink className="button button-outline" href={`/players?season=${encodeURIComponent(startSeason)}`}>查看选手数据 <span aria-hidden="true">→</span></ArchiveLink>} />
    <section className={styles.filterPanel} aria-labelledby="stats-scope-heading">
      <div className={styles.filterHeading}><h2 id="stats-scope-heading">统计范围</h2><span className={styles.scopeBadge}>{rangeLabel}</span></div>
      <StatsRangeFilter key={`${start}:${end}`} seasons={stats.available_seasons} start={start || startSeason} end={end} onApply={onRangeChange} />
    </section>
    <section className={styles.summaryGrid} aria-label="对局统计概览">
      <article className={styles.summaryCard}><span>纳入对局</span><strong>{formatNumber(stats.game_count)}<span className={styles.unit}>局</span></strong></article>
      <article className={`${styles.summaryCard} ${styles.goodSummary}`}><span>好人胜率</span><strong>{percentage(totals.good, settled)}</strong></article>
      <article className={`${styles.summaryCard} ${styles.wolfSummary}`}><span>狼人胜率</span><strong>{percentage(totals.werewolf, settled)}</strong></article>
    </section>
    <section className={styles.calculationGuide} aria-labelledby="stats-calculation-heading">
      <h2 id="stats-calculation-heading">胜率计算</h2>
      <dl className={styles.guideFormulas}>
        <div><dt>好人胜率</dt><dd><MetricFormula numerator="好人胜场" denominator="已结算对局数" percent /></dd></div>
        <div><dt>狼人胜率</dt><dd><MetricFormula numerator="狼人胜场" denominator="已结算对局数" percent /></dd></div>
      </dl>
      <p className={styles.guideNote}>已结算对局数为好人胜场与狼人胜场之和。胜方待定或平局不计入胜率分母；分母为零时显示“—”。下方各版型的胜率采用相同公式。</p>
    </section>
    <section className={styles.section} aria-labelledby="stats-boards-heading"><h2 id="stats-boards-heading">版型与结果</h2>{stats.boards.length ? <div className={styles.tableWrap} role="region" aria-label="版型与结果统计表" tabIndex={0}><table className={styles.boardTable}>
      <thead><tr><th scope="col">版型</th><th scope="col">对局数</th><th scope="col">好人胜场</th><th scope="col">好人胜率</th><th scope="col">狼人胜场</th><th scope="col">狼人胜率</th></tr></thead>
      <tbody>{stats.boards.map((board) => { const boardSettled = board.good_wins + board.werewolf_wins; return <tr key={board.code}><th scope="row">{board.name}</th><td>{formatNumber(board.games)}</td><td>{formatNumber(board.good_wins)}</td><td className={styles.goodRate}>{percentage(board.good_wins, boardSettled)}</td><td>{formatNumber(board.werewolf_wins)}</td><td className={styles.wolfRate}>{percentage(board.werewolf_wins, boardSettled)}</td></tr>; })}</tbody>
    </table></div> : <div className="empty-state"><span className="empty-number">—</span><p>当前范围没有版型统计记录。</p></div>}</section>
    <section className={styles.section} aria-labelledby="stats-roles-heading"><h2 id="stats-roles-heading">身份记录数量</h2>{stats.roles.length ? <div className={styles.roleGrid}>{stats.roles.map((role) => <article className={styles.roleCard} key={role.role}><h3>{role.role}</h3><strong>{formatNumber(role.count)}</strong></article>)}</div> : <div className="empty-state"><span className="empty-number">—</span><p>当前范围没有身份统计记录。</p></div>}</section>
    <div className={styles.detailsGroup}>
      <details className={styles.details}><summary>指标范围与样本处理<span aria-hidden="true">＋</span></summary><div className={styles.detailsContent}>
        <ul className={styles.methodology}>
          <li>本页汇总所选赛季区间的正式对局。身份记录按每位选手每局的原始身份累计，身份未知单独计数。</li>
          <li>个人胜率、出场率、上警率与投票指标均包含整季及决赛周。整季积分包含全部正式对局，决赛周冠军榜仅累计决赛周积分。</li>
          <li>好人、狼人指标按个人胜利阵营分别统计；投票指标按轮次计数，PK、技能复投分别计入。</li>
          <li>悍跳次数与成功结果依据逐局复核，待定结论排除在相应比例的分母之外。</li>
        </ul>
        <dl className={styles.stateLegend}><div><dt>有效样本</dt><dd>信息可判定，计入对应指标的分子或分母。</dd></div><div><dt>排除样本</dt><dd>记录缺失或结论待定，不按失败计入分母。</dd></div><div><dt>无有效样本</dt><dd>分母为零，比例显示“—”。</dd></div></dl>
        <p className={styles.rulesLink}><ArchiveLink href={`/leaderboard?season=${encodeURIComponent(startSeason)}#leaderboard-calculation-rules`}>查看个人指标计算规则 →</ArchiveLink></p>
      </div></details>
      <details className={styles.details}><summary>发布版本<span aria-hidden="true">＋</span></summary><div className={styles.releaseWrap} role="region" aria-label="发布版本记录" tabIndex={0}><table className={styles.releaseTable}><thead><tr><th scope="col">版本</th><th scope="col">发布日期</th><th scope="col">对局数</th><th scope="col">状态</th></tr></thead><tbody>{releases.items.map((release) => <tr key={release.id}><th scope="row">{release.id}</th><td>{release.published_at ? formatDate(release.published_at.slice(0, 10)) : "未记录"}</td><td>{formatNumber(release.game_count)}</td><td><span className={release.active ? styles.activeRelease : undefined}>{release.active ? "当前版本" : "历史版本"}</span></td></tr>)}</tbody></table></div></details>
    </div>
  </div>;
}
