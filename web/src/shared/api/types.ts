export interface CallEvent {
  t: number;
  kind: string;
  [k: string]: unknown;
}

export interface Turn {
  turn: number;
  text: string;
  speech_end: number;
  decided: number;
  endpoint_ms: number;
  reason: string;
  p: number;
  llm_first_token?: number;
  tts_first?: number;
  tts_ms?: number;
  audio_start?: number;
  response_ms?: number;
  after_decision_ms?: number;
  tools?: string[];
}

export interface Booking {
  service: string;
  date: string;
  time: string;
  name: string;
  phone: string;
  ref: string;
}

export interface Outcome {
  bookings: Booking[];
  transferred: string | null;
}

export interface Options {
  turn_mode: string;
  speculate: boolean;
  aec: boolean;
  barge_in: boolean;
}

export interface CallRow {
  id: string;
  started_at: string;
  lang: string;
  scenario: string | null;
  options: Options;
  turns: number;
  response_ms: number[];
  counts: Record<string, number>;
  outcome: Outcome;
}

export interface CallDetail {
  id: string;
  started_at: string;
  lang: string;
  scenario: string | null;
  options: Options;
  events: CallEvent[];
  summary: { turns: Turn[]; response_ms: number[]; counts: Record<string, number>; providers: Record<string, number>; hedged: number };
  outcome: Outcome;
}

export interface EvalSummary {
  calls: number;
  response_ms: { n: number; p50: number | null; p90: number | null; mean: number | null };
  pause_takeover_rate: number | null;
  pause_lines: number;
  interrupt_stop_ms: { n: number; p50: number | null; p90: number | null };
  interrupts_stopped: string;
  backchannels_disrupted: string;
  false_stops: number;
  task_success: string;
  wer: number | null;
  hedged: number;
  taken_back: number;
  response_vs_full?: [number, number, number] | null;
  response_p90_vs_full?: [number, number, number] | null;
}

export interface EvalDoc {
  set: string;
  scenarios: string[];
  summary: Record<string, EvalSummary>;
  first_run: boolean;
}
