import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { callDetail, callRows } from "../../test/fixtures";
import { renderAt } from "../../test/render";
import { mockApi } from "../../test/server";

describe("Calls", () => {
  it("shows a skeleton, then the list and the newest call", async () => {
    mockApi({ "/api/calls": callRows, [`/api/calls/${callDetail.id}`]: callDetail });
    renderAt("/calls");
    expect(screen.getAllByRole("status")[0]).toHaveTextContent("Loading calls");
    const list = await screen.findByRole("list", { name: /calls, newest first/i });
    expect(within(list).getAllByRole("link")).toHaveLength(2);
    expect(await screen.findByRole("heading", { level: 2, name: "en-book-basic" })).toBeInTheDocument();
    expect(screen.getByText(/Haircut, 2026-10-27 10:00, for Anna Berger/)).toBeInTheDocument();
    expect(within(list).getByText("no echo cancelling")).toBeInTheDocument();
  });

  it("opens a turn's latency breakdown from its diamond on the timeline", async () => {
    mockApi({ "/api/calls": callRows, [`/api/calls/${callDetail.id}`]: callDetail });
    renderAt(`/calls/${callDetail.id}`);
    expect(await screen.findByRole("heading", { level: 3, name: /Turn 1: 860 ms to first audio/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Turn 2: answered after 230 ms/ }));
    expect(await screen.findByRole("heading", { level: 3, name: /Turn 2: 690 ms to first audio/ })).toBeInTheDocument();
    expect(screen.getByText(/tools: check_availability/)).toBeInTheDocument();
    expect(screen.getByText("cut off here")).toBeInTheDocument();
  });

  it("lets the keyboard pick a turn too", async () => {
    mockApi({ "/api/calls": callRows, [`/api/calls/${callDetail.id}`]: callDetail });
    renderAt(`/calls/${callDetail.id}`);
    const diamond = await screen.findByRole("button", { name: /Turn 2/ });
    diamond.focus();
    await userEvent.keyboard("{Enter}");
    expect(await screen.findByRole("heading", { level: 3, name: /Turn 2/ })).toBeInTheDocument();
  });

  it("says how to get calls when there are none", async () => {
    mockApi({ "/api/calls": [] });
    renderAt("/calls");
    expect(await screen.findByText("No calls yet")).toBeInTheDocument();
    expect(screen.getByText("/twilio/voice")).toBeInTheDocument();
  });

  it("explains a failure and retries on request", async () => {
    let n = 0;
    mockApi({ "/api/calls": () => (n++ === 0 ? "network" : { body: callRows }), [`/api/calls/${callDetail.id}`]: callDetail });
    renderAt("/calls");
    expect(await screen.findByRole("alert")).toHaveTextContent(/The runtime did not answer/);
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("list", { name: /calls, newest first/i })).toBeInTheDocument();
  });

  it("says a missing call is not in the database", async () => {
    mockApi({ "/api/calls": callRows });
    renderAt("/calls/gone");
    expect(await screen.findByRole("alert")).toHaveTextContent(/not in this database/);
  });
});
