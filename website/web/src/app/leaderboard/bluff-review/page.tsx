import Link from "next/link";
import type { Metadata } from "next";
import { getBluffReview } from "@/lib/api";
import { DataProblem } from "@/components/data-state";
import { PageIntro } from "@/components/page-intro";
import type { BluffReview, SearchParams } from "@/lib/types";
import { BluffFeedbackTools } from "@/components/bluff-feedback-tools";
import { BluffFeedbackFields } from "@/components/bluff-feedback-fields";
import { gamePhaseLabel } from "@/lib/format";

export const metadata: Metadata = { title: "悍跳推断与复核" };
function first(value: string | string[] | undefined) { return Array.isArray(value) ? value[0] ?? "" : value ?? ""; }
function time(ms?: number) {
  if (ms === undefined) return "定位片段";
  const seconds = Math.floor(ms / 1000);
  return [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60].map((n) => String(n).padStart(2, "0")).join(":");
}
function statusLabel(item: BluffReview["items"][number]) {
  if (item.assistant_pending) return "待助手继续核查";
  if (item.claim_needs_review) return item.previous_decision === "yes"
    ? "上次确认悍跳 · 发言证据变化待复核" : "发言证据变化 · 悍跳归属待复核";
  if (item.success_needs_review && item.legacy_success_needs_review) return item.verification_status === "user_confirmed"
    ? "用户确认悍跳 · 历史成功缺少依赖基线" : "已识别悍跳 · 历史成功缺少依赖基线";
  if (item.success_needs_review) return item.verification_status === "user_confirmed"
    ? "用户确认悍跳 · 成功依据变化待复核" : "已识别悍跳 · 成功依据变化待复核";
  if (item.verification_status === "user_confirmed") {
    if (item.decision === "no") return "用户确认不是悍跳";
    if (item.success_source === "user") return `用户复核悍跳 · ${item.success === null ? "成功待定" : item.success ? "成功" : "失败"}${item.review_questions.some((question) => question.includes("暂定")) ? "（暂定）" : ""}`;
    return `用户确认悍跳 · ${item.success === null ? "成功结果待补" : item.success ? "按规则成功" : "按规则未成功"}`;
  }
  return item.decision === "uncertain" ? "悍跳归属待复核" : item.decision === "no" ? "推断不是悍跳" : item.success === null ? "成功结果待复核" : item.success ? "推断成功" : "推断未成功";
}
function conclusionLabel(value: boolean | null | undefined) {
  return value === true ? "成功" : value === false ? "失败" : "待定";
}
function hasReviewChange(items: BluffReview["items"]) {
  return items.some((item) => item.claim_needs_review || item.success_needs_review
    || item.review_questions.some((question) => question.includes("变化") || question.includes("冲突")));
}
function groupReviewItems(items: BluffReview["items"]) {
  const groups = new Map<string, BluffReview["items"]>();
  for (const item of items) groups.set(item.game_id, [...(groups.get(item.game_id) ?? []), item]);
  return [...groups.entries()].map(([gameId, rows]) => ({ gameId, rows: rows.sort((a, b) => a.seat - b.seat) })).sort((a, b) => {
    return Number(hasReviewChange(b.rows)) - Number(hasReviewChange(a.rows))
      || a.rows[0].date.localeCompare(b.rows[0].date)
      || (a.rows[0].game_number ?? 0) - (b.rows[0].game_number ?? 0);
  });
}

