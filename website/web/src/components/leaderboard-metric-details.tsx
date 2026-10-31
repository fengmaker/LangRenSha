"use client";

import { createContext, useContext, useId, useState, type ReactNode } from "react";
import type { Leaderboard } from "@/lib/types";
import { formatNumber } from "@/lib/format";
import { MetricSamples, type SampleLabels, type SampleMetric } from "./metric-samples";

const SampleGames = createContext<Leaderboard["sample_games"]>([]);
const ShowDetails = createContext(false);
const outcomes: Record<string, [string, string, "场" | "次"]> = {
  出场率: ["出场", "未出场", "场"], 整季胜率: ["获胜", "失利", "场"],
  上警率: ["上警", "未上警", "场"], 好人胜率: ["获胜", "失利", "场"],
  投狼率: ["投中狼人", "未投中狼人", "次"], 好人上警率: ["上警", "未上警", "场"],
  好人警下率: ["警下", "上警", "场"], 警徽正确率: ["投对", "未投对", "次"],
  好人站边率: ["站边正确", "站边错误", "次"], 狼人胜率: ["获胜", "失利", "场"],
  拿狼率: ["狼人阵营", "好人阵营", "场"], 自爆率: ["自爆", "未自爆", "场"],
  狼人上警率: ["上警", "未上警", "场"],
  悍跳率: ["悍跳", "未悍跳", "场"], 悍跳成功率: ["成功", "失败", "场"],
};

export function LeaderboardSampleLink({ label, metric, playerId, playerName }: {
  label: string; metric: SampleMetric; playerId: string; playerName: string;
}) {
  const allGames = useContext(SampleGames);
  const showDetails = useContext(ShowDetails);
  if (!showDetails) return <span className="leaderboard-rate-equation">{formatNumber(metric.numerator)} / {formatNumber(metric.denominator)}</span>;
  const ids = new Set((metric.samples ?? []).map((sample) => sample.game_id));
  const games = allGames.filter((game) => ids.has(game.game_id)).map((game) => ({
    ...game, role: playerId in game.roles ? game.roles[playerId] : "未出场",
  }));
  const [positive, negative, unit] = outcomes[label];
  const labels: SampleLabels = { positive, negative, unit,
    description: `正面样本为${positive}记录，负面样本为${negative}记录。${unit === "次" ? "按投票轮次统计；同一局可同时包含正面和负面样本。" : "每位选手每局计一次。"}` };
  return <MetricSamples label={`${playerName} · ${label}`} metric={metric} games={games} labels={labels}
    trigger={<>{formatNumber(metric.numerator)} / {formatNumber(metric.denominator)} <span aria-hidden="true">↗</span></>} />;
}

export function LeaderboardMetricDetails({ children, sampleGames }: { children: ReactNode; sampleGames: Leaderboard["sample_games"] }) {
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
    <ShowDetails.Provider value={showDetails}><SampleGames.Provider value={sampleGames}><div id={tableId}>{children}</div></SampleGames.Provider></ShowDetails.Provider>
  </div>;
}
