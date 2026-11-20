import type { Metadata } from "next";
import { Suspense } from "react";
import { StaticPlayersBrowser } from "./static-players-browser";

export const metadata: Metadata = { title: "选手索引", description: "检索大师赛选手档案、身份分布与相关对局。" };

export default function PlayersPage() {
  return <Suspense fallback={<div className="page-wrap" role="status">正在读取选手索引…</div>}>
    <StaticPlayersBrowser />
  </Suspense>;
}
