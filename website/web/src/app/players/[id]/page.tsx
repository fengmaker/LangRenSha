import type { Metadata } from "next";
import { Suspense } from "react";
import { StaticPlayerBrowser } from "./static-player-browser";

export const metadata: Metadata = { title: "选手档案" };
export const generateStaticParams = async () => [{ id: "__static__" }];

export default function PlayerDetailPage() {
  return <Suspense fallback={<div className="page-wrap" role="status">正在读取选手档案…</div>}>
    <StaticPlayerBrowser />
  </Suspense>;
}
