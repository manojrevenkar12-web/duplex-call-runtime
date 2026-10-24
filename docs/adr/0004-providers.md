# 4. Every LLM request can be hedged to a second provider

## Context

The language model's time to first token is the largest and most variable part of a reply. Hosted
APIs have a slow tail (requests that wait a second or more) and outages; our own GPU has queueing.

## Decision

`llm/router.py` streams from OpenAI-compatible providers in order:

- If no token has arrived after 450 ms, the same request goes to the next provider, and the first
  to produce a token wins; the loser is cancelled.
- A provider that errors, does not start within 2 s, or stalls mid-stream for 1.2 s counts a
  failure; three in 30 s open its circuit for 20 s.
- A stream that breaks after text was spoken is not retried (the caller heard half a sentence);
  the agent apologises and asks again.
- Only read-only tools (`check_availability`) may run on a speculative reply. A booking or a
  transfer waits for the turn to be committed.

## Consequences

Hedging costs a duplicate request on about one turn in ten. The evaluation's providers have an 8%
slow tail of +1.2 s, so `no_hedging` shows what it buys.
