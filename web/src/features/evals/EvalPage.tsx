import { useEvals } from "../../shared/api/queries";
import { EmptyState, QueryView } from "../../shared/ui/states";
import styles from "./EvalPage.module.css";
import { EvalTable } from "./EvalTable";

export function EvalPage() {
  const evals = useEvals();
  return (
    <main className={styles.page}>
      <header className={styles.intro}>
        <h1 className={styles.title}>Does each part earn its place?</h1>
        <p className={styles.lede}>
          Every scripted call, placed again with one part of the runtime switched off. Green marks the best value in a row.
        </p>
      </header>
      <QueryView
        query={evals}
        what="evaluation results"
        lines={12}
        isEmpty={(d) => d.length === 0}
        empty={
          <EmptyState title="No evaluation has run yet">
            Run <code>dcr eval</code>; its report appears here.
          </EmptyState>
        }
      >
        {(docs) => (
          <div className={styles.sets}>
            {[...docs]
              .sort((a, b) => Number(b.first_run) - Number(a.first_run))
              .map((d) => (
                <EvalTable key={d.set} doc={d} />
              ))}
          </div>
        )}
      </QueryView>
    </main>
  );
}
