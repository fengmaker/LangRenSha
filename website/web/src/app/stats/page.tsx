import Link from "next/link";
import type { Metadata } from "next";
import { getReleases, getStats } from "@/lib/api";
import type { SearchParams } from "@/lib/types";
import { DataProblem } from "@/components/data-state";
import { PageIntro } from "@/components/page-intro";
import { formatDate, formatNumber } from "@/lib/format";
import { StatsRangeFilter } from "./stats-range-filter";
import styles from "./stats.module.css";

function first(value: string | string[] | undefined): string {
  return Array.isArray(value) ? (value[0] ?? "") : (value ?? "");
}

function percentage(wins: number, settled: number): string {
  return settled > 0 ? `${(wins / settled * 100).toFixed(1)}%` : "—";
}

export const metadata: Metadata = {
  title: "数据说明",
  description: "按赛季范围查看身份分布、版型胜率与统计口径。",
};

export default async function StatsPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const query = await searchParams;
  const legacySeason = first(query.season);
  const start = first(query.season_start) || legacySeason || "S22";
  const end = first(query.season_end) || (legacySeason && !first(query.season_start) ? start : "latest");

  try {
    const [stats, releases] = await Promise.all([getStats(start, end), getReleases()]);
    const startSeason = stats.scope.season_start;
    const endSeason = stats.scope.season_end;
    const rangeLabel = end === "latest" ? `${startSeason} 至今`
      : startSeason === endSeason ? startSeason : `${startSeason} — ${endSeason}`;
    const totals = stats.boards.reduce((sum, board) => ({
      good: sum.good + board.good_wins,
      werewolf: sum.werewolf + board.werewolf_wins,
    }), { good: 0, werewolf: 0 });
    const settled = totals.good + totals.werewolf;

    return (
      <div className={`page-wrap ${styles.statsPage}`}>
        <PageIntro title="数据说明" action={
          <Link className="button button-outline" href={`/players?season=${encodeURIComponent(startSeason)}`}>
            查看选手数据 <span aria-hidden="true">→</span>
          </Link>
        } />

        <section className={styles.filterPanel} aria-labelledby="stats-scope-heading">
          <div className={styles.filterHeading}>
            <h2 id="stats-scope-heading">统计范围</h2>
            <span className={styles.scopeBadge}>{rangeLabel}</span>
          </div>
          <StatsRangeFilter
            key={`${startSeason}:${end}`}
            seasons={stats.available_seasons}
            start={startSeason}
            end={end === "latest" ? "latest" : endSeason}
          />
        </section>

        <section className={styles.summaryGrid} aria-label="对局统计概览">
          <article className={styles.summaryCard}>
            <span>纳入对局</span>
            <strong>{formatNumber(stats.game_count)}<span className={styles.unit}>局</span></strong>
          </article>
          <article className={`${styles.summaryCard} ${styles.goodSummary}`}>
            <span>好人胜率</span>
            <strong>{percentage(totals.good, settled)}</strong>
          </article>
          <article className={`${styles.summaryCard} ${styles.wolfSummary}`}>
            <span>狼人胜率</span>
            <strong>{percentage(totals.werewolf, settled)}</strong>
          </article>
        </section>

        <section className={styles.section} aria-labelledby="stats-boards-heading">
          <h2 id="stats-boards-heading">版型与结果</h2>
          {stats.boards.length ? (
            <div className={styles.tableWrap} role="region" aria-label="版型与结果统计表" tabIndex={0}>
              <table className={styles.boardTable}>
                <thead><tr>
                  <th scope="col">版型</th><th scope="col">对局数</th>
                  <th scope="col">好人胜场</th><th scope="col">好人胜率</th>
                  <th scope="col">狼人胜场</th><th scope="col">狼人胜率</th>
                </tr></thead>
                <tbody>{stats.boards.map((board) => {
                  const boardSettled = board.good_wins + board.werewolf_wins;
                  return <tr key={board.code}>
                    <th scope="row">{board.name}</th>
                    <td>{formatNumber(board.games)}</td>
                    <td>{formatNumber(board.good_wins)}</td>
                    <td className={styles.goodRate}>{percentage(board.good_wins, boardSettled)}</td>
                    <td>{formatNumber(board.werewolf_wins)}</td>
                    <td className={styles.wolfRate}>{percentage(board.werewolf_wins, boardSettled)}</td>
                  </tr>;
                })}</tbody>
              </table>
            </div>
          ) : <div className="empty-state"><span className="empty-number">—</span><p>当前范围没有版型统计记录。</p></div>}
        </section>

        <section className={styles.section} aria-labelledby="stats-roles-heading">
          <h2 id="stats-roles-heading">身份记录数量</h2>
          {stats.roles.length ? (
            <div className={styles.roleGrid}>{stats.roles.map((role) => (
              <article className={styles.roleCard} key={role.role}>
                <h3>{role.role}</h3><strong>{formatNumber(role.count)}</strong>
              </article>
            ))}</div>
          ) : <div className="empty-state"><span className="empty-number">—</span><p>当前范围没有身份统计记录。</p></div>}
        </section>

        <div className={styles.detailsGroup}>
          <details className={styles.details}>
            <summary>统计口径与字段状态<span aria-hidden="true">＋</span></summary>
            <div className={styles.detailsContent}>
              <ul className={styles.methodology}>
                <li>好人胜率与狼人胜率均以已确认胜方的对局为分母；没有有效胜负时显示“—”。</li>
                {stats.methodology.map((item, index) => <li key={index}>{item}</li>)}
              </ul>
              <dl className={styles.stateLegend}>
                <div><dt>未知</dt><dd>来源不足以确认字段值。</dd></div>
                <div><dt>未发动</dt><dd>已有记录表明该行动选择了不发动。</dd></div>
                <div><dt>不适用</dt><dd>该槽位不适用于当前对局或阶段。</dd></div>
              </dl>
            </div>
          </details>
          <details className={styles.details}>
            <summary>发布版本<span aria-hidden="true">＋</span></summary>
            <div className={styles.releaseWrap} role="region" aria-label="发布版本记录" tabIndex={0}>
              <table className={styles.releaseTable}>
                <thead><tr><th scope="col">版本</th><th scope="col">发布日期</th><th scope="col">对局数</th><th scope="col">状态</th></tr></thead>
                <tbody>{releases.items.map((release) => <tr key={release.id}>
                  <th scope="row">{release.id}</th>
                  <td>{release.published_at ? formatDate(release.published_at.slice(0, 10)) : "未记录"}</td>
                  <td>{formatNumber(release.game_count)}</td>
                  <td><span className={release.active ? styles.activeRelease : undefined}>{release.active ? "当前版本" : "历史版本"}</span></td>
                </tr>)}</tbody>
              </table>
            </div>
          </details>
        </div>
      </div>
    );
  } catch (error) {
    return <div className={`page-wrap ${styles.statsPage}`}><PageIntro title="数据说明" /><DataProblem error={error} /></div>;
  }
}
