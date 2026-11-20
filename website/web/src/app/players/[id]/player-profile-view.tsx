"use client";

import { ArchiveLink } from "@/components/archive-link";
import { useState, type ReactNode } from "react";
import type { Metric, MetricRanking, PerformanceKey, PlayerDetail, PlayerLedgerEntry, PlayerRankingKey, PlayerStats, RankingEntry } from "@/lib/types";
import { formatDate, formatNumber, phaseLabel, factionLabel } from "@/lib/format";
import { publicPagePath } from "@/lib/site-mode";
import { StaticPlayerPhoto } from "@/components/static-player-photo";
import styles from "./player-detail.module.css";
import { SeasonRangeFilter } from "./season-range-filter";
import { MetricSamples, type SampleLabels } from "@/components/metric-samples";
import { MetricRank, type RankingContext } from "./metric-rank";
import { PlayerChapterNav, profileChapters } from "./player-chapters";
import { BoardWinRates, RoleWinRates, rateText } from "./player-win-distributions";

function countMetricText(metric: Metric): string {
  if (metric.excluded > 0) return metric.numerator > 0 ? `≥${formatNumber(metric.numerator)}` : "—";
  return formatNumber(metric.numerator);
}
function MetricCard({ label, value, note, metric, games, sampleLabels, breakdown, ranking, rankLabel, provisional, rankingBoard, rankContext, format }: { label: string; value: string; note?: string; metric?: Metric; games?: PlayerLedgerEntry[]; sampleLabels?: SampleLabels; breakdown?: ReactNode; ranking?: MetricRanking | null; rankLabel?: string; provisional?: boolean; rankingBoard?: RankingEntry[]; rankContext: RankingContext; format?: "count" | "percent" | "points" }) {
  const sampleIds = new Set((metric?.samples ?? []).map((sample) => sample.game_id));
  const hasSamples = metric && sampleLabels;
  return <article className="profile-stat-card"><div className="metric-copy"><span>{label}</span><strong>{value}</strong>{note ? <small>{note}</small> : null}</div>
    <div className="metric-actions">{rankingBoard !== undefined || ranking !== undefined ? <div className="profile-metric-ranks"><MetricRank ranking={ranking} label={rankLabel} provisional={provisional} entries={rankingBoard} metricLabel={rankLabel ?? label} format={format ?? (label.includes("率") ? "percent" : label === "赛季积分" ? "points" : "count")} sampleUnit={sampleLabels?.unit} context={rankContext} /></div> : null}
      {hasSamples ? <MetricSamples label={label} metric={metric} games={(games ?? []).filter((game) => sampleIds.has(game.game_id))} labels={sampleLabels} breakdown={breakdown} /> : null}
    </div>
  </article>;
}
type PerformanceCardDefinition = { key: PerformanceKey; label: string; format: "count" | "percent"; rankKey?: PlayerRankingKey; sampleLabels: SampleLabels };
const witchCards: PerformanceCardDefinition[] = [
  { key: "witch_poison_count", rankKey: "witch_poison_count", label: "女巫施毒次数", format: "count", sampleLabels: { positive: "使用毒药", negative: "未使用毒药", unit: "场", description: "按女巫和毒师的对局统计。整局用过毒药计为正面样本，确认整局未用毒药计为负面样本。" } },
  { key: "witch_poison_wolf_rate", rankKey: "witch_poison_wolf_rate", label: "女巫毒狼率", format: "percent", sampleLabels: { positive: "目标为狼人", negative: "目标为好人", unit: "次", description: "按女巫和毒师的毒药原始选择目标统计，目标阵营未知时排除。" } },
  { key: "witch_poison_wolf_kills", rankKey: "witch_poison_wolf_kills", label: "女巫毒杀狼人次数", format: "count", sampleLabels: { positive: "毒杀狼人", negative: "未毒杀狼人", unit: "次", description: "合计女巫和毒师实际毒杀狼人的记录，结算或实际死者阵营无法判定时排除。" } },
];
const hunterCards: PerformanceCardDefinition[] = [
  { key: "hunter_shot_count", rankKey: "hunter_shot_count", label: "猎人开枪次数", format: "count", sampleLabels: { positive: "开枪", negative: "未开枪", unit: "次", description: "按猎人开枪行动记录；明确未开枪的可判定机会列为负面样本。" } },
  { key: "hunter_shot_wolf_rate", rankKey: "hunter_shot_wolf_rate", label: "猎人枪狼率", format: "percent", sampleLabels: { positive: "目标为狼人", negative: "目标为好人", unit: "次", description: "按开枪原始选择目标统计；目标阵营未知时排除。目标是否死亡由击杀狼人次数单独统计。" } },
  { key: "hunter_shot_wolf_kills", rankKey: "hunter_shot_wolf_kills", label: "猎人击杀狼人次数", format: "count", sampleLabels: { positive: "击杀狼人", negative: "未击杀狼人", unit: "次", description: "按开枪结算统计实际击杀狼人的次数；目标阵营或结算结果无法判定时排除。" } },
];
const seerCards: PerformanceCardDefinition[] = [
  { key: "seer_campaign_count", rankKey: "seer_campaign_count", label: "预言家竞选次数", format: "count", sampleLabels: { positive: "上警竞选", negative: "未上警", unit: "场", description: "按预言家 / 通灵师的首次上警报名记录统计。" } },
  { key: "seer_badge_count", rankKey: "seer_badge_count", label: "预言家获得警徽次数", format: "count", sampleLabels: { positive: "获得警徽", negative: "未获得警徽", unit: "场", description: "按预言家 / 通灵师的竞选结果统计。" } },
  { key: "seer_first_day_exiled", rankKey: "seer_first_day_exiled", label: "预言家首日被放逐次数", format: "count", sampleLabels: { positive: "首日被放逐", negative: "首日未被放逐", unit: "场", description: "按预言家 / 通灵师是否在首日被放逐统计。" } },
];
const guardKnifeDescription = "按实际守护的夜晚统计，比较守护对象与同夜普通狼刀的原始目标。任一方目标未知时排除。";
const guardCards: PerformanceCardDefinition[] = [
  { key: "guard_count", rankKey: "guard_count", label: "守卫守护次数", format: "count", sampleLabels: { positive: "守护", negative: "空守", unit: "次", description: "按守卫明确守护或空守的夜晚统计，自守计为守护。" } },
  { key: "guard_knife_hits", rankKey: "guard_knife_hits", label: "守中狼刀次数", format: "count", sampleLabels: { positive: "守中狼刀", negative: "未守中狼刀", unit: "次", description: guardKnifeDescription } },
  { key: "guard_knife_hit_rate", rankKey: "guard_knife_hit_rate", label: "守中狼刀率", format: "percent", sampleLabels: { positive: "守中狼刀", negative: "未守中狼刀", unit: "次", description: guardKnifeDescription } },
];
const divineRoleTabs = [
  { id: "witch", label: "女巫·毒师", roles: ["女巫", "毒师"], cards: witchCards },
  { id: "hunter", label: "猎人", roles: ["猎人"], cards: hunterCards },
  { id: "seer", label: "预言家·通灵师", roles: ["预言家", "通灵师"], cards: seerCards },
  { id: "guard", label: "守卫", roles: ["守卫"], cards: guardCards },
];

