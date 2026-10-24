import type { Turn } from "../../shared/api/types";

export interface Stage {
  key: "endpoint" | "llm" | "tts" | "playout";
  label: string;
  from: number; // ms after the caller stopped speaking
  to: number;
}

/** Where the milliseconds of one reply went, from the end of the caller's speech to the first
 * agent audio on the line. Stages the turn never reached are left out. */
export function stages(turn: Turn): Stage[] {
  const t0 = turn.speech_end;
  const out: Stage[] = [{ key: "endpoint", label: "Deciding the caller had finished", from: 0, to: turn.decided - t0 }];
  let at = turn.decided;
  if (turn.llm_first_token !== undefined) {
    out.push({ key: "llm", label: "Language model, first token", from: at - t0, to: turn.llm_first_token - t0 });
    at = turn.llm_first_token;
  }
  if (turn.tts_first !== undefined) {
    out.push({ key: "tts", label: "Speech for the first clause", from: at - t0, to: turn.tts_first - t0 });
    at = turn.tts_first;
  }
  if (turn.audio_start !== undefined) {
    out.push({ key: "playout", label: "Onto the phone line", from: at - t0, to: turn.audio_start - t0 });
  }
  // speculation can start the model before the decision: never draw a negative stage
  return out.map((s) => ({ ...s, from: Math.max(0, s.from), to: Math.max(Math.max(0, s.from), s.to) }));
}
