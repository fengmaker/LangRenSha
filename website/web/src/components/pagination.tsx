import Link from "next/link";

export function Pagination({ page, pageSize, total, params }: { page: number; pageSize: number; total: number; params: URLSearchParams }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const hrefFor = (nextPage: number) => {
    const query = new URLSearchParams(params);
    query.set("page", String(nextPage));
    query.set("page_size", String(pageSize));
    return "?" + query.toString();
  };
  if (pages <= 1) return <p className="pagination-summary">共 {total} 条记录</p>;
  return (
    <nav className="pagination" aria-label="结果分页">
      <span>第 <b>{page}</b> / {pages} 页 · 共 {total} 条</span>
      <div>{page > 1 ? <Link href={hrefFor(page - 1)}>← 上一页</Link> : <span className="disabled">← 上一页</span>}{page < pages ? <Link href={hrefFor(page + 1)}>下一页 →</Link> : <span className="disabled">下一页 →</span>}</div>
    </nav>
  );
}
