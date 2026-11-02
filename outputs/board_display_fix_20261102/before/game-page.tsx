import Link from "next/link";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ApiError, getGame } from "@/lib/api";
import { formatDate, gamePhaseLabel, gameTimeText, phaseLabel, winnerLabel } from "@/lib/format";
import { DataProblem } from "@/components/data-state";
import { EventBoard } from "@/components/event-board";
import { SeatGrid } from "@/components/seat-grid";
import styles from "./detail.module.css";

function safeMetadataId(id: string): string {
  return id.replace(/[^A-Za-z0-9_-]/g, "").slice(0, 14) || "档案";
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  try {
    const game = await getGame(id);
    return { title: game.board?.name ? game.board.name + " 对局档案" : "对局档案" };
  } catch (error) {
    if (error instanceof ApiError && error.kind === "not-found") return { title: "对局未找到" };
    return { title: "对局档案 " + safeMetadataId(id) };
  }
}

function safeHttpUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try { const url = new URL(value); return url.protocol === "https:" || url.protocol === "http:" ? url.toString() : null; } catch { return null; }
}

function publicNote(value: string): string {
  return gameTimeText(value.replace(/(?:[A-Za-z]:\\|(?:\.\.?[\\/])|(?:data|outputs|transcripts|extractions)[\\/])[^\s，。；、]+/gi, "来源文件路径已隐藏"));
}

function endgameKindLabel(value: string | undefined): string {
  const labels: Record<string, string> = { wolf_rush: "狼人拍刀" };
  return value ? labels[value] ?? "终局阶段" : "终局阶段";
}

function endgameResultLabel(value: string): string {
  const labels: Record<string, string> = { good_win: "好人阵营胜", werewolf_win: "狼人阵营胜", unknown: "结果未知" };
  return labels[value] ?? "结果已记录";
}

function finalWinnerLabel(value: string | null | undefined): string {
  if (value === "good" || value === "good_win") return "好人阵营获胜";
  if (value === "werewolf" || value === "werewolf_win") return "狼人阵营获胜";
  if (value === "draw") return "本局平局";
  return "胜负结果待核";
}

export default async function GameDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  try {
    const game = await getGame(id);
    const sourceUrl = safeHttpUrl(game.source?.url);
    const endgamePhases = game.endgame?.phases ?? [];
    return <div className={"page-wrap detail-page " + styles.page}>
      <nav className="breadcrumb" aria-label="面包屑"><Link href="/games">对局档案</Link><span aria-hidden="true">/</span><span aria-current="page">{game.season} · {formatDate(game.date)}</span></nav>
      <header className="match-hero">
        <div className="match-hero-main"><h1>{game.board?.name ?? "版型未知"}</h1><p className="match-date"><span>{game.season} · {phaseLabel(game.phase)}</span><time dateTime={game.date}>{formatDate(game.date)}</time><span>{game.game_number ? `第 ${game.game_number} 局` : "局次待核"}</span></p></div>
        <div className="match-outcome" data-winner={game.winner ?? "unknown"}><span>本局结果</span><strong>{winnerLabel(game.winner)}</strong></div>
        <dl className="match-credits">
          <div><dt>解说</dt><dd>{game.commentators?.length ? game.commentators.join("、") : "未记录"}</dd></div>
          <div><dt>裁判</dt><dd>{game.referee || "未记录"}</dd></div>
          <div className="match-source"><dt>比赛录像</dt><dd>{sourceUrl ? <a href={sourceUrl} target="_blank" rel="noreferrer">观看原始视频</a> : "来源链接未提供"}{game.source?.bvid ? <code>{game.source.bvid}</code> : null}</dd></div>
        </dl>
      </header>
      <nav className="match-section-nav" aria-label="对局档案章节"><a href="#game-seats">身份与座位</a><a href="#game-recap">逐轮复盘</a>{endgamePhases.length ? <a href="#game-endgame">拍刀与终局</a> : null}</nav>

      <section className="detail-section" id="game-seats" tabIndex={-1}>
        <div className="section-heading"><div><h2>身份与座位</h2><p className="section-subtitle">按本局阵营归类，保留每位选手的真实底牌。</p></div></div>
        <SeatGrid seats={game.seats ?? []} rounds={game.rounds ?? []} season={game.season} />
      </section>

      <section className="detail-section" id="game-recap" tabIndex={-1}>
        <div className="section-heading"><div><h2>日夜事件与票型记录</h2><p className="section-subtitle">从首夜开始逐轮复盘，投票与对应白天一起阅读。</p></div></div>
        <EventBoard timeline={game.timeline} seats={game.seats ?? []} />
      </section>

      {endgamePhases.length ? <section className="detail-section endgame-section" id="game-endgame" tabIndex={-1}>
        <div className="section-heading"><div><h2>拍刀与终局</h2></div></div>
        {endgamePhases.length ? <div className="endgame-list">{endgamePhases.map((phase, index) => <article className="endgame-card" key={index}><div><h3>{endgameKindLabel(phase.kind ?? phase.phase)}{phase.day ? <span className="endgame-day">{gamePhaseLabel(phase.day, "day")}</span> : null}</h3><p>{phase.actor ? phase.actor + " 号行动" : "行动者未知"}{Array.isArray(phase.declared_targets) && phase.declared_targets.length ? " · 明确提及目标 " + phase.declared_targets.map(String).join("、") + " 号" : ""}{phase.result ? " · " + endgameResultLabel(phase.result) : ""}</p>{phase.note ? <small>{publicNote(phase.note)}</small> : null}</div></article>)}</div> : <div className="empty-state compact-empty"><span className="empty-number">—</span><p>当前发布版本没有独立的终局阶段记录。</p></div>}
      </section> : null}

      <section className="game-finish" data-winner={game.winner ?? "unknown"} aria-label="游戏结束">
        <span>游戏结束</span><h2>{finalWinnerLabel(game.winner)}</h2>
      </section>

      {game.data_notes?.length ? <details className="match-record-notes"><summary>复盘补充说明</summary><ul>{game.data_notes.map((note, index) => <li key={index}>{publicNote(note)}</li>)}</ul></details> : null}
      <details className="release-details"><summary>查看此页的数据版本</summary><div className="release-detail-content"><span>发布版本 <code>{game.release_id}</code></span></div></details>
    </div>;
  } catch (error) {
    if (error instanceof ApiError && error.kind === "not-found") notFound();
    return <div className="page-wrap"><DataProblem error={error} /></div>;
  }
}
