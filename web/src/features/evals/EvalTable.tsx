import type { EvalDoc } from "../../shared/api/types";
import { count } from "../../shared/lib/format";
import styles from "./EvalTable.module.css";
import { best, CONFIG_LABEL, ROWS } from "./metrics";

export function EvalTable({ doc }: { doc: EvalDoc }) {
  const configs = Object.keys(doc.summary);
  return (
    <section className={styles.set} aria-labelledby={`set-${doc.set}`}>
      <header className={styles.head}>
        <h2 id={`set-${doc.set}`} className={styles.title}>
          {doc.first_run ? `Held-out ${doc.set.replace(/^set/, "set ")}, first run` : `${doc.set[0]?.toUpperCase()}${doc.set.slice(1)} set`}
        </h2>
        <p className={styles.sub}>
          {count(doc.scenarios.length, "simulated call")} per configuration, scored from the caller's side of the line.
          {doc.first_run && " Written by someone who had not seen the runtime; this run is never rewritten."}
        </p>
      </header>
      <div className={styles.scroller} tabIndex={0} aria-label={`${doc.set} results, scroll sideways`}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col" className={styles.metricHead}>
                Measure
              </th>
              {configs.map((c) => (
                <th key={c} scope="col" data-shipped={c === "full" || undefined}>
                  {CONFIG_LABEL[c] ?? c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ROWS.map((row) => {
              const top = best(row, doc.summary);
              return (
                <tr key={row.key}>
                  <th scope="row" className={styles.metric}>
                    <span>{row.label}</span>
                    <span className={styles.help}>{row.help}</span>
                  </th>
                  {configs.map((c) => {
                    const m = doc.summary[c];
                    return (
                      <td key={c} data-shipped={c === "full" || undefined} data-best={top === c || undefined}>
                        {m ? row.value(m) : "–"}
                        {top === c && <span className="visually-hidden"> (best)</span>}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
