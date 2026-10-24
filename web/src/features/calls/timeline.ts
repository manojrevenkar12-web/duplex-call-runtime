import type { CallEvent } from "../../shared/api/types";

export interface Span {
  start: number;
  end: number;
  cut?: boolean; // ended by an interruption
}

export interface Marker {
  t: number;
  kind: "end_of_turn" | "speculate" | "taken_back" | "interrupt" | "hold" | "resume" | "backchannel" | "hedged";
  label: string;
  turn?: number;
}

export interface Lanes {
  duration: number;
  caller: Span[];
  agent: Span[];
  held: Span[];
  markers: Marker[];
}

const num = (v: unknown, fallback = 0): number => (typeof v === "number" ? v : fallback);

/** Turn a call's event log into what the timeline draws: who spoke when, and every decision. */
export function lanes(events: CallEvent[]): Lanes {
  const end = events.find((e) => e.kind === "call_end")?.t ?? events.at(-1)?.t ?? 0;
  const caller: Span[] = [];
  const agent: Span[] = [];
  const held: Span[] = [];
  const markers: Marker[] = [];
  let callerStart: number | null = null;
  let agentStart: number | null = null;
  let holdStart: number | null = null;
  for (const e of events) {
    switch (e.kind) {
      case "caller_speech_start":
        callerStart = num(e.at, e.t);
        break;
      case "caller_speech_end":
        if (callerStart !== null) caller.push({ start: callerStart, end: num(e.at, e.t) });
        callerStart = null;
        break;
      case "agent_audio_start":
        agentStart = e.t;
        break;
      case "agent_audio_end":
        if (agentStart !== null) agent.push({ start: agentStart, end: e.t });
        agentStart = null;
        break;
      case "interrupt":
        if (agentStart !== null) agent.push({ start: agentStart, end: e.t, cut: true });
        agentStart = null;
        if (holdStart !== null) held.push({ start: holdStart, end: e.t });
        holdStart = null;
        markers.push({ t: e.t, kind: "interrupt", label: `Interrupted after ${Math.round(num(e.latency_ms))} ms` });
        break;
      case "hold":
        holdStart = e.t;
        markers.push({ t: e.t, kind: "hold", label: `${e.mode === "pause" ? "Paused" : "Ducked"}: caller sound, no words yet` });
        break;
      case "resume":
        if (holdStart !== null) held.push({ start: holdStart, end: e.t });
        holdStart = null;
        markers.push({ t: e.t, kind: "resume", label: "Resumed: it was not an interruption" });
        break;
      case "end_of_turn":
        markers.push({
          t: e.t,
          kind: "end_of_turn",
          turn: num(e.turn),
          label: `Turn ${num(e.turn)}: answered after ${Math.round(num(e.pause_ms))} ms of silence (${String(e.reason)}, p ${num(e.p).toFixed(2)})`,
        });
        break;
      case "speculate":
        markers.push({ t: e.t, kind: "speculate", label: `Started thinking early (p ${num(e.p).toFixed(2)})` });
        break;
      case "taken_back":
        markers.push({ t: e.t, kind: "taken_back", label: "Caller went on: answer taken back before it was heard" });
        break;
      case "backchannel":
        markers.push({ t: e.t, kind: "backchannel", label: `Backchannel "${String(e.text)}": kept talking` });
        break;
      case "llm_done":
        if (e.hedged) markers.push({ t: e.t, kind: "hedged", label: `Slow first token: hedged, ${String(e.provider)} answered` });
        break;
      default:
        break;
    }
  }
  if (callerStart !== null) caller.push({ start: callerStart, end });
  if (agentStart !== null) agent.push({ start: agentStart, end });
  return { duration: end, caller, agent, held, markers };
}

export interface Exchange {
  turn: number;
  caller: string;
  agent: string;
  interrupted: boolean;
}

/** The conversation as text: what the agent acted on, and what it said back. */
export function transcript(events: CallEvent[]): Exchange[] {
  const out: Exchange[] = [];
  let current: Exchange = { turn: 0, caller: "", agent: "", interrupted: false };
  for (const e of events) {
    if (e.kind === "end_of_turn") {
      if (current.caller || current.agent) out.push(current);
      current = { turn: num(e.turn), caller: String(e.text ?? ""), agent: "", interrupted: false };
    } else if (e.kind === "taken_back") {
      current = { ...current, caller: "", agent: "" };
    } else if (e.kind === "assistant") {
      current.agent = String(e.text ?? "");
      current.interrupted = Boolean(e.interrupted);
    }
  }
  if (current.caller || current.agent) out.push(current);
  return out;
}
