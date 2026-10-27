import type { Ballot, Seat, Vote, VotingData } from "@/lib/types";
import { voteStatusLabel } from "@/lib/format";

const ballotKind: Record<string, string> = { sheriff: "警长投票", exile: "放逐投票", tie_break: "补投" };
const ballotStage: Record<string, string> = {
  initial: "首轮", pk: "平票 PK 后复投", revote: "技能重投", skill_revote: "技能重投",
};
function seatName(number: number, seats: Seat[]) {
  const seat = seats.find((item) => item.seat === number);
  return `${number}号${seat?.name ? ` ${seat.name}` : ""}`;
}
function seatsText(numbers: number[] | null | undefined) {
  if (numbers == null) return "名单待核";
  return numbers.length ? numbers.map((number) => `${number}号`).join("、") : "无人";
}
function groupVotes(votes: Vote[]) {
  const groups = new Map<string, { label: string; votes: Vote[]; isDefault: boolean }>();
  for (const vote of votes) {
    const isDefault = vote.basis === "rule_default";
    const key = isDefault ? "default" : vote.state === "abstained" ? "abstained" : vote.state === "not_voting" ? "not_voting" : vote.state === "cast" && vote.target != null ? `target-${vote.target}` : "unknown";
    const label = isDefault ? "默认弃票" : vote.state === "abstained" ? "弃票" : vote.state === "not_voting" ? "未参与" : vote.state === "cast" && vote.target != null ? `投给 ${vote.target} 号` : "投向待核";
    if (!groups.has(key)) groups.set(key, { label, votes: [], isDefault });
    groups.get(key)!.votes.push(vote);
  }
  return [...groups.entries()];
}
function BallotCard({ ballot, seats, resultConflict }: { ballot: Ballot; seats: Seat[]; resultConflict: boolean }) {
  return <article className="ballot-card" data-ballot-id={ballot.id}>
    <header><div><span className="ballot-stage">{ballotStage[ballot.stage] ?? "其他投票轮次"}{ballot.number > 1 ? ` · 第 ${ballot.number} 轮` : ""}</span><h4>{ballotKind[ballot.kind] ?? "投票记录"}</h4></div><span className="ballot-record-status">{voteStatusLabel(ballot.status)}</span></header>
    <div className="ballot-meta">
      {ballot.candidates != null ? <span>候选：{seatsText(ballot.candidates)}</span> : null}
      {resultConflict ? <strong>本轮结果与放逐事件记录冲突，待核实</strong>
        : ballot.winner != null ? <strong>本轮结果：{seatName(ballot.winner, seats)}</strong>
          : ballot.tied_candidates?.length ? <strong>平票：{seatsText(ballot.tied_candidates)}</strong> : null}
      {ballot.eligible_voters != null ? <span>本轮有票权：{seatsText(ballot.eligible_voters)}</span> : null}
    </div>
    {ballot.votes?.length ? <ul className="vote-groups">{groupVotes(ballot.votes).map(([key, group]) => <li key={key} data-vote-state={key}>
      <div className="vote-group-title"><strong>{group.label}</strong><span>{group.votes.length} 人</span></div>
      <div className="vote-group-voters">{group.votes.map((vote) => <span key={vote.voter} title={seatName(vote.voter, seats)}>{vote.voter}号{group.isDefault ? <small>规则默认</small> : null}</span>)}</div>
    </li>)}</ul> : <p className="ballot-gap">本轮逐票记录待补。</p>}
    {ballot.unrecorded_voters?.length ? <p className="ballot-gap">尚缺记录：{seatsText(ballot.unrecorded_voters)}</p> : null}
  </article>;
}
function missingRoundMessage(data: VotingData, day: number, kind: "sheriff" | "exile") {
  const status = data.days?.find((item) => item.day === day)?.[kind];
  if (!status || ["unknown", "not_applicable", "not_held"].includes(status)) return null;
  if (status === "recorded") return `${kind === "sheriff" ? "警长" : "放逐"}结果已记录，逐票明细待补。`;
  if (status === "interrupted_self_destruct") return `${kind === "sheriff" ? "警长竞选" : "放逐投票"}因狼人自爆中断。`;
  if (status === "deferred" || status === "delayed") return "警长竞选延期到下一天继续。";
  if (status === "badge_lost") return "警徽流失，本局不再进行警长投票。";
  return voteStatusLabel(status);
}
export function BallotPanel({ voting, seats = [], resultConflictIds = [] }: {
  voting: VotingData; seats?: Seat[]; resultConflictIds?: string[];
}) {
  const registrations = (voting.registrations ?? []).filter((row) => row.on_police != null || row.off_police != null);
  const ballots = voting.ballots ?? [];
  const statuses = (voting.days ?? []).flatMap((day) => (["sheriff", "exile"] as const).flatMap((kind) => {
    if (ballots.some((ballot) => ballot.day === day.day && ballot.kind === kind)) return [];
    const message = missingRoundMessage(voting, day.day, kind);
    return message ? [{ key: `${day.day}-${kind}`, message }] : [];
  }));
  if (!registrations.length && !ballots.length && !statuses.length) return null;
  return <div className="day-ballots">
    {registrations.map((registration) => <article className="registration-card" key={registration.id}>
      <h4>警长竞选报名</h4>
      {registration.on_police != null ? <p><span>上警</span>{seatsText(registration.on_police)}</p> : null}
      {registration.off_police != null ? <p><span>警下</span>{seatsText(registration.off_police)}</p> : null}
    </article>)}
    {ballots.map((ballot) => <BallotCard key={ballot.id} ballot={ballot} seats={seats}
      resultConflict={resultConflictIds.includes(ballot.id)} />)}
    {statuses.map((status) => <p className="ballot-day-status" key={status.key}>{status.message}</p>)}
  </div>;
}
