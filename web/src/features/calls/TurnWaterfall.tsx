import { motion as m } from "framer-motion";

import type { Turn } from "../../shared/api/types";
import { ms } from "../../shared/lib/format";
import { motion } from "../../shared/theme/motion";
import styles from "./TurnWaterfall.module.css";
import { stages } from "./waterfall";

/** One reply's latency, stage by stage, on a shared millisecond axis. */
export function TurnWaterfall({ turn }: { turn: Turn }) {
  const st = stages(turn);
  const total = turn.response_ms ?? st.at(-1)?.to ?? 0;
  const scale = Math.max(total, 1);
  const pctOf = (v: number) => `${(v / scale) * 100}%`;
  return (
    <section className={styles.panel} aria-labelledby={`wf-${turn.turn}`}>
      <header className={styles.head}>
        <h3 id={`wf-${turn.turn}`} className={styles.title}>
          Turn {turn.turn}: {turn.response_ms !== undefined ? `${ms(turn.response_ms)} to first audio` : "no reply reached the line"}
        </h3>
        <p className={styles.heard}>
          Acted on: <q>{turn.text || "(nothing heard)"}</q>
        </p>
        <p className={styles.meta}>
          Ended by {turn.reason.replace(/_/g, " ")}, end-of-turn probability {turn.p.toFixed(2)}
          {turn.tools?.length ? `, tools: ${turn.tools.join(", ")}` : ""}
        </p>
      </header>
      <ol className={styles.rows}>
        {st.map((s, i) => (
          <li key={s.key} className={styles.row}>
            <span className={styles.label}>{s.label}</span>
            <span className={styles.track}>
              <m.span
                className={styles.bar}
                data-stage={s.key}
                style={{ left: pctOf(s.from) }}
                initial={{ width: 0 }}
                animate={{ width: pctOf(s.to - s.from) }}
                transition={{ ...motion.spring, delay: i * motion.fast }}
              />
            </span>
            <span className={styles.value}>{ms(s.to - s.from)}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