const mechanicalWolfSamples: SampleLabels = { positive: "拿到机械狼", negative: "狼阵营其他身份", unit: "场", description: "只统计机械狼版型中狼人阵营的场次。机械狼率为拿到机械狼的场次占该范围中身份可判定场次的比例。" };
const mechanicalWolfCards: PerformanceCardDefinition[] = [
  { key: "mechanical_wolf_count", rankKey: "mechanical_wolf_count", label: "机械狼次数", format: "count", sampleLabels: mechanicalWolfSamples },
  { key: "mechanical_wolf_rate", rankKey: "mechanical_wolf_rate", label: "机械狼率", format: "percent", sampleLabels: mechanicalWolfSamples },
];

const mechanicalPoisonCards: PerformanceCardDefinition[] = [
  { key: "mechanical_poison_count", rankKey: "mechanical_poison_count", label: "机械狼施毒次数", format: "count", sampleLabels: { positive: "使用毒药", negative: "未使用毒药", unit: "次", description: "按机械狼学习毒药后的行动记录；未发动的可判定机会列为负面样本。" } },
  { key: "mechanical_poison_god_kills", rankKey: "mechanical_poison_god_kills", label: "机械狼毒神次数", format: "count", sampleLabels: { positive: "毒杀神职", negative: "未毒杀神职", unit: "次", description: "按机械女巫毒药结算统计实际毒杀神职的次数，结算或实际死者身份未知时排除。" } },
];
const mechanicalShotCards: PerformanceCardDefinition[] = [
  { key: "mechanical_shot_count", rankKey: "mechanical_shot_count", label: "机械狼开枪次数", format: "count", sampleLabels: { positive: "开枪", negative: "未开枪", unit: "次", description: "按机械狼学习猎人技能后的开枪行动记录；未发动的可判定机会列为负面样本。" } },
  { key: "mechanical_shot_god_kills", rankKey: "mechanical_shot_god_kills", label: "机械狼枪神次数", format: "count", sampleLabels: { positive: "开枪带走神职", negative: "未开枪带走神职", unit: "次", description: "按机械猎人开枪结算统计实际带走神职的次数，结算或实际死者身份未知时排除。" } },
];
const mechanicalGuardCards: PerformanceCardDefinition[] = [
  { key: "mechanical_guard_count", rankKey: "mechanical_guard_count", label: "机械狼守护次数", format: "count", sampleLabels: { positive: "守护", negative: "空守", unit: "次", description: "按机械守卫明确守护或空守的夜晚统计，自守计为守护。" } },
  { key: "mechanical_reflect_god_kills", rankKey: "mechanical_reflect_god_kills", label: "机械狼弹毒神次数", format: "count", sampleLabels: { positive: "反弹毒药带走神职", negative: "未反弹毒药带走神职", unit: "次", description: "按机械守卫结算统计反弹毒药后实际带走神职的次数，结算或实际死者身份未知时排除。" } },
];
const mechanicalCheckCards: PerformanceCardDefinition[] = [
  { key: "mechanical_check_count", rankKey: "mechanical_check_count", label: "机械狼查验次数", format: "count", sampleLabels: { positive: "查验", negative: "未查验", unit: "次", description: "按机械通灵师明确查验或空过的记录统计。" } },
];
const mechanicalAttackCards: PerformanceCardDefinition[] = [
  { key: "mechanical_extra_attack_count", rankKey: "mechanical_extra_attack_count", label: "机械狼技能刀次数", format: "count", sampleLabels: { positive: "使用技能刀", negative: "未使用技能刀", unit: "次", description: "按机械双刀狼明确使用或空过的额外技能刀统计，接手的普通狼刀另行记录。" } },
];
const mechanicalForms = [
  { id: "机械双刀狼", label: "双刀", cards: mechanicalAttackCards },
  { id: "机械猎人", label: "猎人", cards: mechanicalShotCards },
  { id: "机械女巫", label: "女巫", cards: mechanicalPoisonCards },
  { id: "机械通灵师", label: "预言家·通灵师", cards: mechanicalCheckCards },
  { id: "机械守卫", label: "守卫", cards: mechanicalGuardCards },
  { id: "机械平民", label: "平民", cards: [] },
];
const bluffStageCards: PerformanceCardDefinition[] = [
  { key: "bluff_badge_count", rankKey: "bluff_badge_count", label: "悍跳获得警徽次数", format: "count", sampleLabels: { positive: "获得警徽", negative: "未获得警徽", unit: "场", description: "按已确认悍跳者在本局的竞选当选结果统计；延期竞选仍计，之后接到移交的警徽不计。" } },
  { key: "bluff_first_day_exiled", rankKey: "bluff_first_day_exiled", label: "悍跳首日被放逐次数", format: "count", sampleLabels: { positive: "首日被放逐", negative: "首日未被放逐", unit: "场", description: "按已确认悍跳者是否在首日被放逐统计。" } },
];
const lifecycleCards: PerformanceCardDefinition[] = [
  { key: "first_night_targeted", rankKey: "first_night_targeted", label: "首夜狼刀目标次数", format: "count", sampleLabels: { positive: "成为狼刀目标", negative: "未成为狼刀目标", unit: "场", description: "按首夜狼人原始狼刀目标统计；即使目标获救仍计入，狼刀目标不等同于首夜死亡。" } },
  { key: "first_night_death", rankKey: "first_night_death", label: "首夜死亡次数", format: "count", sampleLabels: { positive: "首夜死亡", negative: "首夜存活", unit: "场", description: "按该选手是否在首夜死亡统计。" } },
  { key: "first_day_exiled", rankKey: "first_day_exiled", label: "首日被放逐次数", format: "count", sampleLabels: { positive: "首日被放逐", negative: "首日未被放逐", unit: "场", description: "按该选手是否在首日被放逐统计。" } },
];

