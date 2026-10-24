import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MotionConfig } from "framer-motion";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { CallsPage } from "../features/calls/CallsPage";
import { EvalPage } from "../features/evals/EvalPage";
import { ApiError } from "../shared/api/client";
import { EmptyState } from "../shared/ui/states";
import { Shell } from "./Shell";

export function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // a missing call will not appear by asking again; a runtime that is restarting will
        retry: (n, err) => !(err instanceof ApiError && err.status === 404) && n < 2,
        staleTime: 5_000,
      },
    },
  });
}

export function Routed() {
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<Navigate to="/calls" replace />} />
        <Route path="/calls" element={<CallsPage />} />
        <Route path="/calls/:id" element={<CallsPage />} />
        <Route path="/evals" element={<EvalPage />} />
        <Route
          path="*"
          element={
            <main className="page-pad">
              <EmptyState title="There is no page here">Use Calls or Evaluation above.</EmptyState>
            </main>
          }
        />
      </Routes>
    </Shell>
  );
}

export function App({ client = makeClient() }: { client?: QueryClient }) {
  return (
    <QueryClientProvider client={client}>
      <MotionConfig reducedMotion="user">
        <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <Routed />
        </BrowserRouter>
      </MotionConfig>
    </QueryClientProvider>
  );
}
