import { useParams } from "react-router-dom";

import { useCall, useCalls } from "../../shared/api/queries";
import { EmptyState, QueryView } from "../../shared/ui/states";
import { CallDetail } from "./CallDetail";
import { CallList } from "./CallList";
import styles from "./CallsPage.module.css";

export function CallsPage() {
  const { id } = useParams();
  const calls = useCalls();
  const current = id ?? calls.data?.[0]?.id ?? null;
  const call = useCall(current);
  return (
    <div className={styles.page}>
      <aside className={styles.list}>
        <QueryView
          query={calls}
          what="calls"
          lines={8}
          isEmpty={(d) => d.length === 0}
          empty={
            <EmptyState title="No calls yet">
              Point a Twilio number at <code>/twilio/voice</code>, or run <code>dcr eval</code> to place simulated calls.
            </EmptyState>
          }
        >
          {(d) => <CallList calls={d} />}
        </QueryView>
      </aside>
      <main className={styles.main}>
        {current ? (
          <QueryView query={call} what="this call" lines={10}>
            {(d) => <CallDetail key={d.id} call={d} />}
          </QueryView>
        ) : (
          !calls.isPending && !calls.isError && <EmptyState title="Pick a call">Its timeline and per-turn latency appear here.</EmptyState>
        )}
      </main>
    </div>
  );
}
