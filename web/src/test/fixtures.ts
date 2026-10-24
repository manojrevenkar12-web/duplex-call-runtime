import type { CallDetail, CallRow, EvalDoc } from "../shared/api/types";

const opts = { turn_mode: "model", speculate: true, aec: true, barge_in: true };
const booking = { service: "haircut", date: "2026-10-27", time: "10:00", name: "Anna Berger", phone: "017636795025", ref: "B5897F" };

export const callDetail: CallDetail = {
  id: "en-book-basic-1a2b3c",
  started_at: "2026-10-24T20:00:00Z",
  lang: "en",
  scenario: "en-book-basic",
  options: opts,
  events: [
    { t: 10, kind: "call_start" },
    { t: 340, kind: "agent_audio_start", turn: 0 },
    { t: 3200, kind: "agent_audio_end", turn: 0 },
    { t: 4500, kind: "caller_speech_start", at: 4400 },
    { t: 6500, kind: "caller_speech_end", at: 6470, text: "i'd like to book a haircut" },
    { t: 6600, kind: "speculate", p: 0.62 },
    { t: 6735, kind: "end_of_turn", turn: 1, text: "i'd like to book a haircut please", p: 0.896, reason: "end of turn", pause_ms: 265, speech_end: 6470 },
    { t: 7100, kind: "llm_first_token", turn: 1, ms: 360 },
    { t: 7300, kind: "tts", turn: 1, ms: 120 },
    { t: 7320, kind: "llm_done", turn: 1, provider: "secondary", hedged: true },
    { t: 7320, kind: "assistant", text: "Which day would you like?", interrupted: false },
    { t: 7330, kind: "agent_audio_start", turn: 1 },
    { t: 8100, kind: "hold", mode: "duck" },
    { t: 8500, kind: "resume" },
    { t: 9000, kind: "agent_audio_end", turn: 1 },
    { t: 10000, kind: "caller_speech_start", at: 9900 },
    { t: 11500, kind: "caller_speech_end", at: 11470, text: "tomorrow at ten" },
    { t: 11700, kind: "end_of_turn", turn: 2, text: "tomorrow at ten", p: 0.97, reason: "end of turn", pause_ms: 230, speech_end: 11470 },
    { t: 12000, kind: "llm_first_token", turn: 2, ms: 300 },
    { t: 12150, kind: "tts", turn: 2, ms: 110 },
    { t: 12160, kind: "assistant", text: "That time is free. What name should I put the booking under?", interrupted: true },
    { t: 12160, kind: "agent_audio_start", turn: 2 },
    { t: 13000, kind: "interrupt", latency_ms: 420 },
    { t: 15000, kind: "call_end" },
  ],
  summary: {
    turns: [
      { turn: 1, text: "i'd like to book a haircut please", speech_end: 6470, decided: 6735, endpoint_ms: 265, reason: "end of turn", p: 0.896, llm_first_token: 7100, tts_first: 7300, tts_ms: 120, audio_start: 7330, response_ms: 860, after_decision_ms: 595 },
      { turn: 2, text: "tomorrow at ten", speech_end: 11470, decided: 11700, endpoint_ms: 230, reason: "end of turn", p: 0.97, llm_first_token: 12000, tts_first: 12150, tts_ms: 110, audio_start: 12160, response_ms: 690, after_decision_ms: 460, tools: ["check_availability"] },
    ],
    response_ms: [860, 690],
    counts: { interrupt: 1, taken_back: 0, hold: 1 },
    providers: { secondary: 1 },
    hedged: 1,
  },
  outcome: { bookings: [booking], transferred: null },
};

export const callRows: CallRow[] = [
  {
    id: callDetail.id,
    started_at: callDetail.started_at,
    lang: "en",
    scenario: "en-book-basic",
    options: opts,
    turns: 2,
    response_ms: [860, 690],
    counts: { interrupt: 1 },
    outcome: { bookings: [booking], transferred: null },
  },
  {
    id: "de-book-basic-9f8e7d",
    started_at: "2026-10-24T19:00:00Z",
    lang: "de",
    scenario: "de-book-basic",
    options: { ...opts, aec: false },
    turns: 5,
    response_ms: [1200],
    counts: {},
    outcome: { bookings: [], transferred: null },
  },
];

const summary = (p50: number, task: string, bc: string) => ({
  calls: 10,
  response_ms: { n: 40, p50, p90: p50 + 600, mean: p50 + 100 },
  pause_takeover_rate: 0,
  pause_lines: 2,
  interrupt_stop_ms: { n: 2, p50: 480, p90: 900 },
  interrupts_stopped: "2/2",
  backchannels_disrupted: bc,
  false_stops: 0,
  task_success: task,
  wer: 0.12,
  hedged: 3,
  taken_back: 1,
});

export const evalDocs: EvalDoc[] = [
  {
    set: "dev",
    scenarios: ["en-book-basic", "de-book-basic"],
    first_run: false,
    summary: {
      full: summary(1100, "9/10", "0/1"),
      silence_endpoint: { ...summary(1650, "8/10", "0/1"), response_vs_full: [550, 420, 700] },
    },
  },
];
