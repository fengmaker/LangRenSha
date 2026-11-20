import type { Metadata } from "next";
import { Suspense } from "react";
import { StaticStatsBrowser } from "./static-stats-browser";

export const metadata: Metadata = { title: "数据说明", description: "按赛季范围查看身份分布、版型胜率与统计口径。" };

export default function StatsPage() {
  return <Suspense fallback={<div className="page-wrap" role="status">正在读取统计数据…</div>}>
    <StaticStatsBrowser />
  </Suspense>;
}
