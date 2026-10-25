import Link from "next/link";
import type { Metadata } from "next";
import { getOverview, getReleases, getStats } from "@/lib/api";
import type { SearchParams } from "@/lib/types";
import { DataProblem } from "@/components/data-state";
import { PageIntro } from "@/components/page-intro";
import { formatDate, formatNumber } from "@/lib/format";
import styles from "./stats.module.css";

function first(value: string | string[] | undefined): string { return Array.isArray(value) ? (value[0] ?? "") : (value ?? ""); }
export const metadata: Metadata = { title: "数据说明", description: "查看赛事档案的统计范围、发布版本与字段口径。" };

export default async function StatsPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const query = await searchParams;
  const season = first(query.season) || "S22";
  try {
    const [stats, overview, releases] = await Promise.all([getStats(season), getOverview(), getReleases()]);
    return <div className={`page-wrap stats-page ${styles.statsPage}`}>
      <PageIntro title="数据说明" description="统计基于已发布的数据版本，说明身份记录、整局胜负、选手指标与阶段积分的计算口径。" />
      <section className="filter-panel stats-filter"><form method="get" action="/stats" className="stats-season-form"><label className="filter-field"><span>统计赛季</span><select name="season" defaultValue={season}>{overview.seasons.map((item) => <option key={item.id} value={item.id}>{item.id} · {item.name}</option>)}</select></label><button className="button button-primary" type="submit">查看赛季 <span>→</span></button></form></section>

      <section className="stats-topline">
        <div className="stats-total"><span>本季纳入对局</span><strong>{formatNumber(stats.game_count)}<small>局</small></strong></div>
        <div className="stats-callout"><span className="callout-mark" aria-hidden="true">i</span><p>未知结果会保留在分布中，不计入好人胜场或狼人胜场。</p></div>
      </section>
      <section className="stats-section">
        <div className="section-heading"><div><h2>身份记录数量</h2><p className="section-subtitle">按已记录的身份出现次数汇总。</p></div></div>
        {stats.roles.length ? <div className="role-stat-grid">{stats.roles.map((role) => <article className="role-stat-card" key={role.role}><strong>{role.role}</strong><b>{formatNumber(role.count)}</b></article>)}</div> : <div className="empty-state"><span className="empty-number">—</span><p>当前赛季没有身份统计记录。</p></div>}
      </section>

      <section className="stats-section">
        <div className="section-heading"><div><h2>版型与结果</h2><p className="section-subtitle">按整局胜方汇总。</p></div></div>
        <div className="table-wrap"><table className="data-table stats-table"><thead><tr><th scope="col">版型</th><th scope="col">对局数</th><th scope="col">好人胜场</th><th scope="col">狼人胜场</th><th scope="col">未知结果</th></tr></thead><tbody>{stats.boards.map((board) => <tr key={board.code}><td><strong>{board.name}</strong></td><td>{formatNumber(board.games)}</td><td>{formatNumber(board.good_wins)}</td><td>{formatNumber(board.werewolf_wins)}</td><td>{formatNumber(board.unknown)}</td></tr>)}</tbody></table></div>
      </section>

      <p className={styles.playerLink}><Link href={"/players?season=" + encodeURIComponent(season)}>查看选手胜率与每局积分 →</Link></p>

      <section className="methodology-section">
        <div className="methodology-heading"><h2>口径与边界</h2><p>查看统计数字时，也请留意字段状态与发布版本。</p></div>
        <div className="methodology-list">{stats.methodology.map((item, index) => <article key={index}><p>{item}</p></article>)}</div>
        <div className="state-legend">
          <div><span className="state-mark state-unknown">?</span><span><b>未知</b><small>来源不足以确认字段值。</small></span></div>
          <div><span className="state-mark state-pass">—</span><span><b>未发动</b><small>已有记录表明该行动选择了不发动。</small></span></div>
          <div><span className="state-mark state-na">∅</span><span><b>不适用</b><small>该槽位不适用于当前对局或阶段。</small></span></div>
        </div>
      </section>

      <details className="release-details"><summary>展开查看发布版本与日期</summary><section className="release-history">
        <div className="section-heading"><div><h2>发布版本</h2></div></div>
        <div className="release-table"><div className="release-table-head"><span>版本</span><span>发布日期</span><span>对局数</span><span>状态</span></div>{releases.items.map((release) => <div className="release-table-row" key={release.id}><strong>{release.id}</strong><span>{release.published_at ? formatDate(release.published_at.slice(0, 10)) : "未记录"}</span><span>{formatNumber(release.game_count)}</span><span className={release.active ? "active-release" : ""}>{release.active ? "当前版本" : "历史版本"}</span></div>)}</div>
      </section></details>
    </div>;
  } catch (error) {
    return <div className={`page-wrap ${styles.statsPage}`}><PageIntro title="数据说明" description="查看统计范围与数据边界。" /><DataProblem error={error} /></div>;
  }
}