export default async function BluffReviewPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const query = await searchParams;
  const rawSeason = first(query.season) || "S22";
  const season = /^[A-Za-z0-9_-]{1,20}$/.test(rawSeason) ? rawSeason : "S22";
  const status = first(query.status) === "all" ? "all" : first(query.status) === "assistant_pending" ? "assistant_pending" : "pending";
  const rawPlayer = first(query.player);
  const player = /^[A-Za-z0-9_-]{1,100}$/.test(rawPlayer) ? rawPlayer : "";
  let data: Awaited<ReturnType<typeof getBluffReview>>;
  try { data = await getBluffReview(season, status, player); }
  catch (error) { return <div className="page-wrap"><PageIntro title="悍跳推断与复核" description="按逐局原文证据回查悍跳归属与成功结果。" /><DataProblem error={error} /></div>; }
  const reviewBase = season === "S23" ? "/seasons/S23/bluff-review" : "/leaderboard/bluff-review";
  const href = (nextStatus: "all" | "pending" | "assistant_pending") => `${reviewBase}?${new URLSearchParams({ season, status: nextStatus, player })}`;
  const groups = groupReviewItems(data.items);
  return <div className="page-wrap">
    <div className="breadcrumb"><Link href={`/leaderboard?season=${encodeURIComponent(season)}`}>积分榜</Link><span>/</span><span>悍跳推断与复核</span></div>
    <PageIntro title={`${season} 悍跳推断与复核`} description={data.manual_review ? "已采用用户逐局提交的悍跳与成功结果，原备注和暂定项同时保留。" : season === "S23" ? "先由助手核对首日警上发言、导播摘要与前后转写；默认只列仍需你判断的项目。" : "对照原文与视频回查推断，逐条标明用户确认或助手推断。"} />
    {season === "S23" ? <p>本轮已复核 {data.summary.reviewed_games ?? 0} / {data.summary.games} 局。{data.manual_review ? `其中人工纳入 ${data.summary.manual_included_appearances ?? 0} 条混血儿记录；默认仅列仍需确认的项目。` : data.summary.reviewed_games === data.summary.games ? "已完成整季视频与转写交叉复核，默认仅列仍需你判断的项目。" : "其余场次及待补细节列为“待助手继续”。"}</p> : null}
    <section className="leaderboard-summary"><article><span>已识别悍跳</span><strong>{data.summary.identified_bluffs}</strong></article><article><span>{data.manual_review ? "人工复核成功" : "按规则判定成功"}</span><strong>{data.summary.successes}</strong></article><article><span>待复核</span><strong>{data.summary.pending}</strong></article><article><span>整季对局范围</span><strong>{data.summary.games}</strong></article></section>
    <details className="methodology-details"><summary>查看本次判定口径</summary><ul>{data.notes.map((note) => <li key={note}>{note}</li>)}</ul></details>
    <nav className="leaderboard-tabs bluff-review-tabs" aria-label="悍跳复核范围"><Link href={href("pending")} aria-current={status === "pending" ? "page" : undefined}>{season === "S23" ? "只需你判断" : "待复核"}</Link>{season === "S23" ? <Link href={href("assistant_pending")} aria-current={status === "assistant_pending" ? "page" : undefined}>待助手继续（{data.summary.assistant_pending ?? 0}）</Link> : null}<Link href={href("all")} aria-current={status === "all" ? "page" : undefined}>全部推断</Link>{player ? <Link href={`${reviewBase}?season=${encodeURIComponent(season)}&status=${status}`}>查看全部选手</Link> : null}</nav>
    <BluffFeedbackTools season={season} inferenceVersion={data.inference_version} scopeKey={`${status}:${player}`} />
    <div className="bluff-review-list">{groups.map(({ gameId, rows }) => <article className="bluff-review-card" key={gameId}>
      <header><div><p className="review-meta">{rows[0].date} · 第{rows[0].game_number ?? "?"}局 · {rows.length} 条记录</p><h2>本局复核</h2></div>
        <strong className={hasReviewChange(rows) ? "bluff-status-pending" : "bluff-status-known"}>
          {hasReviewChange(rows) ? "变化／冲突优先" : "按座位复核"}
        </strong></header>
      <Link href={`/games/${encodeURIComponent(gameId)}`}>查看本局底牌、日夜行动、投票与最终结果 →</Link>
      <div className="bluff-review-entries">{rows.map((item) => <section className="bluff-review-entry" key={`${item.game_id}-${item.seat}`}>
        <header><div><h3>{item.seat}号 · {item.name} <span>{item.physical_role}{item.claimed_role ? ` → 自称${item.claimed_role}` : ""}</span></h3></div>
          <strong className={item.needs_review ? "bluff-status-pending" : "bluff-status-known"}>{statusLabel(item)}</strong></header>
        {item.success_source !== "user" || item.claim_day != null ? <p>{item.first_day_claim === true ? `起跳阶段：${gamePhaseLabel(1, "day")}` : item.claim_day === 2 ? `起跳阶段：${gamePhaseLabel(2, "day")}／延期竞选` : item.claim_day === "later" && item.actual_claim_day ? `起跳阶段：${gamePhaseLabel(item.actual_claim_day, "day")}（后续起跳）` : "起跳阶段：见证据与前后推断"}</p> : null}
        {item.claim_needs_review ? <section className="bluff-success-comparison" aria-label="悍跳归属结论前后对照">
          <h4>发言证据变化与复核影响</h4>
          <dl>
            <div><dt>改前 · 上次悍跳结论</dt><dd>{item.previous_decision === "yes" ? "确认悍跳" : item.previous_decision === "no" ? "确认不是悍跳" : "上次结论未单独保存"}</dd></div>
            <div><dt>改后 · 当前归属</dt><dd>待复核，暂不纳入已识别悍跳</dd></div>
            <div><dt>影响</dt><dd>上次结论与备注保留供对照；核清发言者、自称阶段和证据后再更新计数。</dd></div>
          </dl>
          {item.decision_note ? <p>上次备注：{item.decision_note}</p> : null}
        </section> : null}
        {item.success_needs_review ? <section className="bluff-success-comparison" aria-label="悍跳成功结论前后对照">
          <h4>{item.legacy_success_needs_review ? "历史成功结论与当前结果" : "本次变化、结果与影响"}</h4>
          <dl>
            <div><dt>改前 · 上次人工成功结论</dt><dd>{item.previous_success_saved ? conclusionLabel(item.previous_success) : "上次成功结论未单独保存"}</dd></div>
            <div><dt>改后 · 当前规则结果</dt><dd>{conclusionLabel(item.current_success)}，待复核</dd></div>
            <div><dt>影响</dt><dd>{item.legacy_success_needs_review ? "当前数据不能证明上次人工成功结论依赖的有效阵营与结果基线；悍跳结论保留，历史成功暂不计入，复核后再更新。" : "悍跳判断保留；成功率暂不计入，确认成功结果后再更新。"}</dd></div>
          </dl>
          {item.previous_decision ? <p>上次悍跳结论：{item.previous_decision === "yes" ? "确认悍跳" : item.previous_decision === "no" ? "确认不是悍跳" : "未确定"}</p> : null}
          {item.decision_note ? <p>上次备注：{item.decision_note}</p> : null}
        </section> : null}
        {!item.claim_needs_review && !item.success_needs_review && item.decision_note ? <p>上次备注：{item.decision_note}</p> : null}
        {item.review_questions.length ? <ul className="bluff-review-questions">{item.review_questions.map((question) => <li key={question}>{question}</li>)}</ul> : null}
        {item.success_reasons.map((reason) => <p key={reason.kind}>{reason.text}</p>)}
        {item.evidence.length ? <><h4>证据与原视频定位</h4><div className="bluff-review-evidence">{item.evidence.map((evidence, index) => <div key={index}><blockquote>{evidence.text}</blockquote>{evidence.interpretation ? <p>{evidence.interpretation}</p> : null}{evidence.image_url ? <figure className="bluff-frame"><a href={evidence.image_url} target="_blank" rel="noreferrer"><img src={evidence.image_url} alt={`原视频发言摘要 ${time(evidence.start_ms)}`} loading="lazy" /></a><figcaption>原视频截图 {time(evidence.start_ms)} · 点击查看原图</figcaption></figure> : null}{evidence.url ? <a href={evidence.url} target="_blank" rel="noreferrer">原视频 {time(evidence.start_ms)} ↗</a> : null}</div>)}</div></> : <p>{item.success_source === "user" ? "此条采用用户提交的人工复核结果。" : "当前没有足以确定发言归属的定位证据，需要回看该局警上发言。"}</p>}
        <p className="bluff-review-id">反馈编号：{item.review_id}</p>
        {!item.assistant_pending ? <BluffFeedbackFields item={item} /> : <p>此项留待助手继续核查，不需要你填写。</p>}
      </section>)}</div>
    </article>)}</div>
    {!data.items.length ? <div className="empty-state"><p>{status === "pending" ? "当前筛选下没有待复核项，可切换“全部推断”查看已识别记录。" : "当前筛选下没有悍跳推断记录。"}</p></div> : null}
  </div>;
}
