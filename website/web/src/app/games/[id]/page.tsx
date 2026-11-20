import type { Metadata } from "next";
import { StaticGameBrowser } from "./static-game-browser";

export const metadata: Metadata = { title: "对局档案" };
export const generateStaticParams = async () => [{ id: "__static__" }];

export default function GameDetailPage() {
  return <StaticGameBrowser />;
}
