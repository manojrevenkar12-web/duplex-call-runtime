import { AnimatePresence, motion as m } from "framer-motion";
import { useMemo, useState } from "react";

import type { CallDetail as Detail } from "../../shared/api/types";
import { clock, count, median, ms, outcomeText } from "../../shared/lib/format";
import { motion } from "../../shared/theme/motion";
import { EmptyState } from "../../shared/ui/states";
import styles from "./CallDetail.module.css";
import { CallTimeline } from "./CallTimeline";
import { lanes, transcript } from "./timeline";
import { TurnWaterfall } from "./TurnWaterfall";

export function CallDetail({ call }: { call: Detail }) {
  const l = useMemo(() => lanes(call.events), [call.events]);
  const talk = useMemo(() => transcript(call.events), [call.events]);
  const turns = call.summary.turns;
  const firstAnswered = turns.find((t) => t.response_ms !== undefined)?.turn ?? null;
  const [picked, setPicked] = useState<number | null>(null);
  const selected = picked ?? firstAnswered;
  const turn = turns.find((t) => t.turn === selected);
  const c = call.summary.counts;
  const booking = call.outcome.bookings[0];
  return (
    <article className={styles.detail}>
      <header className={styles.header}>
        <h2 className={styles.title}>{call.scenario ?? "Phone call"}</h2>
        <p className={styles.outcome} data-booked={!!booking || undefined}>
          {outcomeText(call.outcome)}
          {booking && `, for ${booking.name}, ${booking.phone}`}
        </p>
        <dl className={styles.facts}>
          <div>
            <dt>Length</dt>
            <dd>{clock(l.duration)}</dd>
          </div>
          <div>
            <dt>Median reply</dt>
            <dd>{ms(median(call.summary.response_ms))}</dd>
          </div>
          <div>
            <dt>Interruptions</dt>
            <dd>{c.interrupt ?? 0}</dd>
          </div>
          <div>
            <dt>Answers taken back</dt>
            <dd>{c.taken_back ?? 0}</dd>
          </div>
          <div>
            <dt>Hedged requests</dt>
            <dd>{call.summary.hedged}</dd>
          </div>
        </dl>
      </header>

      <section className={styles.section} aria-labelledby="tl-h">
        <h3 id="tl-h" className={styles.h3}>
          Who spoke when
        </h3>
        <p className={styles.help}>Each diamond is a decision that the caller had finished. Select one to see where its reply time went.</p>
        <CallTimeline lanes={l} selected={selected} onSelect={setPicked} />
      </section>

      <AnimatePresence mode="wait">
        {turn ? (
          <m.div key={turn.turn} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: motion.base, ease: motion.ease }}>
            <TurnWaterfall turn={turn} />
          </m.div>
        ) : (
          <EmptyState title="No turns in this call">The caller hung up before the agent decided they had finished speaking.</EmptyState>
        )}
      </AnimatePresence>

      <section className={styles.section} aria-labelledby="tr-h">
        <h3 id="tr-h" className={styles.h3}>
          Transcript, {count(talk.length, "exchange")}
        </h3>
        {talk.length === 0 ? (
          <EmptyState title="Nothing was said">No caller turn was committed in this call.</EmptyState>
        ) : (
          <ol className={styles.transcript}>
            {talk.map((x, i) => (
              <li key={i} className={styles.exchange}>
                {x.caller && (
                  <p className={styles.caller}>
                    <span className={styles.who}>Caller</span>
                    {x.caller}
                  </p>
                )}
                {x.agent && (
                  <p className={styles.agent} data-cut={x.interrupted || undefined}>
                    <span className={styles.who}>Agent</span>
                    {x.agent}
                    {x.interrupted && <span className={styles.cut}>cut off here</span>}
                  </p>
                )}
              </li>
            ))}
          </ol>
        )}
      </section>
    </article>
  );
}
