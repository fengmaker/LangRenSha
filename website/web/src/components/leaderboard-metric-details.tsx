"use client";

import { useId, useState, type ReactNode } from "react";

export function LeaderboardMetricDetails({ children }: { children: ReactNode }) {
  const [showDetails, setShowDetails] = useState(false);
  const tableId = useId();

  return <div className="leaderboard-metric-details" data-show-calculations={showDetails}>
    <div className="leaderboard-detail-controls">
      <a href="#leaderboard-calculation-rules" className="leaderboard-rules-link" onClick={() => { const rules = document.getElementById("leaderboard-calculation-rules"); if (rules instanceof HTMLDetailsElement) rules.open = true; }}>指标计算规则</a>
      <button type="button" className="button" aria-pressed={showDetails} aria-controls={tableId}
        onClick={() => setShowDetails((current) => !current)}>
        {showDetails ? "隐藏计算明细" : "显示计算明细"}
      </button>
    </div>
    <div id={tableId}>{children}</div>
  </div>;
}
