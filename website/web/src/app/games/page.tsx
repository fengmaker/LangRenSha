import type { Metadata } from "next";
import { Suspense } from "react";
import { StaticGamesBrowser } from "./static-games-browser";
import styles from "./games.module.css";

export const metadata: Metadata = { title: "对局档案", description: "检索大师赛各赛季的对局、票型和选手记录。" };

export default function GamesPage() {
  return <div className={"page-wrap " + styles.page}>
    <header className={styles.intro}><h1>对局档案</h1><p>按日期、赛季、阶段、版型或选手，找到想看的对局。</p></header>
    <Suspense fallback={<p>正在载入筛选条件…</p>}><StaticGamesBrowser /></Suspense>
  </div>;
}
