import type { EvalSummary } from "../../shared/api/types";
import { ms, pct } from "../../shared/lib/format";

export interface MetricRow {
  key: string;
  label: string;
  help: string;
  value: (m: EvalSummary) => string;
  /** lower is better: used to mark the best configuration */
  rank?: (m: EvalSummary) => number | null;
}

const ratio = (s: string): number | null => {
  const [a, b] = s.split("/").map(Number);
  return b ? (a as number) / b : null;
};

function interval(v: [number, number, number] | null | undefined): string {
  if (!v) return "–";
  const sign = (x: number) => (x > 0 ? "+" : "");
  return `${sign(v[0])}${ms(v[0])} (${ms(v[1])} to ${ms(v[2])})`;
}

export const ROWS: MetricRow[] = [
  { key: "task", label: "Bookings made correctly", help: "The exact booking, transfer or no-booking the script expects.", value: (m) => m.task_success, rank: (m) => { const r = ratio(m.task_success); return r === null ? null : -r; } },
  { key: "p50", label: "Time to first audio, median", help: "Caller stops speaking to the agent's first sound, measured on the caller's side of the line.", value: (m) => ms(m.response_ms.p50), rank: (m) => m.response_ms.p50 },
  { key: "p90", label: "Time to first audio, 90th percentile", help: "The slow replies a caller notices.", value: (m) => ms(m.response_ms.p90), rank: (m) => m.response_ms.p90 },
  {
    key: "diff",
    label: "Median difference from shipped",
    help: "With a 95% bootstrap interval. An interval that excludes zero is a real difference on this set.",
    value: (m) => interval(m.response_vs_full),
  },
  {
    key: "diff90",
    label: "90th percentile difference from shipped",
    help: "The slow tail: what hedging is for.",
    value: (m) => interval(m.response_p90_vs_full),
  },
  { key: "pause", label: "Spoke into a mid-sentence pause", help: "Lines the caller paused in (dictating a number), where the agent cut in.", value: (m) => (m.pause_takeover_rate === null ? "–" : `${pct(m.pause_takeover_rate)} of ${m.pause_lines}`), rank: (m) => m.pause_takeover_rate },
  { key: "stopped", label: "Interruptions that stopped the agent", help: "Within 1.5 s of the caller starting to talk over it.", value: (m) => m.interrupts_stopped, rank: (m) => { const r = ratio(m.interrupts_stopped); return r === null ? null : -r; } },
  { key: "stop", label: "Time to stop when interrupted, median", help: "Caller starts talking over the agent to the agent's audio stopping.", value: (m) => ms(m.interrupt_stop_ms.p50), rank: (m) => m.interrupt_stop_ms.p50 },
  { key: "bc", label: "Backchannels that stopped the agent", help: "A \"mhm\" or \"genau\" should never cut the agent off.", value: (m) => m.backchannels_disrupted, rank: (m) => ratio(m.backchannels_disrupted) },
  { key: "false", label: "Stops with the caller silent", help: "The agent stopped for its own echo or for noise.", value: (m) => String(m.false_stops), rank: (m) => m.false_stops },
  { key: "wer", label: "Transcript word error rate", help: "What the agent acted on against what the caller said. Digits written as numerals count as errors.", value: (m) => (m.wer === null ? "–" : pct(m.wer)), rank: (m) => m.wer },
  { key: "hedged", label: "Requests hedged to the second provider", help: "The first provider had not produced a token in time.", value: (m) => String(m.hedged) },
];

export const CONFIG_LABEL: Record<string, string> = {
  full: "Shipped",
  silence_endpoint: "Silence endpointing",
  no_speculation: "No speculation",
  no_echo_cancel: "No echo cancelling",
  no_hedging: "No hedging",
  pause_on_barge_in: "Pause, not duck",
};

/** The configuration with the best value for a row, or none when they tie or it has no ranking. */
export function best(row: MetricRow, summary: Record<string, EvalSummary>): string | null {
  if (!row.rank) return null;
  const scored = Object.entries(summary)
    .map(([k, m]) => [k, row.rank?.(m) ?? null] as const)
    .filter((x): x is readonly [string, number] => x[1] !== null);
  if (scored.length < 2) return null;
  const min = Math.min(...scored.map((x) => x[1]));
  const at = scored.filter((x) => x[1] === min);
  return at.length === 1 ? (at[0] as readonly [string, number])[0] : null;
}
