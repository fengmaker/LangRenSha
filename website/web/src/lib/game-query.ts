import type { GameSummary } from "@/lib/types";

export type IndexedGame = GameSummary & { search_text?: string };
export type GameFilters = { season?: string; phase?: string; board?: string; player?: string; q?: string; date_from?: string; date_to?: string };

function contains(value: string, needle: string) {
  return value.toLowerCase().includes(needle.toLowerCase());
}

function validIsoDate(value: string): boolean {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (year < 1 || month < 1 || month > 12) return false;
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const daysInMonth = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return day >= 1 && day <= daysInMonth[month - 1];
}

function characterLength(value: string): number {
  return [...value].length;
}

export function validateGameFilters(filters: GameFilters): string | null {
  const limits: [keyof GameFilters, number, string][] = [
    ["season", 32, "赛季"], ["phase", 32, "比赛阶段"], ["board", 64, "版型"], ["player", 120, "选手"], ["q", 120, "关键词"],
  ];
  for (const [key, limit, label] of limits) {
    const value = filters[key];
    if (value !== undefined && characterLength(value) > limit) return `${label}筛选最多${limit}个字符。`;
  }
  if (filters.date_from !== undefined && !validIsoDate(filters.date_from)) return "开始日期必须是有效的 YYYY-MM-DD 日期。";
  if (filters.date_to !== undefined && !validIsoDate(filters.date_to)) return "截止日期必须是有效的 YYYY-MM-DD 日期。";
  if (filters.date_from && filters.date_to && filters.date_from > filters.date_to) return "开始日期不能晚于截止日期。";
  return null;
}

export function filterAndSortGames(games: IndexedGame[], filters: GameFilters): IndexedGame[] {
  if (validateGameFilters(filters)) return [];
  return games.filter((game) =>
    (!filters.season || game.season === filters.season)
    && (!filters.phase || game.phase === filters.phase)
    && (!filters.board || game.board.code === filters.board)
    && (!filters.date_from || game.date >= filters.date_from)
    && (!filters.date_to || game.date <= filters.date_to)
    && (!filters.player || game.players.some((player) => player.id === filters.player || contains(player.name, filters.player!)))
    && (!filters.q || contains(game.search_text ?? [game.id, game.date, game.season, game.board.name, ...game.players.map((player) => player.name)].join(" "), filters.q))
  ).slice().sort((a, b) => (a.date === b.date ? 0 : a.date > b.date ? -1 : 1)
    || (b.game_number ?? Number.NEGATIVE_INFINITY) - (a.game_number ?? Number.NEGATIVE_INFINITY)
    || (a.id === b.id ? 0 : a.id < b.id ? -1 : 1));
}
