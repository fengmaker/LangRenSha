"use client";

import { StaticData } from "@/components/static-data";
import { fetchGame, staticRouteId } from "@/lib/static-browser";
import { GameDetailView } from "./game-detail-view";

async function loadGame() {
  const game = await fetchGame(staticRouteId("games"));
  document.title = `${game.board?.name ? game.board.name + " 对局档案" : "对局档案"} · 大师赛档案`;
  return game;
}

export function StaticGameBrowser() {
  return <StaticData load={loadGame}>{(game) => <GameDetailView game={game} />}</StaticData>;
}
