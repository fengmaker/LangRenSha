export function parsePositivePage(value: string | null, fallback = 1): number {
  if (value === null || !/^\d+$/.test(value)) return fallback;
  const number = Number(value);
  return Number.isSafeInteger(number) && number > 0 ? number : fallback;
}
