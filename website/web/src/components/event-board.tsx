import { Fragment } from "react";
import type { GameEvent, GameTimeline, Seat } from "@/lib/types";
import { availabilityLabel, gameTimeText } from "@/lib/format";
import { BallotPanel } from "@/components/ballot-panel";

function seatText(number: number, seats: Seat[]): string {
  const seat = seats.find((item) => item.seat === number);
  return `${number}号${seat?.name ?? ""}${seat?.role ? `（${seat.role}）` : ""}`;
}

function effectText(effect: NonNullable<GameEvent["effects"]>[number], seats: Seat[]): string {
  const parts = [effect.kind === "poison_reflected" ? "毒药反弹" : "技能结算"];
  if (effect.intended_target != null) parts.push(`原目标：${seatText(effect.intended_target, seats)}`);
  if (effect.dead_seat != null) parts.push(`实际出局：${seatText(effect.dead_seat, seats)}`);
  if (effect.shield_actor != null) parts.push(`护盾来自${seatText(effect.shield_actor, seats)}`);
  return parts.join("；");
}

function conflictingResults(phase: GameTimeline["phases"][number]): string[] {
  const ids: string[] = [];
  const events = phase.items.flatMap((item) => item.kind === "event" ? item.events : []);
  for (const kind of ["sheriff", "exile"] as const) {
    const ballots = phase.items.flatMap((item) => item.kind === "ballot" && item.ballot.kind === kind ? [item.ballot] : []);
    const finalBallot = ballots.at(-1);
    const result = events.find((event) => event.slot === (kind === "sheriff" ? "sheriff_result" : "exile_result")
      && event.action === (kind === "sheriff" ? "elected" : "exile"));
    const resultSeat = result?.targets?.length === 1 ? result.targets[0] : null;
    if (finalBallot?.status === "complete" && finalBallot.winner != null
      && resultSeat != null && finalBallot.winner !== resultSeat) ids.push(finalBallot.id);
  }
  return ids;
}

export function EventBoard({ timeline, seats = [] }: { timeline: GameTimeline; seats?: Seat[] }) {
  if (!timeline.phases.length) return <p className="timeline-empty">当前还没有可整理的日夜行动记录。</p>;
  return <>
    <nav className="timeline-index" aria-label="按日夜跳转">{timeline.phases.map((phase) =>
      <a key={`${phase.number}-${phase.phase}`} href={`#phase-${phase.number}-${phase.phase}`} data-phase={phase.phase}>{phase.label}</a>
    )}</nav>
    <div className="game-timeline">{timeline.phases.map((phase) => {
    const night = phase.phase === "night";
    const conflictIds = conflictingResults(phase);
    return <section key={`${phase.number}-${phase.phase}`} id={`phase-${phase.number}-${phase.phase}`} tabIndex={-1}
      className={`timeline-phase timeline-${phase.phase}${phase.terminal ? " timeline-terminal" : ""}`}
      data-phase={phase.phase} data-day={phase.number} aria-labelledby={`phase-title-${phase.number}-${phase.phase}`}>
      <header className="timeline-phase-header">
        <svg className="timeline-phase-symbol" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          {night ? <path d="M20.5 13A8.5 8.5 0 0 1 11 3.5 8.5 8.5 0 1 0 20.5 13Z" /> : <><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" /></>}
        </svg>
        <h3 id={`phase-title-${phase.number}-${phase.phase}`}>{phase.label}</h3>
        {phase.terminal ? <span className="timeline-terminal-label">终局结算</span> : null}
      </header>
      <div className="game-event-list">{phase.items.map((item, index) => item.kind === "ballot"
        ? <div key={item.ballot.id} data-slot={item.slot}>
          <BallotPanel voting={{ ballots: [item.ballot] }} seats={seats} resultConflictIds={conflictIds} />
        </div>
        : <article className="game-event" key={`${item.slot}-${index}`} data-slot={item.slot}
          data-action={item.events.length === 1 ? item.events[0].action : "combined"}>
          <div className="game-event-label"><span>{item.title}</span></div>
          <div className="game-event-content">
            {item.text.split("\n").map((text, line) => <p key={line}>{text}</p>)}
            {item.events.map((event, detail) => <Fragment key={detail}>
              {event.effects?.length ? <small className="game-event-effects">{event.effects.map((effect) => effectText(effect, seats)).join("；")}</small> : null}
              {event.inference_note && !event.resolved_targets?.length && event.action !== "badge_lost" && event.result !== "double_tie"
                ? <small>{gameTimeText(event.inference_note)}</small> : null}
              {event.availability && !event.inferred ? <small>{availabilityLabel(event.availability)}</small> : null}
            </Fragment>)}
          </div>
        </article>)}</div>
    </section>;
  })}</div></>;
}