function MechanicalLearningDistribution({ games }: { games: PlayerLedgerEntry[] }) {
  const counts = new Map<string, number>();
  for (const { mechanical_learned_role: role } of games) {
    if (role) counts.set(role, (counts.get(role) ?? 0) + 1);
  }
  const rows = mechanicalForms.map(({ id, label }) => ({ label, count: counts.get(id) ?? 0 }));
  const total = rows.reduce((sum, row) => sum + row.count, 0);
  return <table className={styles.learningDistribution}>
    <thead><tr><th scope="col">学到的身份</th><th scope="col">场次</th><th scope="col">占已确认形态场次</th></tr></thead>
    <tbody>{rows.map(({ label, count }) => <tr key={label}>
      <th scope="row">{label}</th>
      <td>{formatNumber(count)}</td>
      <td>{rateText(total ? count / total : null)}</td>
    </tr>)}</tbody>
  </table>;
}

function PerformanceMetricGrid({ cards, metrics, rankings, rankingBoards, games, rankContext, grid = true, showEmpty = true }: { cards: readonly PerformanceCardDefinition[]; metrics?: PlayerStats["performance"]; rankings?: PlayerStats["rankings"]; rankingBoards?: PlayerStats["ranking_boards"]; games: PlayerLedgerEntry[]; rankContext: RankingContext; grid?: boolean; showEmpty?: boolean }) {
  const availableCards = cards.filter((card) => metrics?.[card.key] !== undefined);
  if (!availableCards.length) return showEmpty ? <p className="lane-empty">当前范围内暂无已记录的统计项。</p> : null;
  const cardItems = availableCards.map((card) => {
    const metric = metrics?.[card.key];
    if (!metric) return null;
    return <MetricCard key={card.key} rankContext={rankContext} label={card.label} value={card.format === "percent" ? rateText(metric.rate) : countMetricText(metric)} format={card.format} metric={metric} games={games} sampleLabels={card.sampleLabels} rankingBoard={card.rankKey ? rankingBoards?.[card.rankKey] : undefined} ranking={card.rankKey ? rankings?.[card.rankKey] : undefined} />;
  });
  return grid ? <div className="profile-stat-grid">{cardItems}</div> : <>{cardItems}</>;
}
function LedgerTable({ ledger, singleSeason }: { ledger: PlayerLedgerEntry[]; singleSeason: boolean }) {
  if (!ledger.length) return <div className="empty-state"><span className="empty-number">—</span><p>当前时间范围内暂无对局记录。</p></div>;
  return <div className="data-table-scroll"><table className="ledger-table" data-single-season={singleSeason}><colgroup><col className="ledger-game-col" /><col className="ledger-phase-col" /><col className="ledger-role-col" /><col className="ledger-result-col" />{singleSeason ? <col className="ledger-points-col" /> : null}</colgroup><thead><tr><th scope="col">对局</th><th scope="col">阶段 / 版型</th><th scope="col">身份</th><th scope="col">结果</th>{singleSeason ? <th scope="col">赛季累计积分</th> : null}</tr></thead><tbody>{ledger.map((entry, index) => <tr key={`${entry.game_id}-${index}`}>
    <td><ArchiveLink className="ledger-game-link" href={`/games/${encodeURIComponent(entry.game_id)}`}><time dateTime={entry.date}>{formatDate(entry.date)}</time><small>{entry.season ? `${entry.season} · ` : ""}{entry.game_number ? `第 ${entry.game_number} 局` : entry.game_id}</small></ArchiveLink></td>
    <td>{phaseLabel(entry.phase)}<small>{entry.board_name || "版型待核"}</small></td><td>{entry.role_label || entry.role || "身份待核"}<small>{factionLabel(entry.faction)}{entry.faction_inferred ? " · 随榜样" : ""}</small></td>
    <td>{entry.result === "win" ? <span className="ledger-win">胜</span> : entry.result === "loss" ? <span className="ledger-loss">负</span> : <span className="ledger-pending">待结算</span>}</td>
    {singleSeason ? <td>{entry.cumulative_points.toFixed(1)}{entry.pending_count ? <small>另有 {entry.pending_count} 场待结算</small> : null}</td> : null}
  </tr>)}</tbody></table></div>;
}

