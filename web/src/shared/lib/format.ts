export function ms(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return v >= 10_000 ? `${(v / 1000).toFixed(1)} s` : `${Math.round(v).toLocaleString("en")} ms`;
}

export function clock(msFromStart: number): string {
  const s = msFromStart / 1000;
  const m = Math.floor(s / 60);
  return `${m}:${(s - m * 60).toFixed(1).padStart(4, "0")}`;
}

export function median(xs: number[]): number | null {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? (s[mid] as number) : ((s[mid - 1] as number) + (s[mid] as number)) / 2;
}

export function pct(v: number | null | undefined): string {
  return v === null || v === undefined ? "–" : `${Math.round(v * 100)}%`;
}

export function count(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString("en")} ${n === 1 ? one : many}`;
}

export const SERVICE: Record<string, string> = { haircut: "Haircut", colour: "Colouring", beard: "Beard trim" };

export function outcomeText(o: { bookings: { service: string; date: string; time: string }[]; transferred: string | null }): string {
  const b = o.bookings[0];
  if (b) return `${SERVICE[b.service] ?? b.service}, ${b.date} ${b.time}`;
  if (o.transferred) return "Put through to a person";
  return "No booking";
}
