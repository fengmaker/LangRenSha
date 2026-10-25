import Link from "next/link";
import type { GameSummary } from "@/lib/types";
import { formatDate, phaseLabel, winnerLabel } from "@/lib/format";

export function GameTable({ games, empty = "当前条件下没有对局。" }: { games: GameSummary[]; empty?: string }) {
  if (games.length === 0) return <div className="empty-state"><span className="empty-number">—</span><p>{empty}</p></div>;
  return (
    <div className="table-wrap">
      <table className="data-table game-table">
        <thead><tr><th>日期 / 场次</th><th>版型</th><th>对局结果</th><th>座位阵容</th><th>记录</th></tr></thead>
        <tbody>{games.map((game) => <tr key={game.id}>
          <td><Link className="game-date-link" href={"/games/" + encodeURIComponent(game.id)}><span>{formatDate(game.date)}</span><small>{game.season} · {phaseLabel(game.phase)}{game.game_number ? " · 第" + game.game_number + "局" : ""}</small></Link></td>
          <td><span className="board-name">{game.board?.name ?? "版型未知"}</span></td>
          <td><span className={"result-pill " + (game.winner === "good" ? "result-good" : game.winner === "werewolf" ? "result-wolf" : "result-unknown")}>{winnerLabel(game.winner)}</span></td>
          <td><div className="roster-inline">{(game.players ?? []).slice().sort((a, b) => a.seat - b.seat).map((player) => { const title = player.seat + "号 " + player.name + " · " + (player.role || "身份未知"); const contents = <><b>{player.seat}</b><span>{player.name}</span></>; return player.id ? <Link title={title} key={player.seat + "-" + player.id} href={"/players/" + encodeURIComponent(player.id)}>{contents}</Link> : <span title={title} key={player.seat + "-" + player.name}>{contents}</span>; })}</div></td>
          <td><div className="record-count"><span><b>{game.ballot_count}</b> 票型</span><span><b>{game.round_count}</b> 回合</span></div></td>
        </tr>)}</tbody>
      </table>
    </div>
  );
}
