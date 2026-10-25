import Link from "next/link";

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="footer-inner">
        <nav aria-label="页脚导航"><Link href="/stats">数据说明</Link><Link href="/games">对局档案</Link><Link href="/players">选手索引</Link></nav>
      </div>
    </footer>
  );
}
