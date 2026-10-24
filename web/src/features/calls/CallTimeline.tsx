import { motion as m } from "framer-motion";
import { useId } from "react";

import { clock } from "../../shared/lib/format";
import { motion } from "../../shared/theme/motion";
import styles from "./CallTimeline.module.css";
import type { Lanes, Marker } from "./timeline";

const PX_PER_S = 56;
const LANE = 36;
const ROW = 30;
const TOP = 22;
const Y = { caller: TOP, markers: TOP + LANE + 6, agent: TOP + LANE + ROW + 12 };
const HEIGHT = Y.agent + LANE + 8;

const LABEL: Record<Marker["kind"], string> = {
  end_of_turn: "Answered",
  speculate: "Thinking early",
  taken_back: "Taken back",
  interrupt: "Interrupted",
  hold: "Paused",
  resume: "Resumed",
  backchannel: "Backchannel",
  hedged: "Hedged",
};

/** The call as two lanes: the caller's speech above, the agent's below, every turn decision
 * between them. Selecting an answer opens its latency breakdown. */
export function CallTimeline({ lanes, selected, onSelect }: { lanes: Lanes; selected: number | null; onSelect: (turn: number) => void }) {
  const clip = useId().replace(/:/g, "");
  const width = Math.max(600, (lanes.duration / 1000) * PX_PER_S + 40);
  const x = (t: number) => 20 + (t / 1000) * PX_PER_S;
  const ticks = Array.from({ length: Math.floor(lanes.duration / 5000) + 1 }, (_, i) => i * 5000);
  return (
    <figure className={styles.figure}>
      <figcaption className={styles.legend}>
        <span className={styles.key} data-kind="caller">Caller speaking</span>
        <span className={styles.key} data-kind="agent">Agent speaking</span>
        <span className={styles.key} data-kind="decision">Turn decisions</span>
        <span className={styles.key} data-kind="interrupt">Interruptions</span>
      </figcaption>
      <div className={styles.scroller} tabIndex={0} aria-label="Call timeline, scroll sideways">
        <svg width={width} height={HEIGHT} role="img" aria-label={`Call timeline, ${clock(lanes.duration)} long`}>
          <defs>
            <clipPath id={clip}>
              <m.rect x={0} y={0} height={HEIGHT} initial={{ width: 0 }} animate={{ width }} transition={{ duration: motion.draw, ease: motion.ease }} />
            </clipPath>
            <pattern id={`${clip}-hatch`} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <line x1="0" y1="0" x2="0" y2="6" className={styles.hatch} />
            </pattern>
          </defs>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={x(t)} x2={x(t)} y1={TOP - 6} y2={HEIGHT} className={styles.grid} />
              <text x={x(t) + 3} y={TOP - 10} className={styles.tick}>
                {clock(t)}
              </text>
            </g>
          ))}
          <text x={4} y={Y.caller + LANE / 2 + 4} className={styles.laneLabel}>
            caller
          </text>
          <g clipPath={`url(#${clip})`}>
            <line x1={0} x2={width} y1={Y.caller + LANE / 2} y2={Y.caller + LANE / 2} className={styles.baseline} />
            <line x1={0} x2={width} y1={Y.agent + LANE / 2} y2={Y.agent + LANE / 2} className={styles.baseline} />
            {lanes.caller.map((s) => (
              <rect key={`c${s.start}`} x={x(s.start)} y={Y.caller + 4} width={Math.max(2, x(s.end) - x(s.start))} height={LANE - 8} rx={3} className={styles.caller}>
                <title>{`Caller ${clock(s.start)}–${clock(s.end)}`}</title>
              </rect>
            ))}
            {lanes.agent.map((s) => (
              <rect key={`a${s.start}`} x={x(s.start)} y={Y.agent + 4} width={Math.max(2, x(s.end) - x(s.start))} height={LANE - 8} rx={3} className={styles.agent} data-cut={s.cut || undefined}>
                <title>{`Agent ${clock(s.start)}–${clock(s.end)}${s.cut ? ", cut off by the caller" : ""}`}</title>
              </rect>
            ))}
            {lanes.held.map((s) => (
              <rect key={`h${s.start}`} x={x(s.start)} y={Y.agent + 2} width={Math.max(2, x(s.end) - x(s.start))} height={LANE - 4} fill={`url(#${clip}-hatch)`} className={styles.held}>
                <title>{`Paused ${clock(s.start)}–${clock(s.end)}`}</title>
              </rect>
            ))}
            {lanes.markers.map((mk, i) => {
              const cx = x(mk.t);
              if (mk.kind === "interrupt") {
                return (
                  <line key={i} x1={cx} x2={cx} y1={Y.caller} y2={Y.agent + LANE} className={styles.interrupt}>
                    <title>{mk.label}</title>
                  </line>
                );
              }
              const isTurn = mk.kind === "end_of_turn" && mk.turn !== undefined;
              const on = isTurn && mk.turn === selected;
              return (
                <g
                  key={i}
                  className={styles.marker}
                  data-kind={mk.kind}
                  data-on={on || undefined}
                  transform={`translate(${cx} ${Y.markers + ROW / 2})`}
                  {...(isTurn
                    ? {
                        role: "button",
                        tabIndex: 0,
                        "aria-label": mk.label,
                        "aria-pressed": on,
                        onClick: () => onSelect(mk.turn as number),
                        onKeyDown: (ev: React.KeyboardEvent) => {
                          if (ev.key === "Enter" || ev.key === " ") {
                            ev.preventDefault();
                            onSelect(mk.turn as number);
                          }
                        },
                      }
                    : {})}
                >
                  <title>{mk.label}</title>
                  {isTurn ? <path d="M0 -8 L8 0 L0 8 L-8 0 Z" /> : <circle r={4} />}
                </g>
              );
            })}
          </g>
          <text x={4} y={Y.agent + LANE / 2 + 4} className={styles.laneLabel}>
            agent
          </text>
        </svg>
      </div>
      <ul className={styles.markerKey} aria-label="Marker shapes">
        {(["end_of_turn", "speculate", "taken_back", "hold", "backchannel", "hedged"] as const)
          .filter((k) => lanes.markers.some((mk) => mk.kind === k))
          .map((k) => (
            <li key={k} data-kind={k}>
              {LABEL[k]}
            </li>
          ))}
      </ul>
    </figure>
  );
}
