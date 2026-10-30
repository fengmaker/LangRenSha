import { Fragment } from "react";
import type { GameEvent, GameRound, Seat, VotingData } from "@/lib/types";
import { actionLabel, availabilityLabel, gamePhaseLabel, gameTimeText } from "@/lib/format";
import { BallotPanel } from "@/components/ballot-panel";

function slotLabel(event: GameEvent): string {
  if (event.terminal && event.slot === "exile_result") return "终局说明";
  if (event.slot === "game_end" || event.slot === "werewolf_surrender") return "交牌与终局";
  if (event.slot === "trade_decisions") return "交易双方选择";
  if (event.slot_label && /[\u4e00-\u9fff]/.test(event.slot_label)) return event.slot_label;
  const labels: Record<string, string> = {
    mixed_blood_model: "混血儿榜样", guard: "守卫守护", wolf_attack: "狼队行动", witch_save: "女巫解药", witch_poison: "女巫毒药",
    seer_check: "预言家查验", hunter_state: "猎人状态", mixed_blood_alignment: "混血儿阵营",
    sheriff_candidates: "竞选报名", sheriff_vote: "警长投票", sheriff_result: "警长结果", night_deaths: "天亮情况",
    hunter_shot: "猎人开枪", badge: "警徽处理", speech_order: "发言顺序", exile_vote: "放逐投票",
    disqualification: "DQ出局",
    exile_result: "放逐结果", self_destruct: "狼人自爆", white_god_reveal: "白神翻牌", mixed_blood_victory: "混血儿胜利条件",
    dancer_dance: "舞者共舞", dance_resolution: "共舞结算", magician_exchange: "魔术师交换",
    magic_duel_magician_swap: "魔术师交换", magic_duel_wolf_sorcerer_swap: "狼术师交换", sorcerer_exchange: "狼术师交换",
    nine_tail_mark: "九尾狐标记", nine_tail_hunt: "九尾狐猎杀时刻", nine_tail_kill: "九尾狐猎杀结果",
    nine_tail_skill: "九尾狐技能结算", nine_tail_vote_mark: "九尾狐投票标记", whiteze_clear: "白泽技能结算",
    whiteze_clear_mark: "白泽清除标记",
  };
  return event.slot ? labels[event.slot] ?? (/[\u4e00-\u9fff]/.test(event.slot) ? event.slot : "其他事件") : "对局事件";
}
function eventDescription(value: string): string {
  return gameTimeText(value).replace(/^(?:首夜|第\s*(?:\d+|[零〇一二三四五六七八九十百千万两]+)\s*(?:夜|天(?:白天|夜晚)?)|[零〇一二三四五六七八九十百千万两]+\s*(?:夜|天(?:白天|夜晚)?))[，,、：:\s]*/, "");
}
function resultLabel(value: string): string {
  const labels: Record<string, string> = {
    good: "好人", werewolf: "狼人", wolf: "狼人", unknown: "待核", none: "无", peaceful: "平安夜",
    success: "成功", failed: "失败", guarded: "目标被守护", saved: "目标被救起", immune: "目标免疫毒药",
    protected_by_dance: "目标受到共舞保护", protected_by_dance_pool: "目标受到共舞保护",
    badge_lost: "警徽流失", badge_destroyed: "警徽撕毁",
    cleared: "标记已清除", successful: "成功", minority_dies: "少数阵营出局",
    disqualified_repeat_target: "重复选择目标，交换无效",
  };
  return labels[value] ?? (/[\u4e00-\u9fff]/.test(value) ? value : "结果已记录");
}
function displayResult(event: GameEvent): string | null {
  return event.display_result === undefined ? event.result ?? null : event.display_result;
}
function isFailedResult(event: GameEvent): boolean {
  const result = displayResult(event);
  return result != null && /failed|fail|失败|未生效|未成功/i.test(result);
}
function seatText(number: number, seats: Seat[]): string {
  const seat = seats.find((item) => item.seat === number);
  return `${number}号${seat?.name ?? ""}${seat?.role ? `（${seat.role}）` : ""}`;
}
function narrative(event: GameEvent, seats: Seat[]): string {
  const result = displayResult(event);
  if (event.terminal && event.slot === "exile_result" && result) return resultLabel(result);
  const actor = event.actor != null ? seatText(event.actor, seats) : "";
  const targets = (event.targets ?? []).map((number) => seatText(number, seats)).join("、");
  const resolved = (event.resolved_targets ?? []).map((number) => seatText(number, seats)).join("、");
  if (event.blocked_by_game_end) return `对局已结束，${actor || slotLabel(event)}未进入发动阶段。`;
  if (event.invalidated) return `${actor || slotLabel(event)}的本次行动判定失效。`;
  if (event.action === "unavailable") return `${actor || slotLabel(event)}本轮无法发动。`;
  if (event.action === "forbidden") return `${slotLabel(event)}本轮受规则限制，未发动。`;
  if (event.action === "unknown" || !event.action) return `${slotLabel(event)}的具体情况仍待核实。`;
  if (event.slot === "mixed_blood_model" && event.action === "choose") return `${actor || "混血儿"}选择${targets || "榜样待核"}作为榜样。`;
  if (event.slot === "mixed_blood_alignment" && ["wolf", "werewolf", "good"].includes(event.action)) return `${actor || "混血儿"}本局跟随${event.action === "good" ? "好人" : "狼人"}阵营。`;
  if (event.slot === "wolf_attack" && event.action === "attack") return `狼队选择击杀${targets || "目标待核"}${resolved ? `，交换后实际刀口为${resolved}` : ""}。`;
  if (event.slot === "nine_tail_kill" && event.action === "kill") return `${actor || "九尾狐"}选择击杀${targets || "目标待核"}。`;
  if (event.slot === "witch_save" && event.action === "save") return isFailedResult(event)
    ? `${actor || "女巫"}尝试使用解药救起${targets || "目标待核"}，但未生效。`
    : `${actor || "女巫"}使用解药，救起${targets || "目标待核"}。`;
  if (event.action === "poison") return isFailedResult(event)
    ? `${actor || "行动者"}尝试对${targets || "目标待核"}使用毒药${resolved ? `，交换后实际目标为${resolved}` : ""}，但未生效。`
    : `${actor || "行动者"}${resolved ? "原选择对" : "对"}${targets || "目标待核"}使用毒药${resolved ? `，交换后实际毒药目标为${resolved}` : ""}。`;
  if (event.action === "check") return `${actor || "查验者"}${resolved ? "原选择查验" : "查验"}${targets || "目标待核"}${resolved ? `，交换后实际查验${resolved}` : ""}${result ? `，结果为${resultLabel(result)}` : "，查验反馈待核"}。`;
  if (event.action === "guard") return `${actor || "守护者"}守护${targets || "目标待核"}。`;
  if (event.action === "learn") return `${actor || "机械狼"}选择学习${targets || "学习目标待核"}${result ? `，学习后成为${resultLabel(result)}` : ""}。`;
  if (event.action === "choose" || event.action === "select") return `${actor || slotLabel(event)}选择${targets || (result ? resultLabel(result) : "对象待核")}。`;
  if (event.action === "exchange") return `${actor || "行动者"}交换${targets || "对象待核"}。`;
  if (event.slot === "trade_decisions") {
    const choices: Record<string, string> = {
      trade: "双方均选择交易", betray: "双方均选择背叛",
      trade_betray: "前一位选择交易，后一位选择背叛", betray_trade: "前一位选择背叛，后一位选择交易",
    };
    if (event.action && choices[event.action]) return `${targets ? `按${targets}的顺序，` : ""}${choices[event.action]}。`;
  }
  if (event.action === "dream") return `${actor || "摄梦人"}梦游${targets || "目标待核"}。`;
  if (event.slot === "dancer_dance" && event.action === "dance") return `${actor || "舞者"}选择${targets || "对象待核"}共舞。`;
  if (event.slot === "masquerade_verify" && event.action === "verify") return `${actor || "假面"}验证${targets || "对象待核"}是否在舞池${result ? `，结果为${resultLabel(result)}` : ""}。`;
  if (event.slot === "masquerade_mask" && event.action === "give_mask") return `${actor || "假面"}赐予${targets || "对象待核"}面具。`;
  if (event.slot === "puppet_skill_effect") {
    if (event.action === "reverse_check") return `${targets || "傀儡预言家"}的查验反馈按傀儡规则反转。`;
    if (event.action === "skill_disabled") return `${targets || "傀儡"}因傀儡效果无法使用原技能。`;
    if (event.action === "no_effect") return `${targets || "傀儡"}的身份不产生额外傀儡技能效果。`;
  }
  if (event.action === "carrying") return `${actor || "机械狼"}已接过狼刀。`;
  if (event.action === "not_carrying") return `${actor || "机械狼"}尚未接过狼刀。`;
  if (event.slot === "wolf_king_state" && event.action === "can_shoot") return `${actor || slotLabel(event)}本次出局可以开枪。`;
  if (event.slot === "wolf_king_state" && event.action === "cannot_shoot") return `${actor || slotLabel(event)}本次出局不能开枪。`;
  if (event.slot === "hunter_state" && event.action === "can_shoot") return `${actor || slotLabel(event)}本夜可开枪。`;
  if (event.slot === "hunter_state" && event.action === "cannot_shoot") return `${actor || slotLabel(event)}本夜不能开枪。`;
  if (event.slot === "night_deaths") {
    if (event.terminal) return ["peaceful", "no_death"].includes(event.action)
      ? "本夜终局结算：平安夜。" : targets ? `本夜终局出局：${targets}。` : "本夜终局结算待核。";
    return ["peaceful", "no_death"].includes(event.action) ? "天亮，昨夜平安夜。" : targets ? `天亮，昨夜出局：${targets}。` : "夜间出局情况待核。";
  }
  if (event.slot === "sheriff_result" && event.action === "elected") return `${targets || actor || "当选者待核"}当选警长。`;
  if (event.slot === "sheriff_result" && event.action === "deferred") return "警长竞选延期至次日继续。";
  if (event.slot === "badge" && event.action === "badge_lost") return "警徽流失，本局不再进行警长竞选。";
  if (event.slot === "disqualification" && event.action === "disqualify") return (event.description ? eventDescription(event.description) : "") || `${targets || actor || "玩家"}被DQ出局；与普通死亡结算分开记录。`;
  if (event.slot === "exile_result" && event.action === "exile") return `${targets || "放逐对象待核"}被放逐出局。`;
  if (event.action === "self_destruct") return `${actor || targets || "狼人"}自爆。`;
  if (event.action === "surrender") return `${actor || "狼人"}选择交牌，对局结束。`;
  if (event.action === "shoot") return `${actor || "开枪者"}开枪带走${targets || "目标待核"}。`;
  if (event.action === "transfer") return `警徽${actor ? `由${actor}` : ""}移交给${targets || "接徽者待核"}。`;
  if (["reveal", "flip"].includes(event.action) && event.slot === "white_god_reveal") return `${actor || targets || "白神"}翻牌公开身份。`;
  if (event.slot === "witch_save" && event.action === "pass") return `${actor || "女巫"}本夜未使用解药。`;
  if (event.slot === "witch_poison" && event.action === "pass") return `${actor || "女巫"}本夜未使用毒药。`;
  if (event.action === "pass") return `${actor || slotLabel(event)}本轮未发动。`;
  if (event.action === "none" && event.slot === "exile_result") return result === "double_tie" ? "首轮与 PK 轮均平票，本日无人被放逐。" : "本日无人被放逐。";
  const description = event.description ? eventDescription(event.description)
    .replace(/^[a-z][a-z _-]*[：:]\s*/i, `${slotLabel(event)}：`) : undefined;
  if (description && !/记录动作\s+[a-z_]+|记录槽|记录未知/i.test(description)) return description;
  return [actor, actionLabel(event.action), targets ? `目标：${targets}` : ""].filter(Boolean).join("，") + "。";
}
type EventCard = { events: GameEvent[]; witchMedicine: boolean; key: string };
function eventCards(events: GameEvent[], seats: Seat[], isNight: boolean): EventCard[] {
  if (!isNight) return events.map((event, index) => ({ events: [event], witchMedicine: false, key: `${event.slot ?? "event"}-${index}` }));
  const witches = seats.filter((seat) => seat.role === "女巫");
  const actorFor = (event: GameEvent): number | null => {
    if (event.slot !== "witch_save" && event.slot !== "witch_poison") return null;
    if (event.actor != null) return seats.some((seat) => seat.seat === event.actor && seat.role === "女巫") ? event.actor : null;
    return witches.length === 1 ? witches[0].seat : null;
  };
  const grouped = new Map<number, number[]>();
  events.forEach((event, index) => {
    const actor = actorFor(event);
    if (actor == null) return;
    grouped.set(actor, [...(grouped.get(actor) ?? []), index]);
  });
  const indexToActor = new Map<number, number>();
  for (const [actor, indices] of grouped) for (const index of indices) indexToActor.set(index, actor);
  const emitted = new Set<number>();
  const cards: EventCard[] = [];
  events.forEach((event, index) => {
    const actor = indexToActor.get(index);
    if (actor == null) {
      cards.push({ events: [event], witchMedicine: false, key: `${event.slot ?? "event"}-${index}` });
      return;
    }
    if (emitted.has(actor)) return;
    emitted.add(actor);
    const indices = grouped.get(actor) ?? [];
    cards.push({ events: indices.map((item) => events[item]), witchMedicine: true, key: `witch-medicine-${actor}-${index}` });
  });
  return cards;
}
function witchMedicineNarratives(events: GameEvent[], seats: Seat[]): string[] {
  const save = events.filter((event) => event.slot === "witch_save");
  const poison = events.filter((event) => event.slot === "witch_poison");
  const all = [...save, ...poison];
  if (save.length && poison.length && all.every((event) => event.action === "pass")) return ["女巫本夜未使用解药或毒药。"];
  if (save.length && poison.length && all.every((event) => event.action === "unknown" || !event.action)) return ["女巫本夜用药情况待核。"];
  if (save.length === 1 && poison.length === 1
    && [save[0].action, poison[0].action].includes("pass")
    && [save[0].action, poison[0].action].includes("unknown")) {
    const unused = save[0].action === "pass" ? "解药" : "毒药";
    const pending = save[0].action === "unknown" ? "解药" : "毒药";
    return [`女巫本夜未使用${unused}；${pending}使用情况待核。`];
  }
  return events.map((event) => narrative(event, seats));
}
function narrativeShowsResult(event: GameEvent): boolean {
  const result = displayResult(event);
  if (!result) return false;
  return Boolean((event.action === "check" || event.action === "learn")
    || (event.slot === "witch_save" && event.action === "save" && (["saved", "success"].includes(result) || isFailedResult(event)))
    || ((event.action === "choose" || event.action === "select") && !event.targets?.length)
    || (event.action === "poison" && isFailedResult(event))
    || event.action === "surrender"
    || (event.terminal && event.slot === "exile_result"));
}
function effectText(effect: NonNullable<GameEvent["effects"]>[number], seats: Seat[]): string {
  const parts = [effect.kind === "poison_reflected" ? "毒药反弹" : "技能结算"];
  if (effect.intended_target != null) parts.push(`原目标：${seatText(effect.intended_target, seats)}`);
  if (effect.dead_seat != null) parts.push(`实际出局：${seatText(effect.dead_seat, seats)}`);
  if (effect.shield_actor != null) parts.push(`护盾来自${seatText(effect.shield_actor, seats)}`);
  return parts.join("；");
}
function EventList({ events, seats, isNight = false }: { events: GameEvent[]; seats: Seat[]; isNight?: boolean }) {
  return <div className="game-event-list">{eventCards(events, seats, isNight).map((card) => {
    const event = card.events[0];
    const narratives = card.witchMedicine ? witchMedicineNarratives(card.events, seats) : [narrative(event, seats)];
    return <article className="game-event" key={card.key}
      data-slot={card.witchMedicine ? "witch_medicine" : event.slot}
      data-action={card.witchMedicine ? "combined" : event.action}>
      <div className="game-event-label"><span>{card.witchMedicine ? "女巫用药" : slotLabel(event)}</span>
        {card.events.some((item) => item.inferred) ? <small className="game-inference-tag">规则推断</small> : null}</div>
      <div className="game-event-content">
        {narratives.map((text, index) => <p key={`${card.key}-narrative-${index}`}>{text}</p>)}
        {card.events.map((item, index) => {
          const result = displayResult(item);
          return <Fragment key={`${card.key}-detail-${index}`}>
            {result && result !== "double_tie" && !narrativeShowsResult(item) ? <small className="game-event-result">{resultLabel(result)}</small> : null}
            {item.effects?.length ? <small className="game-event-effects">{item.effects.map((effect) => effectText(effect, seats)).join("；")}</small> : null}
            {item.inference_note && !item.resolved_targets?.length && item.action !== "badge_lost" && !(item.slot === "hunter_state" && ["can_shoot", "cannot_shoot"].includes(item.action ?? "")) && result !== "double_tie" ? <small>{gameTimeText(item.inference_note)}</small> : null}
            {item.availability && !item.inferred ? <small>{availabilityLabel(item.availability)}</small> : null}
          </Fragment>;
        })}
      </div>
    </article>;
  })}</div>;
}
function votingForDay(voting: VotingData, day: number): VotingData {
  return {
    registrations: voting.registrations?.filter((row) => row.day === day), ballots: voting.ballots?.filter((row) => row.day === day),
    days: voting.days?.filter((row) => row.day === day), interruptions: voting.interruptions?.filter((row) => row.day === day),
  };
}
function hasVoting(voting: VotingData) {
  return Boolean(voting.ballots?.length || voting.registrations?.some((row) => row.on_police != null || row.off_police != null)
    || voting.days?.some((row) => [row.sheriff, row.exile].some((status) => status && !["unknown", "not_applicable", "not_held", "none"].includes(status))));
}
function DayRecap({ events, voting, seats }: { events: GameEvent[]; voting: VotingData; seats: Seat[] }) {
  const resultConflictIds: string[] = [];
  for (const kind of ["sheriff", "exile"] as const) {
    const ballots = voting.ballots?.filter((ballot) => ballot.kind === kind) ?? [];
    const finalBallot = ballots.at(-1);
    const result = events.find((event) => event.slot === (kind === "sheriff" ? "sheriff_result" : "exile_result")
      && event.action === (kind === "sheriff" ? "elected" : "exile"));
    const resultSeat = result?.targets?.length === 1 ? result.targets[0] : null;
    if (finalBallot?.status === "complete" && finalBallot.winner != null
      && resultSeat != null && finalBallot.winner !== resultSeat) resultConflictIds.push(finalBallot.id);
  }
  const sheriffVoting: VotingData = {
    registrations: voting.registrations,
    ballots: voting.ballots?.filter((ballot) => ballot.kind === "sheriff"),
    days: voting.days?.map((day) => ({ day: day.day, sheriff: events.some((event) =>
      (event.slot === "badge" && event.action === "badge_lost")
      || (event.slot === "sheriff_result" && event.action === "deferred" && ["deferred", "delayed"].includes(day.sheriff ?? "")))
      ? undefined : day.sheriff })),
  };
  const exileVoting: VotingData = {
    ballots: voting.ballots?.filter((ballot) => ballot.kind === "exile"),
    days: voting.days?.map((day) => ({ day: day.day, exile: day.exile })),
  };
  const resultAt = events.findIndex((event) => event.slot === "exile_vote" || event.slot === "exile_result");
  const splitAt = resultAt < 0 ? events.length : resultAt;
  return <>
    <BallotPanel voting={sheriffVoting} seats={seats} resultConflictIds={resultConflictIds} />
    {splitAt ? <EventList events={events.slice(0, splitAt)} seats={seats} /> : null}
    <BallotPanel voting={exileVoting} seats={seats} resultConflictIds={resultConflictIds} />
    {splitAt < events.length ? <EventList events={events.slice(splitAt)} seats={seats} /> : null}
    <BallotPanel voting={{ ballots: voting.ballots?.filter((ballot) => !["sheriff", "exile"].includes(ballot.kind)) }} seats={seats} />
  </>;
}
export function EventBoard({ rounds, voting = {}, seats = [], terminal = null }: {
  rounds: GameRound[]; voting?: VotingData; seats?: Seat[];
  terminal?: { round: number; phase: "night" | "day"; events: GameEvent[] } | null;
}) {
  const numbers = [...new Set([...rounds.map((round) => round.number), ...(voting.days ?? []).map((row) => row.day), ...(voting.ballots ?? []).map((row) => row.day), ...(voting.registrations ?? []).map((row) => row.day)])]
    .filter((number) => !terminal || number <= terminal.round).sort((a, b) => a - b);
  if (!numbers.length && !terminal?.events.length) return <p className="timeline-empty">当前还没有可整理的日夜行动记录。</p>;
  return <div className="game-timeline">{numbers.map((number) => {
    const round = rounds.find((item) => item.number === number);
    const night = round?.night ?? [], day = round?.day ?? [];
    const dayVoting = votingForDay(voting, number);
    return <Fragment key={number}>
      {night.length ? <section className="timeline-phase timeline-night" data-phase="night" data-day={number}>
        <header className="timeline-phase-header"><span className="timeline-phase-symbol" aria-hidden="true">☾</span><div><p>夜间行动</p><h3>{gamePhaseLabel(number, "night")}</h3></div></header>
        <EventList events={night} seats={seats} isNight />
      </section> : null}
      {(!terminal || number < terminal.round || terminal.phase === "day") && (day.length || hasVoting(dayVoting)) ? <section className="timeline-phase timeline-day" data-phase="day" data-day={number}>
        <header className="timeline-phase-header"><span className="timeline-phase-symbol" aria-hidden="true">☼</span><div><p>白天复盘</p><h3>{gamePhaseLabel(number, "day")}</h3></div></header>
        <DayRecap events={day} voting={dayVoting} seats={seats} />
      </section> : null}
    </Fragment>;
  })}
    {terminal?.events.length ? <section className="timeline-phase timeline-terminal" data-phase="terminal" data-day={terminal.round}>
      <header className="timeline-phase-header"><span className="timeline-phase-symbol" aria-hidden="true">◆</span><div>
        <p>终局结算</p><h3>{gamePhaseLabel(terminal.round, terminal.phase)} · 游戏结束</h3>
      </div></header>
      <EventList events={terminal.events} seats={seats} />
    </section> : null}
  </div>;
}
