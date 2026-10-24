# 5. One batched recogniser per process, off the event loop

## Context

Streaming recognition on the event loop that also runs the calls made inbound audio queue up:
turn decisions were made on stale audio, and the echo canceller lost alignment (inbound lag p95
over 40 ms, peaks near 200 ms, on two cores).

## Decision

`serving/stt_service.py` runs one decoder thread per process. Calls hand over audio and read
their transcript; before a decision they `await sync()` for everything they fed (bounded at 1 s).
Each pass decodes all streams that have a chunk ready in one `decode_streams` call, up to
`serving.max_batch`, so the encoder runs once per batch rather than once per call. German uses
Whisper per pause in an executor (it is not streaming).

## Consequences

Capacity per pod is set by the batch (docs/MEASUREMENTS.md, "Serving"); on a GPU the same
service runs with `DCR_MODEL_PROVIDER=cuda`. The LLM is served separately (vLLM,
deploy/k8s/vllm.yaml) and reached as a provider.
