import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "档案未找到" };

export default function NotFound() {
  return <div className="page-wrap"><section className="not-found-card"><span className="not-found-code">404</span><h1>没有找到这条档案</h1><p>该对局或选手记录可能尚未发布，或档案链接已经变更。</p><div><Link className="button button-primary" href="/games">浏览对局档案 <span>→</span></Link><Link className="button button-outline" href="/players">搜索选手 <span>→</span></Link></div></section></div>;
}
