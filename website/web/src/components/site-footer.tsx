import { ArchiveLink } from "@/components/archive-link";

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="footer-inner">
        <nav aria-label="页脚导航"><ArchiveLink href="/stats">数据说明</ArchiveLink><ArchiveLink href="/games">对局档案</ArchiveLink><ArchiveLink href="/players">选手索引</ArchiveLink></nav>
      </div>
    </footer>
  );
}
