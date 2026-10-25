import Link from "next/link";
import type { GameRound, Seat } from "@/lib/types";
import { factionLabel } from "@/lib/format";
import styles from "./seat-grid.module.css";

type SeatGroup = "werewolf" | "special" | "civilian" | "review";

const goodSpecialRoles = new Set([
  "白痴",
  "白神",
  "盗宝大师",
  "典狱长",
  "定序王子",
  "毒师",
  "诡术师",
  "猎人",
  "假面",
  "蒙面人",
  "魔术师",
  "女巫",
  "摄梦人",
  "守卫",
  "通灵师",
  "舞者",
  "预言家",
]);

const wolfRoles = new Set(["狼人", "狼王", "机械狼"]);

function groupForSeat(seat: Seat | undefined): SeatGroup {
  if (!seat) return "review";
  if (seat.faction === "werewolf") return "werewolf";
  if (seat.faction !== "good" || !seat.role) return "review";
  if (seat.role === "平民" || seat.role === "混血儿") return "civilian";
  if (wolfRoles.has(seat.role)) return "review";
  if (goodSpecialRoles.has(seat.role)) return "special";
  return "review";
}

function hybridTarget(seat: Seat, rounds: GameRound[] | undefined): number | null {
  if (seat.learning_target != null) return seat.learning_target;
  if (seat.role !== "混血儿") return null;

  const targets = (rounds ?? [])
    .filter((round) => round.number === 1)
    .flatMap((round) => round.night ?? [])
    .filter((event) => event.slot === "mixed_blood_model" && event.action === "choose" && event.actor === seat.seat && event.targets?.length === 1)
    .map((event) => event.targets![0]);
  const uniqueTargets = [...new Set(targets)];
  return uniqueTargets.length === 1 ? uniqueTargets[0] : null;
}

function personalFaction(seat: Seat): string {
  if (seat.faction === "good") return "好人阵营";
  if (seat.faction === "werewolf") return "狼人阵营";
  return "阵营待核";
}

function SeatCard({ seat, number, rounds }: { seat?: Seat; number: number; rounds?: GameRound[] }) {
  const group = groupForSeat(seat);
  const cardStyle = group === "werewolf" ? styles.wolfCard : group === "special" ? styles.specialCard : group === "civilian" ? styles.civilianCard : styles.reviewCard;
  const target = seat ? hybridTarget(seat, rounds) : null;
  const name = seat?.name || "姓名未知";
  const note = seat?.role === "混血儿"
    ? `榜样：${target == null ? "待核" : `${target}号`} · 个人阵营：${personalFaction(seat)}。底牌仍为混血儿，不获得榜样能力。`
    : seat?.role === "机械狼"
      ? [target == null ? "学习目标待核" : `学习目标：${target}号`, seat.learned_role ? `学习结果：${seat.learned_role}` : ""].filter(Boolean).join(" · ")
      : seat?.learning_target != null || seat?.learned_role
        ? [seat.learning_target != null ? `记录目标：${seat.learning_target}号` : "", seat.learned_role ? `学习身份：${seat.learned_role}` : ""].filter(Boolean).join(" · ")
        : "";

  return <article className={`${styles.seatCard} ${cardStyle}`} data-seat={number} data-faction={seat?.faction ?? "unknown"} data-role={seat?.role ?? "unknown"}>
    <div className={styles.seatTop}>
      <span className={styles.seatNumber}>{String(number).padStart(2, "0")}</span>
      <span className={styles.seatFaction}>{seat ? factionLabel(seat.faction) : "座位记录缺失"}</span>
    </div>
    <h3 className={styles.seatName}>
      {seat?.person_id
        ? <Link href={`/players/${encodeURIComponent(seat.person_id)}`}>{name}</Link>
        : name}
    </h3>
    <p className={styles.seatRole}>{seat?.role || "身份未知"}</p>
    {note ? <p className={styles.seatNote}>{note}</p> : null}
  </article>;
}

const columns: { key: Exclude<SeatGroup, "review">; title: string; className: string }[] = [
  { key: "werewolf", title: "狼人阵营", className: styles.wolfColumn },
  { key: "special", title: "神职阵营", className: styles.specialColumn },
  { key: "civilian", title: "平民阵营", className: styles.civilianColumn },
];

export function SeatGrid({ seats, rounds }: { seats: Seat[]; rounds?: GameRound[] }) {
  const bySeat = new Map<number, Seat>();
  for (const seat of seats) {
    if (seat.seat >= 1 && seat.seat <= 12 && !bySeat.has(seat.seat)) bySeat.set(seat.seat, seat);
  }
  const ordered = Array.from({ length: 12 }, (_, index) => bySeat.get(index + 1));
  const groups: Record<SeatGroup, { seat?: Seat; number: number }[]> = {
    werewolf: [],
    special: [],
    civilian: [],
    review: [],
  };

  ordered.forEach((seat, index) => groups[groupForSeat(seat)].push({ seat, number: index + 1 }));

  return <section className={styles.roster} aria-label="本局身份与座位">
    <div className={styles.columns}>
      {columns.map((column) => <section className={`${styles.column} ${column.className}`} key={column.key} data-seat-group={column.key}>
        <header className={styles.columnHeader}>
          <h2 className={styles.columnTitle}>{column.title}</h2>
          <span className={styles.columnCount}>{groups[column.key].length} 席</span>
        </header>
        {groups[column.key].length
          ? <div className={styles.seatList}>{groups[column.key].map(({ seat, number }) => <SeatCard key={number} seat={seat} number={number} rounds={rounds} />)}</div>
          : <p className={styles.emptyGroup}>暂无已确认座位</p>}
      </section>)}
    </div>

    {groups.review.length ? <section className={styles.reviewSection} aria-labelledby="seat-review-heading" data-seat-group="review">
      <header className={styles.columnHeader}>
        <h2 className={styles.columnTitle} id="seat-review-heading">待核身份</h2>
        <span className={styles.columnCount}>{groups.review.length} 席</span>
      </header>
      {groups.review.length
        ? <div className={styles.reviewList}>{groups.review.map(({ seat, number }) => <SeatCard key={number} seat={seat} number={number} rounds={rounds} />)}</div>
        : <p className={styles.emptyGroup}>没有待核座位。</p>}
    </section> : null}
  </section>;
}
