# 3. A possible interruption ducks the agent; echo can never be one

## Context

A caller talking over the agent may be interrupting ("no, Thursday"), agreeing ("mhm"), or not
there at all (the agent's own echo, a door). Stopping for all of them makes the agent stutter;
stopping for none makes it talk over corrections.

## Decision

- **Echo is gated out first.** While the agent talks, inbound sound counts as the caller only if
  it is louder than echo could be: peak above 35% of what was just played, or, once the echo
  canceller has learned the path, far above the echo it predicts (`EchoCanceller.near_end`). In
  the first second of a call the filter has not converged and loud echo passes it; without this
  gate a -18 dB handset paused the agent on every greeting.
- **Then a three-way decision** (`turn/policy.barge_in`) on what the recogniser has heard:
  under 300 ms, ignore; backchannel words, ignore; two words, or one stop word ("no", "wait",
  "nein"), interrupt; anything else, hold.
- **Hold ducks rather than pauses**: the agent keeps talking 14 dB down until it is clear. A
  backchannel then never interrupts the agent's sentence; a real interruption clears the audio
  when the words arrive. `barge_in.hold: pause` stops the audio instead; the evaluation runs both.
- On an interruption the agent records only the words the caller actually heard (frames played),
  so its history does not claim it said what was cut off.
