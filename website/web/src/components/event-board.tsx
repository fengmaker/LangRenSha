import { Fragment } from "react";
import type { GameEvent, GameRound, Seat, VotingData } from "@/lib/types";
import { actionLabel, availabilityLabel } from "@/lib/format";
import { BallotPanel } from "@/components/ballot-panel";

function slotLabel(event: GameEvent): string {
  if (event.slot_label) return event.slot_label;
  const labels: Record<string, string> = {
    mixed_blood_model: "混血儿榜样", wolf_attack: "狼队行动", witch_save: "女巫解药", witch_poison: "女巫毒药",
    seer_check: "预言家查验", hunter_state: "猎人状态", mixed_blood_alignment: "混血儿阵营",
    sheriff_candidates: "竞选报名", sheriff_vote: "警长投票", sheriff_result: "警长结果", night_deaths: "天亮情况",
    hunter_shot: "猎人开枪", badge: "警徽处理", speech_order: "发言顺序", exile_vote: "放逐投票",
    exile_result: "放逐结果", self_destruct: "狼人自爆", white_god_reveal: "白神翻牌", mixed_blood_victory: "混血儿胜利条件",
  };
  return event.slot ? labels[event.slot] ?? (/[\u4e00-\u9fff]/.test(event.slot) ? event.slot : "其他事件") : "对局事件";
}
function resultLabel(value: string): string {
  const labels: Record<string, string> = { good: "好人", werewolf: "狼人", wolf: "狼人", unknown: "待核", none: "无", peaceful: "平安夜", success: "成功", failed: "失败" };
  return labels[value] ?? (/[\u4e00-\u9fff]/.test(value) ? value : "结果已记录");
}
function seatText(number: number, seats: Seat[]): string {
  const seat = seats.find((item) => item.seat === number);
  return `${number}号${seat?.name ?? ""}${seat?.role ? `（${seat.role}）` : ""}`;
}
function narrative(event: GameEvent, seats: Seat[]): string {
  const actor = event.actor != null ? seatText(event.actor, seats) : "";
  const targets = (event.targets ?? []).map((number) => seatText(number, seats)).join("、");
  const resolved = (event.resolved_targets ?? []).map((number) => seatText(number, seats)).join("、");
  if (event.action === "unknown" || !event.action) return `${slotLabel(event)}的具体情况仍待核实。`;
  if (event.slot === "mixed_blood_model" && event.action === "choose") return `${actor || "混血儿"}选择${targets || "榜样待核"}作为榜样。`;
  if (event.slot === "mixed_blood_alignment" && ["wolf", "werewolf", "good"].includes(event.action)) return `${actor || "混血儿"}本局跟随${event.action === "good" ? "好人" : "狼人"}阵营。`;
  if (event.slot === "wolf_attack" && event.action === "attack") return `狼队选择击杀${targets || "目标待核"}${resolved ? `，交换后实际刀口为${resolved}` : ""}。`;
  if (event.slot === "witch_save" && event.action === "save") return `${actor || "女巫"}使用解药，救起${targets || "目标待核"}。`;
  if (event.action === "poison") return `${actor || "行动者"}${resolved ? "原选择对" : "对"}${targets || "目标待核"}使用毒药${resolved ? `，交换后实际毒药目标为${resolved}` : ""}。`;
  if (event.action === "check") return `${actor || "查验者"}${resolved ? "原选择查验" : "查验"}${targets || "目标待核"}${resolved ? `，交换后实际查验${resolved}` : ""}${event.result ? `，结果为${resultLabel(event.result)}` : "，查验反馈待核"}。`;
  if (event.action === "guard") return `${actor || "守护者"}守护${targets || "目标待核"}。`;
  if (event.action === "learn") return `${actor || "机械狼"}选择学习${targets || "学习目标待核"}。`;
  if (event.action === "choose" || event.action === "select") return `${actor || slotLabel(event)}选择${targets || (event.result ? resultLabel(event.result) : "对象待核")}。`;
  if (event.action === "exchange") return `${actor || "行动者"}交换${targets || "对象待核"}。`;
  if (event.action === "dream") return `${actor || "摄梦人"}梦游${targets || "目标待核"}。`;
  if (event.action === "carrying") return `${actor || "机械狼"}已接过狼刀。`;
  if (event.action === "not_carrying") return `${actor || "机械狼"}尚未接过狼刀。`;
  if (event.slot === "hunter_state" && event.action === "can_shoot") return `${actor || "猎人"}本夜可开枪。`;
  if (event.slot === "hunter_state" && event.action === "cannot_shoot") return `${actor || "猎人"}本夜不能开枪。`;
  if (event.slot === "night_deaths") return ["peaceful", "no_death"].includes(event.action) ? "天亮，昨夜平安夜。" : targets ? `天亮，昨夜出局：${targets}。` : "夜间出局情况待核。";
  if (event.slot === "sheriff_result" && event.action === "elected") return `${targets || actor || "当选者待核"}当选警长。`;
  if (event.slot === "badge" && event.action === "badge_lost") return "延期警长竞选再次被狼人自爆中断，警徽流失，本局不再进行警长竞选。";
  if (event.slot === "exile_result" && event.action === "exile") return `${targets || "放逐对象待核"}被放逐出局。`;
  if (event.action === "self_destruct") return `${actor || targets || "狼人"}自爆。`;
  if (event.action === "shoot") return `${actor || "开枪者"}开枪带走${targets || "目标待核"}。`;
  if (event.action === "transfer") return `警徽${actor ? `由${actor}` : ""}移交给${targets || "接徽者待核"}。`;
  if (["reveal", "flip"].includes(event.action) && event.slot === "white_god_reveal") return `${actor || targets || "白神"}翻牌公开身份。`;
  if (event.slot === "witch_poison" && event.action === "pass") return `${actor || "女巫"}压毒，本夜未使用毒药。`;
  if (event.action === "pass") return `${actor || slotLabel(event)}本轮未发动。`;
  if (event.action === "none" && event.slot === "exile_result") return event.result === "double_tie" ? "首轮与 PK 轮均平票，本日无人被放逐。" : "本日无人被放逐。";
  const description = event.description?.replace(/^第\s*\d+\s*(?:夜|天白天)[，,\s]*/, "");
  if (description) return description;
  return [actor, actionLabel(event.action), targets ? `目标：${targets}` : ""].filter(Boolean).join("，") + "。";
}
function effectText(effect: NonNullable<GameEvent["effects"]>[number], seats: Seat[]): string {
  const parts = [effect.kind === "poison_reflected" ? "毒药反弹" : "技能结算"];
  if (effect.intended_target != null) parts.push(`原目标：${seatText(effect.intended_target, seats)}`);
  if (effect.dead_seat != null) parts.push(`实际出局：${seatText(effect.dead_seat, seats)}`);
  if (effect.shield_actor != null) parts.push(`护盾来自${seatText(effect.shield_actor, seats)}`);
  return parts.join("；");
}
function EventList({ events, seats }: { events: GameEvent[]; seats: Seat[] }) {
  return <div className="game-event-list">{events.map((event, index) => <article className="game-event" key={`${event.slot ?? "event"}-${index}`} data-slot={event.slot} data-action={event.action}>
    <div className="game-event-label"><span>{slotLabel(event)}</span>{event.inferred ? <small className="game-inference-tag">规则推断</small> : null}</div>
    <div className="game-event-content"><p>{narrative(event, seats)}</p>
      {event.result && event.result !== "double_tie" && event.action !== "check" ? <small className="game-event-result">{resultLabel(event.result)}</small> : null}
      {event.effects?.length ? <small className="game-event-effects">{event.effects.map((effect) => effectText(effect, seats)).join("；")}</small> : null}
      {event.inference_note && !event.resolved_targets?.length && event.action !== "badge_lost" && !(event.slot === "hunter_state" && ["can_shoot", "cannot_shoot"].includes(event.action ?? "")) && event.result !== "double_tie" ? <small>{event.inference_note}</small> : null}
      {event.availability && !event.inferred ? <small>{availabilityLabel(event.availability)}</small> : null}
    </div>
  </article>)}</div>;
}
function votingForDay(voting: VotingData, day: number): VotingData {
  return {
    registrations: voting.registrations?.filter((row) => row.day === day), ballots: voting.ballots?.filter((row) => row.day === day),
    days: voting.days?.filter((row) => row.day === day), interruptions: voting.interruptions?.filter((row) => row.day === day),
  };
}
function hasVoting(voting: VotingData) {
  return Boolean(voting.ballots?.length || voting.registrations?.some((row) => row.on_police != null || row.off_police != null)
    || voting.days?.some((row) => [row.sheriff, row.exile].some((status) => status && !["unknown", "not_applicable", "not_held"].includes(status))));
}
function DayRecap({ events, voting, seats }: { events: GameEvent[]; voting: VotingData; seats: Seat[] }) {
  const sheriffVoting: VotingData = {
    registrations: voting.registrations,
    ballots: voting.ballots?.filter((ballot) => ballot.kind === "sheriff"),
    days: voting.days?.map((day) => ({ day: day.day, sheriff: events.some((event) => event.slot === "badge" && event.action === "badge_lost") ? undefined : day.sheriff })),
  };
  const exileVoting: VotingData = {
    ballots: voting.ballots?.filter((ballot) => ballot.kind === "exile"),
    days: voting.days?.map((day) => ({ day: day.day, exile: day.exile })),
  };
  const resultAt = events.findIndex((event) => event.slot === "exile_vote" || event.slot === "exile_result");
  const splitAt = resultAt < 0 ? events.length : resultAt;
  return <>
    <BallotPanel voting={sheriffVoting} seats={seats} />
    {splitAt ? <EventList events={events.slice(0, splitAt)} seats={seats} /> : null}
    <BallotPanel voting={exileVoting} seats={seats} />
    {splitAt < events.length ? <EventList events={events.slice(splitAt)} seats={seats} /> : null}
    <BallotPanel voting={{ ballots: voting.ballots?.filter((ballot) => !["sheriff", "exile"].includes(ballot.kind)) }} seats={seats} />
  </>;
}
export function EventBoard({ rounds, voting = {}, seats = [] }: { rounds: GameRound[]; voting?: VotingData; seats?: Seat[] }) {
  const numbers = [...new Set([...rounds.map((round) => round.number), ...(voting.days ?? []).map((row) => row.day), ...(voting.ballots ?? []).map((row) => row.day), ...(voting.registrations ?? []).map((row) => row.day)])].sort((a, b) => a - b);
  if (!numbers.length) return <p className="timeline-empty">当前还没有可整理的日夜行动记录。</p>;
  return <div className="game-timeline">{numbers.map((number) => {
    const round = rounds.find((item) => item.number === number);
    const night = round?.night ?? [], day = round?.day ?? [];
    const dayVoting = votingForDay(voting, number);
    return <Fragment key={number}>
      {night.length ? <section className="timeline-phase timeline-night" data-phase="night" data-day={number}>
        <header className="timeline-phase-header"><span className="timeline-phase-symbol" aria-hidden="true">☾</span><div><p>夜间行动</p><h3>第 {number} 夜{number === 1 ? " · 首夜" : ""}</h3></div></header>
        <EventList events={night} seats={seats} />
      </section> : null}
      {day.length || hasVoting(dayVoting) ? <section className="timeline-phase timeline-day" data-phase="day" data-day={number}>
        <header className="timeline-phase-header"><span className="timeline-phase-symbol" aria-hidden="true">☼</span><div><p>白天复盘</p><h3>第 {number} 天</h3></div></header>
        <DayRecap events={day} voting={dayVoting} seats={seats} />
      </section> : null}
    </Fragment>;
  })}</div>;
}
