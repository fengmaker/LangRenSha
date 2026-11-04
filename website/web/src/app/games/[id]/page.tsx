import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ApiError, getGame } from "@/lib/api";
import { isStaticSite } from "@/lib/site-mode";
import { DataProblem } from "@/components/data-state";
import { GameDetailView } from "./game-detail-view";
import { StaticGameBrowser } from "./static-game-browser";

function safeMetadataId(id: string): string {
  return id.replace(/[^A-Za-z0-9_-]/g, "").slice(0, 14) || "档案";
}

export const generateStaticParams = isStaticSite ? async () => [{ id: "__static__" }] : undefined;

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  if (isStaticSite) return { title: "对局档案" };
  const { id } = await params;
  try {
    const game = await getGame(id);
    return { title: game.board?.name ? game.board.name + " 对局档案" : "对局档案" };
  } catch (error) {
    if (error instanceof ApiError && error.kind === "not-found") return { title: "对局未找到" };
    return { title: "对局档案 " + safeMetadataId(id) };
  }
}

export default async function GameDetailPage({ params }: { params: Promise<{ id: string }> }) {
  if (isStaticSite) return <StaticGameBrowser />;
  const { id } = await params;
  try {
    return <GameDetailView game={await getGame(id)} />;
  } catch (error) {
    if (error instanceof ApiError && error.kind === "not-found") notFound();
    return <div className="page-wrap"><DataProblem error={error} /></div>;
  }
}
