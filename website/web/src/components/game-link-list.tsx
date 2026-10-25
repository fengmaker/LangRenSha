import Link from "next/link";
import type { GameSummary } from "@/lib/types";
import { formatDate, winnerLabel } from "@/lib/format";

export function GameLinkList({ games }: { games: GameSummary[] }) {
  if (!games.length) return <p className="lane-empty">暂无已关联的对局记录。</p>;
  return <div className="game-link-list">{games.map((game) => <Link key={game.id} href={"/games/" + encodeURIComponent(game.id)} className="game-link-row">
    <span className="game-link-date">{formatDate(game.date)}</span><span><strong>{game.board?.name ?? "版型未知"}</strong><small>{game.season} · {game.game_number ? "第" + game.game_number + "局" : "场次待核"}</small></span>
    <span className="result-pill result-unknown">{winnerLabel(game.winner)}</span><span className="row-arrow">↗</span>
  </Link>)}</div>;
}
