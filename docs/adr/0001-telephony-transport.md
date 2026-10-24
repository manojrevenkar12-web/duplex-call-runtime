# 1. Telephone audio arrives as Twilio Media Streams, and the echo reference is matched by frame count

## Context

The agent answers real phone calls. Phone audio is 8 kHz G.711 mu-law in 20 ms frames, and the
line returns part of the agent's own voice as echo. Python 3.13 has no `audioop`.

## Decision

- The runtime speaks Twilio's Media Streams protocol over one WebSocket per call (`/media`):
  `start` with custom parameters, `media` frames in both directions, `mark` to learn when
  playback reached a point, `clear` to drop the carrier's buffer. `/twilio/voice` returns the
  TwiML that connects a number to it, behind Twilio's request signature.
- G.711 is implemented with lookup tables (`audio/codec.py`); 8 to 16 kHz is a stateful FIR
  upsampler, so frame edges do not click.
- The agent's audio is paced out at real time, one frame per 20 ms tick, rather than sent in
  bursts. The carrier's buffer then stays one or two frames deep, so `clear` and ducking act within
  40 ms, and every outbound tick is known.
- The echo canceller's reference is matched by **count**: inbound frame j is paired with
  outbound tick j - 2. Both directions run at exactly 50 frames a second, so network jitter cannot
  shift the reference under the filter. Matching by arrival time did shift it, and the filter
  diverged.

## Consequences

Another carrier (Vonage, Telnyx, a SIP gateway) needs only a different message adapter around
`CallSession`. The simulator (`sim/caller.py`) speaks the same protocol, so every test call goes
through the production path.
