import { describe, expect, it } from "vitest";

import { clock, count, median, ms, outcomeText, pct } from "./format";

describe("format", () => {
  it("formats durations and clocks", () => {
    expect(ms(842.4)).toBe("842 ms");
    expect(ms(12_345)).toBe("12.3 s");
    expect(ms(null)).toBe("–");
    expect(clock(65_400)).toBe("1:05.4");
  });

  it("computes medians and percentages", () => {
    expect(median([3, 1, 2])).toBe(2);
    expect(median([4, 1, 2, 3])).toBe(2.5);
    expect(median([])).toBeNull();
    expect(pct(0.125)).toBe("13%");
    expect(count(1, "turn")).toBe("1 turn");
    expect(count(3, "turn")).toBe("3 turns");
  });

  it("describes outcomes", () => {
    expect(outcomeText({ bookings: [], transferred: "front desk" })).toBe("Put through to a person");
    expect(outcomeText({ bookings: [], transferred: null })).toBe("No booking");
  });
});
