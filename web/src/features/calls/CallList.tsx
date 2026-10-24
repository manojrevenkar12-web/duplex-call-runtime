import { NavLink } from "react-router-dom";

import type { CallRow } from "../../shared/api/types";
import { count, median, ms, outcomeText } from "../../shared/lib/format";
import styles from "./CallList.module.css";

function flags(c: CallRow): string[] {
  const out: string[] = [];
  if (c.options.turn_mode !== "model") out.push("silence endpointing");
  if (!c.options.speculate) out.push("no speculation");
  if (!c.options.aec) out.push("no echo cancelling");
  return out;
}

export function CallList({ calls }: { calls: CallRow[] }) {
  return (
    <ul className={styles.list} aria-label="Calls, newest first">
      {calls.map((c) => {
        const f = flags(c);
        const interrupts = c.counts.interrupt ?? 0;
        return (
          <li key={c.id}>
            <NavLink to={`/calls/${encodeURIComponent(c.id)}`} className={styles.item}>
              <span className={styles.top}>
                <span className={styles.name}>{c.scenario ?? "Phone call"}</span>
                <span className={styles.lang}>{c.lang}</span>
              </span>
              <span className={styles.outcome} data-booked={c.outcome.bookings.length > 0 || undefined}>
                {outcomeText(c.outcome)}
              </span>
              <span className={styles.stats}>
                <span>
                  {count(c.turns, "turn")}, median reply {ms(median(c.response_ms))}
                </span>
                {interrupts > 0 && <span>{interrupts === 1 ? "1 interruption" : `${interrupts} interruptions`}</span>}
              </span>
              {f.length > 0 && <span className={styles.flags}>{f.join(", ")}</span>}
            </NavLink>
          </li>
        );
      })}
    </ul>
  );
}
