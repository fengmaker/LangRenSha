"use client";

import { Fragment, useId, useState } from "react";
import Link from "next/link";
import type { GameSummary } from "@/lib/types";
import { formatDate, phaseLabel, winnerLabel } from "@/lib/format";
import styles from "./game-archive-list.module.css";

function GameRows({ game }: { game: GameSummary }) {
  const [expanded, setExpanded] = useState(false);
  const rosterId = useId();
  const href = "/games/" + encodeURIComponent(game.id);
  const players = (game.players ?? []).slice().sort((a, b) => a.seat - b.seat);
  const resultStyle = game.winner === "good" ? styles.good : game.winner === "werewolf" ? styles.wolf : styles.unknown;
  const match = game.season + " · " + phaseLabel(game.phase) + (game.game_number ? " · 第" + game.game_number + "局" : "");

  return <Fragment>
    <tr className={styles.game} data-game-row>
      <td className={styles.dateCell}><Link className={styles.date} href={href}><time dateTime={game.date}>{formatDate(game.date)}</time><span>{match}</span></Link></td>
      <td className={styles.board}>{game.board?.name ?? "版型未知"}</td>
      <td className={styles.resultCell}><span className={styles.result + " " + resultStyle}>{winnerLabel(game.winner)}</span></td>
      <td className={styles.records}>{game.ballot_count} 票型<span aria-hidden="true"> · </span>{game.round_count} 回合</td>
      <td className={styles.actionCell}><div className={styles.actions}>
        {players.length ? <button type="button" aria-expanded={expanded} aria-controls={rosterId} onClick={() => setExpanded((value) => !value)} aria-label={(expanded ? "收起" : "查看") + " " + formatDate(game.date) + " " + match + " 座位阵容"}>阵容 <svg aria-hidden="true" viewBox="0 0 16 16" width="14" height="14" className={expanded ? styles.expanded : undefined}><path d="m4 6 4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg></button> : <span className={styles.noRoster}>阵容待补</span>}
        <Link href={href} aria-label={"查看 " + formatDate(game.date) + " " + match + " 对局"}>查看对局 <span aria-hidden="true">→</span></Link>
      </div></td>
    </tr>
    <tr className={styles.rosterRow} id={rosterId} hidden={!expanded}><td colSpan={5}>
      <ol className={styles.seats} aria-label={formatDate(game.date) + " " + match + " 座位阵容"}>{players.map((player) => {
        const content = <><span className={styles.seat}>{player.seat}</span><span className={styles.playerInfo}><strong>{player.name}</strong><span>{player.role || "身份未知"}</span></span></>;
        return <li key={player.seat + "-" + (player.id ?? player.name)}>{player.id
          ? <Link href={"/players/" + encodeURIComponent(player.id)} aria-label={player.seat + "号 " + player.name + " · " + (player.role || "身份未知")}>{content}</Link>
          : <div>{content}</div>}</li>;
      })}</ol>
    </td></tr>
  </Fragment>;
}

export function GameArchiveList({ games, empty = "没有符合条件的对局，试试调整或清除筛选条件。" }: { games: GameSummary[]; empty?: string }) {
  if (games.length === 0) return <p className={styles.empty}>{empty}</p>;
  return <div className={styles.wrap}><table className={styles.table}>
    <caption className={styles.srOnly}>对局记录</caption>
    <thead><tr><th scope="col">日期 / 场次</th><th scope="col">版型</th><th scope="col">结果</th><th scope="col">记录</th><th scope="col">操作</th></tr></thead>
    <tbody>{games.map((game) => <GameRows key={game.id} game={game} />)}</tbody>
  </table></div>;
}
