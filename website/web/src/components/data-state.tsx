import Link from "next/link";
import { ApiError } from "@/lib/api";

export function DataProblem({ error }: { error: unknown }) {
  const message = error instanceof ApiError ? error.message : "暂时无法读取档案数据，请稍后刷新重试。";
  const notFound = error instanceof ApiError && error.kind === "not-found";
  return (
    <section className="data-problem" role="status">
      <span className="problem-icon" aria-hidden="true">{notFound ? "⌕" : "↻"}</span>
      <div><h2>{notFound ? "档案暂不可用" : "数据服务暂不可用"}</h2><p>{message}</p><p className="problem-hint">页面不会展示演示数据。连接恢复后刷新即可查看最新发布版本。</p></div>
      <div className="problem-actions"><Link className="button button-primary" href="/">返回首页</Link><a className="button button-quiet" href="">刷新页面</a></div>
    </section>
  );
}
