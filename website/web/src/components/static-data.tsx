"use client";

import { useEffect, useState, type ReactNode } from "react";
import { DataProblem } from "@/components/data-state";

/** Keep the exported HTML independent of the currently published snapshot. */
export function StaticData<T>({ load, children }: { load: () => Promise<T>; children: (data: T) => ReactNode }) {
  const [state, setState] = useState<{ data?: T; error?: unknown }>({});
  useEffect(() => {
    let active = true;
    load().then((data) => { if (active) setState({ data }); })
      .catch((error: unknown) => { if (active) setState({ error }); });
    return () => { active = false; };
  }, [load]);
  if (state.error) return <div className="page-wrap"><DataProblem error={state.error} /></div>;
  if (state.data === undefined) return <div className="page-wrap"><div className="route-loading" role="status">正在读取档案数据…</div></div>;
  return children(state.data);
}
