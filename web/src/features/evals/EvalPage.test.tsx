import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { evalDocs } from "../../test/fixtures";
import { renderAt } from "../../test/render";
import { mockApi } from "../../test/server";

describe("Evaluation", () => {
  it("shows configurations against measures and marks the best", async () => {
    mockApi({ "/api/evals": evalDocs });
    renderAt("/evals");
    const table = await screen.findByRole("table");
    expect(within(table).getByRole("columnheader", { name: "Shipped" })).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: "Silence endpointing" })).toBeInTheDocument();
    const row = within(table).getByRole("row", { name: /Time to first audio, median/ });
    expect(within(row).getByText(/1,100 ms/)).toHaveAttribute("data-best");
    expect(within(table).getByText("+550 ms (420 ms to 700 ms)")).toBeInTheDocument();
  });

  it("puts a held-out first run first and labels it", async () => {
    mockApi({ "/api/evals": [...evalDocs, { ...evalDocs[0]!, set: "set1", first_run: true }] });
    renderAt("/evals");
    const headings = await screen.findAllByRole("heading", { level: 2 });
    expect(headings[0]).toHaveTextContent("Held-out set set1, first run");
  });

  it("says how to produce results when there are none", async () => {
    mockApi({ "/api/evals": [] });
    renderAt("/evals");
    expect(await screen.findByText("No evaluation has run yet")).toBeInTheDocument();
  });

  it("shows the server's reason when it fails", async () => {
    mockApi({ "/api/evals": () => ({ status: 500, body: { detail: "reports folder unreadable" } }) });
    renderAt("/evals");
    expect(await screen.findByRole("alert")).toHaveTextContent("reports folder unreadable");
  });
});
