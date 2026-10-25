import Link from "next/link";
import type { Metadata } from "next";
import { getBluffReview } from "@/lib/api";
import { DataProblem } from "@/components/data-state";
import { PageIntro } from "@/components/page-intro";
import type { BluffReview, SearchParams } from "@/lib/types";
import { BluffFeedbackTools } from "@/components/bluff-feedback-tools";
import { BluffFeedbackFields } from "@/components/bluff-feedback-fields";

export const metadata: Metadata = { title: "悍跳推断与复核" };
function first(value: string | string[] | undefined) { return Array.isArray(value) ? value[0] ?? "" : value ?? ""; }
function time(ms?: number) {
  if (ms === undefined) return "定位片段";
  const seconds = Math.floor(ms / 1000);
  return [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60].map((n) => String(n).padStart(2, "0")).join(":");
}
function statusLabel(item: BluffReview["items"][number]) {
  if (item.verification_status === "user_confirmed") {
    if (item.decision === "no") return "用户确认不是悍跳";
    return `用户确认悍跳 · ${item.success === null ? "成功结果待补" : item.success ? "按规则成功" : "按规则未成功"}`;
  }
  return item.decision === "uncertain" ? "悍跳归属待复核" : item.decision === "no" ? "推断不是悍跳" : item.success === null ? "成功结果待复核" : item.success ? "推断成功" : "推断未成功";
}

export default async function BluffReviewPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const query = await searchParams;
  const rawSeason = first(query.season) || "S22";
  const season = /^[A-Za-z0-9_-]{1,20}$/.test(rawSeason) ? rawSeason : "S22";
  const status = first(query.status) === "all" ? "all" : "pending";
  const rawPlayer = first(query.player);
  const player = /^[A-Za-z0-9_-]{1,100}$/.test(rawPlayer) ? rawPlayer : "";
  let data: Awaited<ReturnType<typeof getBluffReview>>;
  try { data = await getBluffReview(season, status, player); }
  catch (error) { return <div className="page-wrap"><PageIntro title="悍跳推断与复核" description="按逐局原文证据回查悍跳归属与成功结果。" /><DataProblem error={error} /></div>; }
  const href = (nextStatus: "all" | "pending") => `/leaderboard/bluff-review?${new URLSearchParams({ season, status: nextStatus, player })}`;
  return <div className="page-wrap">
    <div className="breadcrumb"><Link href={`/leaderboard?season=${encodeURIComponent(season)}`}>积分榜</Link><span>/</span><span>悍跳推断与复核</span></div>
    <PageIntro title={`${season} 悍跳推断与复核`} description="对照原文与视频回查推断，逐条标明用户确认或助手推断。" />
    <section className="leaderboard-summary"><article><span>已识别悍跳</span><strong>{data.summary.identified_bluffs}</strong></article><article><span>按规则判定成功</span><strong>{data.summary.successes}</strong></article><article><span>待复核</span><strong>{data.summary.pending}</strong></article><article><span>整季对局范围</span><strong>{data.summary.games}</strong></article></section>
    <details className="methodology-details"><summary>查看本次判定口径</summary><ul>{data.notes.map((note) => <li key={note}>{note}</li>)}</ul></details>
    <nav className="leaderboard-tabs bluff-review-tabs" aria-label="悍跳复核范围"><Link href={href("pending")} aria-current={status === "pending" ? "page" : undefined}>待复核</Link><Link href={href("all")} aria-current={status === "all" ? "page" : undefined}>全部推断</Link>{player ? <Link href={`/leaderboard/bluff-review?season=${encodeURIComponent(season)}&status=${status}`}>查看全部选手</Link> : null}</nav>
    <BluffFeedbackTools season={season} inferenceVersion={data.inference_version} scopeKey={`${status}:${player}`} />
    <div className="bluff-review-list">{data.items.map((item) => <article className="bluff-review-card" key={`${item.game_id}-${item.seat}`}>
      <header><div><p className="review-meta">{item.date} · 第{item.game_number ?? "?"}局 · {item.seat}号</p><h2>{item.name} <span>{item.physical_role}{item.claimed_role ? ` → 自称${item.claimed_role}` : ""}</span></h2></div><strong className={item.needs_review ? "bluff-status-pending" : "bluff-status-known"}>{statusLabel(item)}</strong></header>
      <p>{item.first_day_claim === true ? "起跳阶段：第一天" : item.claim_day === 2 ? "起跳阶段：第二天／延期竞选" : "起跳阶段：见证据与前后推断"}</p>{item.decision_note ? <p>{item.decision_note}</p> : null}
      {item.review_questions.length ? <ul className="bluff-review-questions">{item.review_questions.map((question) => <li key={question}>{question}</li>)}</ul> : null}
      {item.success_reasons.map((reason) => <p key={reason.kind}>{reason.text}</p>)}
      {item.evidence.length ? <div className="bluff-review-evidence">{item.evidence.map((evidence, index) => <div key={index}><blockquote>{evidence.text}</blockquote>{evidence.interpretation ? <p>{evidence.interpretation}</p> : null}{evidence.url ? <a href={evidence.url} target="_blank" rel="noreferrer">原视频 {time(evidence.start_ms)} ↗</a> : null}</div>)}</div> : <p>当前没有足以确定发言归属的定位证据，需要回看该局警上发言。</p>}
      <Link href={`/games/${encodeURIComponent(item.game_id)}`}>对照该局底牌、警徽与最终放逐记录 →</Link><p className="bluff-review-id">反馈编号：{item.review_id}</p>
      <BluffFeedbackFields item={item} />
    </article>)}</div>
    {!data.items.length ? <div className="empty-state"><p>{status === "pending" ? "当前筛选下没有待复核项，可切换“全部推断”查看已识别记录。" : "当前筛选下没有悍跳推断记录。"}</p></div> : null}
  </div>;
}
