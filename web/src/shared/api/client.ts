import type { CallDetail, CallRow, EvalDoc } from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path);
  } catch {
    throw new ApiError(0, "The runtime did not answer. Check that `dcr serve` is running.");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail || `HTTP ${res.status}`);
  }
  return (await res.json()) as T;
}

export const api = {
  calls: (scenario?: string) => request<CallRow[]>(`/api/calls?limit=200${scenario ? `&scenario=${encodeURIComponent(scenario)}` : ""}`),
  call: (id: string) => request<CallDetail>(`/api/calls/${encodeURIComponent(id)}`),
  evals: () => request<EvalDoc[]>("/api/evals"),
};
