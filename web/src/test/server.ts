import { vi } from "vitest";

type Handler = (url: URL) => { status?: number; body: unknown } | "network";

/** Answer the console's API calls from a table of routes; anything else is a 404. */
export function mockApi(routes: Record<string, Handler | unknown>) {
  const fn = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://localhost");
    const route = routes[url.pathname];
    if (route === undefined) return new Response(JSON.stringify({ detail: "no such call" }), { status: 404 });
    const res = typeof route === "function" ? (route as Handler)(url) : { body: route };
    if (res === "network") throw new TypeError("Failed to fetch");
    return new Response(JSON.stringify(res.body), { status: res.status ?? 200, headers: { "content-type": "application/json" } });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}
