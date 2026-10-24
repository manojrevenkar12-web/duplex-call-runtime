import { describe, expect, it } from "vitest";

import { callDetail } from "../../test/fixtures";
import { lanes, transcript } from "./timeline";
import { stages } from "./waterfall";

describe("lanes", () => {
  const l = lanes(callDetail.events);

  it("pairs speech starts and ends for both voices, and marks the cut-off reply", () => {
    expect(l.caller).toEqual([
      { start: 4400, end: 6470 },
      { start: 9900, end: 11470 },
    ]);
    expect(l.agent.map((s) => [s.start, s.end, !!s.cut])).toEqual([
      [340, 3200, false],
      [7330, 9000, false],
      [12160, 13000, true],
    ]);
    expect(l.duration).toBe(15000);
  });

  it("keeps every decision as a marker and every hold as a span", () => {
    const kinds = l.markers.map((m) => m.kind);
    expect(kinds).toEqual(["speculate", "end_of_turn", "hedged", "hold", "resume", "end_of_turn", "interrupt"]);
    expect(l.held).toEqual([{ start: 8100, end: 8500 }]);
    expect(l.markers.find((m) => m.kind === "end_of_turn")?.label).toContain("265 ms");
  });
});

describe("transcript", () => {
  it("pairs what the agent acted on with what it said", () => {
    const t = transcript(callDetail.events);
    expect(t).toHaveLength(2);
    expect(t[0]).toMatchObject({ turn: 1, caller: "i'd like to book a haircut please", agent: "Which day would you like?" });
    expect(t[1]?.interrupted).toBe(true);
  });

  it("drops a turn that was taken back", () => {
    const t = transcript([
      { t: 1, kind: "end_of_turn", turn: 1, text: "yes" },
      { t: 2, kind: "taken_back", turn: 1 },
      { t: 3, kind: "end_of_turn", turn: 1, text: "yes that's right" },
    ]);
    expect(t.map((x) => x.caller)).toEqual(["yes that's right"]);
  });
});

describe("stages", () => {
  it("splits a reply into endpointing, model, speech and playout", () => {
    const st = stages(callDetail.summary.turns[0]!);
    expect(st.map((s) => [s.key, s.to - s.from])).toEqual([
      ["endpoint", 265],
      ["llm", 365],
      ["tts", 200],
      ["playout", 30],
    ]);
  });

  it("never draws a negative stage when speculation started the model early", () => {
    const st = stages({ ...callDetail.summary.turns[0]!, llm_first_token: 6600 });
    expect(st.every((s) => s.to >= s.from && s.from >= 0)).toBe(true);
  });
});
