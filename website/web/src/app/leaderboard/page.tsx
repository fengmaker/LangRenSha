import type { Metadata } from "next";
import { readPageSnapshot } from "@/lib/static-page-data";
import type { Leaderboard, Overview } from "@/lib/types";
import { StaticLeaderboardBrowser } from "./static-leaderboard-browser";

export const metadata: Metadata = { title: "赛季积分榜", description: "按赛季和比赛阶段查看选手积分、出场、胜率与投票表现。" };

export default async function LeaderboardPage() {
  const { manifest, read } = await readPageSnapshot();
  const season = manifest.seasons.at(-1)!.id;
  const [overview, leaderboard] = await Promise.all([
    read<Overview>("overview.json"),
    read<Leaderboard>(`leaderboards/${season}/all.summary.json`),
  ]);
  return <StaticLeaderboardBrowser snapshotId={manifest.snapshot_id} initialData={leaderboard}
    seasons={manifest.seasons} seasonOptions={overview.seasons} />;
}
