/** Motion constants, matching the CSS tokens. One orchestrated reveal (the call timeline
 * drawing in); everything else only answers what the person did. */
export const motion = {
  fast: 0.12,
  base: 0.22,
  draw: 0.9,
  ease: [0.22, 1, 0.36, 1] as const,
  spring: { type: "spring" as const, stiffness: 380, damping: 34 },
};
