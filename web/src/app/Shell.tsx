import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

import styles from "./Shell.module.css";

/** The two voices of a call, offset: the caller above, the agent below. */
function Mark() {
  return (
    <svg className={styles.mark} viewBox="0 0 24 24" aria-hidden="true">
      <rect x="2" y="5" width="9" height="5" rx="2.5" className={styles.markCaller} />
      <rect x="9" y="14" width="13" height="5" rx="2.5" className={styles.markAgent} />
    </svg>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  return (
    <div className={styles.shell}>
      <a href="#content" className={styles.skip}>
        Skip to content
      </a>
      <header className={styles.bar}>
        <span className={styles.brand}>
          <Mark />
          <span>Duplex call runtime</span>
        </span>
        <nav aria-label="Sections" className={styles.nav}>
          <NavLink to="/calls" className={styles.link}>
            Calls
          </NavLink>
          <NavLink to="/evals" className={styles.link}>
            Evaluation
          </NavLink>
        </nav>
      </header>
      <div id="content" className={styles.content}>
        {children}
      </div>
    </div>
  );
}
