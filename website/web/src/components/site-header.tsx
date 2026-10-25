"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/", label: "首页" },
  { href: "/games", label: "对局" },
  { href: "/players", label: "选手" },
  { href: "/leaderboard?season=S22&phase=regular", label: "积分榜" },
  { href: "/stats", label: "数据说明" },
];

export function SiteHeader() {
  const pathname = usePathname();
  return (
    <header className="site-header">
      <div className="header-inner">
        <Link className="brand" href="/" aria-label="大师赛档案首页">
          <span className="brand-mark" aria-hidden="true">M<span>A</span></span>
          <span className="brand-copy"><strong>大师赛档案</strong></span>
        </Link>
        <nav className="main-nav" aria-label="主导航">
          {links.map((link) => {
            const linkPath = link.href.split("?")[0];
            const current = linkPath === "/" ? pathname === "/" : pathname.startsWith(linkPath);
            return <Link key={link.href} href={link.href} aria-current={current ? "page" : undefined}>{link.label}</Link>;
          })}
        </nav>
      </div>
    </header>
  );
}