export function PlayerProfileView({ player, start, end, minimumAppearances, onRangeChange }: { player: PlayerDetail; start: string; end: string; minimumAppearances: number; onRangeChange?: (start: string, end: string, minimumAppearances: number) => void }) {
  const id = player.id;
  const season = player.scope?.season_start ?? start;
  const endSeason = player.scope?.season_end ?? season;
  const singleSeason = season === endSeason;
  const rangeLabel = end === "latest" ? `${season} 至今` : singleSeason ? season : `${season} — ${endSeason}`;
  const stats = player.stats;
  const rankings = stats?.rankings;
  const ledger = [...(stats?.ledger ?? [])].sort((a, b) => b.date.localeCompare(a.date) || (b.game_number ?? -1) - (a.game_number ?? -1) || b.game_id.localeCompare(a.game_id));
  const roles = [...(stats?.roles ?? [])].sort((a, b) => b.appearances - a.appearances || a.role.localeCompare(b.role, "zh-CN"));
  const [divineRoleTab, setDivineRoleTab] = useState<string>();
  const [mechanicalRoleTab, setMechanicalRoleTab] = useState<string>();
  const totalAppearancesByPlayer = new Map((stats?.ranking_boards?.appearances ?? []).map((entry) => [entry.id, entry.appearances] as const));
  const availableSeasons = [...new Set([season, ...(player.available_seasons ?? [])])].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  const baseHref = `/players/${encodeURIComponent(id)}`;
  const appliedMinimum = minimumAppearances;
  const rankContext = { playerId: id, start: season, end: end === "latest" ? "latest" : endSeason, scopeLabel: rangeLabel, minimumAppearances: appliedMinimum, appearances: player.appearances, totalAppearancesByPlayer };
  const hasDivineRole = (tab: typeof divineRoleTabs[number]) => roles.some((role) => tab.roles.includes(role.role) && role.appearances > 0);
  const selectedDivineRole = divineRoleTabs.find((tab) => tab.id === divineRoleTab)
    ?? divineRoleTabs.find(hasDivineRole) ?? divineRoleTabs[0];
  const mechanicalLearnRate = stats?.performance?.mechanical_learn_rate;
  const mechanicalSkillForms = mechanicalForms.filter(({ id, cards }) => cards.length > 0
    && (ledger.some((game) => game.mechanical_learned_role === id)
      || cards.some(({ key }) => stats?.performance?.[key] !== undefined)));
  const selectedMechanicalForm = mechanicalSkillForms.find((form) => form.id === mechanicalRoleTab) ?? mechanicalSkillForms[0];
  return <div className={`page-wrap player-profile ${styles.profile}`}>
    <div className="breadcrumb"><ArchiveLink href={`/players?season=${encodeURIComponent(season)}&phase=all`}>选手索引</ArchiveLink><span>/</span><span>{player.name}</span></div>
    <section className="player-profile-hero">
      <div className="profile-photo-frame">{player.photo ? <StaticPlayerPhoto photo={player.photo} alt={`${player.name} · ${player.photo.season} 官方海报`} /> : <div className="profile-photo-empty"><span>{season} 赛季</span><b>{player.name}</b></div>}</div>
      <div className="profile-hero-copy"><h1>{player.name}</h1><p className="profile-range-label">{rangeLabel}</p></div>
      <div className="profile-hero-controls">
        <SeasonRangeFilter action={publicPagePath(baseHref)} seasons={availableSeasons} start={season} end={end === "latest" ? "latest" : endSeason} minimumAppearances={appliedMinimum} onApply={onRangeChange} />
        {player.appearances < appliedMinimum ? <p className="profile-appearance-status" role="status">当前选手在所选区间出场 {formatNumber(player.appearances)} 场，未达到 {formatNumber(appliedMinimum)} 场门槛，不参与各项排名。</p> : null}
      </div>
    </section>
    {stats ? <>
      <PlayerChapterNav />
      <section className="profile-stat-section" id={profileChapters.overview.id} data-profile-tone="overview" tabIndex={-1}><div className="section-heading"><h2>综合表现</h2></div><div className="profile-stat-grid">
        {singleSeason ? <MetricCard rankContext={rankContext} rankingBoard={stats.ranking_boards?.points} ranking={rankings?.points} provisional={!stats.points_complete} label="赛季积分" value={stats.points_complete ? formatNumber(stats.points) : `小计 ${formatNumber(stats.points)}`} note={!stats.points_complete && stats.pending_games > 0 ? `${formatNumber(stats.pending_games)} 场待结算；当前值不是最终积分` : undefined} /> : null}
        <MetricCard rankContext={rankContext} rankingBoard={stats.ranking_boards?.appearances} ranking={rankings?.appearances} label="出场次数" value={formatNumber(stats.appearances)} />
        <MetricCard rankContext={rankContext} rankingBoard={stats.ranking_boards?.attendance} ranking={rankings?.attendance} label="出场率" value={rateText(stats.attendance.rate)} />
        <MetricCard rankContext={rankContext} rankingBoard={stats.ranking_boards?.total_win_rate} ranking={rankings?.total_win_rate} label="总胜率" value={rateText(stats.total_win_rate.rate)} />
        <MetricCard rankContext={rankContext} rankingBoard={stats.ranking_boards?.wins} ranking={rankings?.wins} rankLabel="胜场" label="总胜场 / 负场" value={`${formatNumber(stats.wins)} / ${formatNumber(stats.losses)}`} note={stats.pending_games > 0 ? `${formatNumber(stats.pending_games)} 场结果待结算` : undefined} />
        <MetricCard rankContext={rankContext} rankingBoard={stats.ranking_boards?.sheriff_registration_rate} ranking={rankings?.sheriff_registration_rate} label="上警率" value={rateText(stats.sheriff_registration_rate.rate)} metric={stats.sheriff_registration_rate} games={ledger} sampleLabels={{ positive: "上警", negative: "未上警", unit: "场", description: "正面样本为首次报名上警的对局，负面样本为未上警的对局。" }} />
      </div></section>
      <section className="profile-stat-section" id={profileChapters.good.id} data-profile-tone="good" tabIndex={-1}><div className="section-heading"><h2>好人表现</h2></div><div className="profile-stat-grid">
        <MetricCard rankContext={rankContext} rankingBoard={stats.ranking_boards?.good_wins} ranking={rankings?.good_wins} label="好人胜场" value={formatNumber(stats.good_win_rate.numerator)} />
        <MetricCard rankContext={rankContext} rankingBoard={stats.ranking_boards?.good_win_rate} ranking={rankings?.good_win_rate} label="好人胜率" value={rateText(stats.good_win_rate.rate)} />
        <MetricCard rankContext={rankContext} rankingBoard={stats.ranking_boards?.wolf_vote_rate} ranking={rankings?.wolf_vote_rate} label="投狼率" value={rateText(stats.wolf_vote_rate.rate)} metric={stats.wolf_vote_rate} games={ledger} sampleLabels={{ positive: "投中狼人", negative: "未投中狼人", unit: "次", description: "按有票权的好人放逐票统计；PK和技能复投逐轮计数。明确弃票计入分母，缺失选票或目标阵营未知时排除。" }} />
        <MetricCard rankContext={rankContext} rankingBoard={stats.ranking_boards?.good_sheriff_registration_rate} ranking={rankings?.good_sheriff_registration_rate} label="好人上警率" value={rateText(stats.good_sheriff_registration_rate.rate)} metric={stats.good_sheriff_registration_rate} games={ledger} sampleLabels={{ positive: "上警", negative: "未上警", unit: "场", description: "仅统计好人阵营的首次报名；名单或阵营未知的场次排除。" }} />
        <MetricCard rankContext={rankContext} rankingBoard={stats.ranking_boards?.seer_follow_rate} ranking={rankings?.seer_follow_rate} label="跟真预言家投票率" value={rateText(stats.seer_follow_rate.rate)} metric={stats.seer_follow_rate} games={ledger} sampleLabels={{ positive: "同投向", negative: "未同投向", unit: "次", description: "按放逐投票轮次比较与真实预言家 / 通灵师的投向。同一局可同时包含同投向和未同投向的轮次。该指标在一定程度上反映站边情况；分票、独立判断等会造成投向不同，不能据此直接判定站边对错。" }} />
        <MetricCard rankContext={rankContext} rankingBoard={stats.ranking_boards?.sheriff_seer_vote_rate} ranking={rankings?.sheriff_seer_vote_rate} label="警徽票投对预言家率" value={rateText(stats.sheriff_seer_vote_rate.rate)} metric={stats.sheriff_seer_vote_rate} games={ledger} sampleLabels={{ positive: "投对", negative: "未投对", unit: "次", description: "按警徽投票轮次统计，正面样本为投给真实预言家 / 通灵师的记录，负面样本为未投对的记录；包含 PK 复投。" }} />
      </div></section>
      <section className="profile-stat-section" id={profileChapters.divine.id} data-profile-tone="divine" tabIndex={-1}><div className="section-heading"><h2>神职表现</h2></div>
        <div className={styles.performanceTabs} role="group" aria-label="神职身份">
          {divineRoleTabs.map((tab) => <button className={styles.performanceTab} key={tab.id} type="button" aria-pressed={selectedDivineRole.id === tab.id} onClick={() => setDivineRoleTab(tab.id)}>{tab.label}</button>)}
        </div>
        <div className={styles.performancePanel}>
          {hasDivineRole(selectedDivineRole) ? <PerformanceMetricGrid cards={selectedDivineRole.cards} metrics={stats.performance} rankings={rankings} rankingBoards={stats.ranking_boards} games={ledger} rankContext={rankContext} /> : <p className="lane-empty">当前范围内没有{selectedDivineRole.label}出场。</p>}
        </div>
      </section>
      <section className="profile-stat-section" id={profileChapters.wolf.id} data-profile-tone="wolf" tabIndex={-1}><div className="section-heading"><h2>狼人表现</h2></div><div className="profile-stat-grid">
        <MetricCard rankContext={rankContext} rankingBoard={stats.ranking_boards?.werewolf_appearances} ranking={rankings?.werewolf_appearances} label="狼人场次" value={formatNumber(stats.werewolf_appearances)} />
        <MetricCard rankContext={rankContext} rankingBoard={stats.ranking_boards?.werewolf_wins} ranking={rankings?.werewolf_wins} label="狼人胜场" value={formatNumber(stats.werewolf_win_rate.numerator)} />
        <MetricCard rankContext={rankContext} rankingBoard={stats.ranking_boards?.werewolf_win_rate} ranking={rankings?.werewolf_win_rate} label="狼人胜率" value={rateText(stats.werewolf_win_rate.rate)} />
        <MetricCard rankContext={rankContext} rankingBoard={stats.ranking_boards?.werewolf_draw_rate} ranking={rankings?.werewolf_draw_rate} label="拿狼率" value={rateText(stats.werewolf_draw_rate.rate)} />
        <MetricCard rankContext={rankContext} rankingBoard={stats.ranking_boards?.werewolf_self_explosion_rate} ranking={rankings?.werewolf_self_explosion_rate} label="自爆率" value={rateText(stats.werewolf_self_explosion_rate.rate)} metric={stats.werewolf_self_explosion_rate} games={ledger} sampleLabels={{ positive: "自爆", negative: "未自爆", unit: "场", description: "仅统计狼人阵营明确的主动自爆，按每局去重；被放逐或技能带走不算自爆。" }} />
        <MetricCard rankContext={rankContext} rankingBoard={stats.ranking_boards?.werewolf_sheriff_registration_rate} ranking={rankings?.werewolf_sheriff_registration_rate} label="狼人上警率" value={rateText(stats.werewolf_sheriff_registration_rate.rate)} metric={stats.werewolf_sheriff_registration_rate} games={ledger} sampleLabels={{ positive: "上警", negative: "未上警", unit: "场", description: "仅统计狼人阵营首次报名，名单或阵营未知的场次排除。" }} />
        <MetricCard rankContext={rankContext} rankingBoard={stats.ranking_boards?.bluff_count} ranking={rankings?.bluff_count} label="悍跳次数" value={stats.bluff_count_complete ? formatNumber(stats.bluff_count) : stats.bluff_count ? `≥${formatNumber(stats.bluff_count)}` : "—"} />
        <MetricCard rankContext={rankContext} rankingBoard={stats.ranking_boards?.bluff_rate} ranking={rankings?.bluff_rate} label="悍跳率" value={rateText(stats.bluff_rate?.rate)} metric={stats.bluff_rate} games={ledger} sampleLabels={{ positive: "悍跳", negative: "未悍跳", unit: "场", description: "悍跳次数除以可判定的狼人阵营场次；悍跳归属或阵营未知的场次排除。" }} />
        <MetricCard rankContext={rankContext} rankingBoard={stats.ranking_boards?.bluff_success_rate} ranking={rankings?.bluff_success_rate} label="悍跳成功率" value={rateText(stats.bluff_success_rate?.rate)} metric={stats.bluff_success_rate} games={ledger} sampleLabels={{ positive: "成功", negative: "失败", unit: "场", description: "按结果已确定的悍跳次数计算；仅获得警徽不计成功，结果待定的记录排除。" }} />
        {bluffStageCards.some((card) => stats.performance?.[card.key] !== undefined) ? <PerformanceMetricGrid cards={bluffStageCards} metrics={stats.performance} rankings={rankings} rankingBoards={stats.ranking_boards} games={ledger} rankContext={rankContext} grid={false} showEmpty={false} /> : null}
      </div>
        {mechanicalLearnRate || stats.performance?.mechanical_wolf_rate ? <div className={styles.performanceSubsection}>
          <h3>机械狼学习技能</h3>
          <div className="profile-stat-grid">
            <PerformanceMetricGrid cards={mechanicalWolfCards} metrics={stats.performance} rankings={rankings} rankingBoards={stats.ranking_boards} games={ledger} rankContext={rankContext} grid={false} showEmpty={false} />
            {mechanicalLearnRate ? <MetricCard label="机械狼学身份率" value={rateText(mechanicalLearnRate.rate)} format="percent" metric={mechanicalLearnRate}
              games={ledger.map((game) => game.mechanical_learned_role ? { ...game, role_label: game.mechanical_learned_role } : game)}
              rankContext={rankContext} ranking={rankings?.mechanical_learn_rate} rankingBoard={stats.ranking_boards?.mechanical_learn_rate}
              sampleLabels={{ positive: "学到非平民身份", negative: "学到平民或未学习", unit: "场", description: "学身份率为学到非平民身份的场次占可判定机械狼场次的比例。学到平民或明确未学习的场次计入分母，学习情况或所学形态待核的场次排除。" }}
              breakdown={<MechanicalLearningDistribution games={ledger} />} /> : null}
          </div>
        </div> : null}
        {roles.some((role) => role.role === "机械狼" && role.appearances > 0) ? <div className={styles.performanceSubsection}>
          <h3>机械狼技能使用</h3>
          {selectedMechanicalForm ? <>
            <div className={styles.performanceTabs} role="group" aria-label="机械狼学习形态">
              {mechanicalSkillForms.map((form) => <button className={styles.performanceTab} key={form.id} type="button" aria-pressed={selectedMechanicalForm.id === form.id} onClick={() => setMechanicalRoleTab(form.id)}>{form.label}</button>)}
            </div>
            <div className={styles.performancePanel}>
              <PerformanceMetricGrid cards={selectedMechanicalForm.cards} metrics={stats.performance} rankings={rankings} rankingBoards={stats.ranking_boards} games={ledger} rankContext={rankContext} />
            </div>
          </> : <p className="lane-empty">当前范围内暂无可统计的机械狼技能。</p>}
        </div> : null}
      </section>
      <section className="profile-stat-section" id={profileChapters.lifecycle.id} data-profile-tone="lifecycle" tabIndex={-1}><div className="section-heading"><h2>受袭与出局</h2></div>
        <PerformanceMetricGrid cards={lifecycleCards} metrics={stats.performance} rankings={rankings} rankingBoards={stats.ranking_boards} games={ledger} rankContext={rankContext} />
      </section>
      <section className="profile-stat-section" id={profileChapters.roles.id} data-profile-tone="roles" tabIndex={-1}>
        <div className="section-heading"><h2>身份胜率分布</h2></div>
        <RoleWinRates roles={roles} ledger={ledger} rankContext={rankContext} />
      </section>
      <section className="profile-stat-section" id={profileChapters.boards.id} data-profile-tone="boards" tabIndex={-1}>
        <div className="section-heading"><h2>版型胜率分布</h2></div>
        <BoardWinRates boards={stats.boards ?? []} ledger={ledger} rankContext={rankContext} />
      </section>
      <section className="profile-games" id={profileChapters.games.id} data-profile-tone="games" tabIndex={-1}><div className="section-heading"><div><h2>对局记录</h2></div><span className="section-index">{ledger.length} 场</span></div><LedgerTable ledger={ledger} singleSeason={singleSeason} /></section>
    </> : <section className="profile-stat-grid profile-stat-fallback"><article><span>出场</span><strong>{formatNumber(player.appearances)}</strong><small>统计摘要暂未提供</small></article><article><span>身份种类</span><strong>{formatNumber(player.roles.length)}</strong><small>原始档案数量</small></article></section>}
    <details className="release-details"><summary>查看此页的数据版本</summary><div className="release-detail-content"><span>发布版本 <code>{player.release_id}</code></span><span>范围 <b>{rangeLabel}</b></span></div></details>
  </div>;
}
