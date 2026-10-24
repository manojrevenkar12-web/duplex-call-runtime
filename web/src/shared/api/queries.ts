import { useQuery } from "@tanstack/react-query";

import { api } from "./client";

export const useCalls = (scenario?: string) => useQuery({ queryKey: ["calls", scenario ?? ""], queryFn: () => api.calls(scenario), refetchInterval: 10_000 });
export const useCall = (id: string | null) => useQuery({ queryKey: ["call", id], queryFn: () => api.call(id as string), enabled: !!id });
export const useEvals = () => useQuery({ queryKey: ["evals"], queryFn: api.evals });
