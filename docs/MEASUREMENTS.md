# Measurements

Everything here was measured on the machine the repository was built on: 2 CPU cores, no GPU.
The scripts are in the repository; numbers on other machines will differ, the method will not.

## Speech recognition on phone audio

Test audio: every caller line of the English dev calls, synthesised (Piper), band-limited to
300-3400 Hz, mu-law coded and upsampled to 16 kHz, as the runtime receives it. Word error rate
against the script; digits written as numerals count as errors.

| English recogniser (streaming) | WER, caller voice amy | lessac | ryan | alan |
|---|---:|---:|---:|---:|
| NeMo FastConformer transducer, 80 ms, int8 (shipped) | 14.0% | 14.0% | 16.7% | 16.3% |

The 20M-parameter streaming Zipformer (`stt_en_streaming`) is about 7x cheaper but split "haircut"
into "hair could" on most calls; on one full booking call its transcript WER was 60.7% against
9.1% for the NeMo model, so it is kept only as a comparison.

The errors that remain matter in this order: repeated digits merged ("five five five" heard as
"five five"), first words of a turn ("hello" heard as "to low"), and names ("Fischer" as
"Fisher", which the booking check accepts).

| German recogniser (per pause) | WER | ms per utterance |
|---|---:|---:|
| Whisper tiny, int8, whole buffer | 60.8% | 388 |
| Whisper tiny, int8, speech span only | 48.6% | 280 |
| Whisper base, int8, whole buffer | 39.2% | 462 |
| **Whisper base, int8, speech span only (shipped)** | **36.5%** | **407** |

12 German lines (Thorsten voice) with a second of line noise before and after, as the turn's
buffer holds it. Most remaining "errors" are numbers written as digits ("0176" for "null eins
sieben sechs"), which the number parser reads correctly. Trimming the buffer to its speech span
stopped Whisper repeating itself on silence ("mein name ist ... mein name ist ...").

## End of turn

`dcr train-turn` on `src/dcr/turn/corpus/` (en and de): validation on 388 prefixes of lines the
model never saw, 93 of them finished turns.

| Threshold | Finished turns recognised | Unfinished turns cut off |
|---:|---:|---:|
| 0.35 (speculate) | 94.6% | 38.0% |
| 0.55 (answer) | 72.0% | 14.6% |
| 0.75 | 40.9% | 3.4% |

AUC 0.893. A turn below the answer threshold is still answered after 1.4 s of silence (2.6 s
while a number is half dictated); a speculative start that turns out wrong costs only compute.

## Echo cancellation

Partitioned-block frequency-domain adaptive filter, 160 ms path, 20 ms blocks
(`tests/test_audio.py`, on coloured, syllable-modulated noise standing in for speech): with echo
paths of 40, 90 and 130 ms at -24, -18 and -30 dB it removes more than 15 dB of echo over the
second half of 8 s, before residual suppression; when the caller talks over the agent their
voice passes with less than 2 dB of loss and adaptation freezes. Before convergence (the first
second of a call) loud echo passes; the near-end gate (docs/adr/0003) is what keeps it from
pausing the agent.

## Serving

`dcr bench` (`reports/BENCH.json`), the NeMo streaming recogniser on one decoder thread, 16.8 s
of phone audio per stream.

| Streams | Decoded one at a time: CPU per audio second | Batched (`decode_streams`) | Streams one core carries, batched |
|---:|---:|---:|---:|
| 2 | 0.303 | 0.229 | 4.4 |
| 4 | 0.307 | 0.193 | 5.2 |
| 8 | 0.295 | 0.174 | 5.7 |

Batching makes the encoder run once per batch: 1.7x the calls per core at 8 streams.

What a turn decision waits for (`await sync()`: everything fed so far decoded), with calls
feeding audio at real time:

| Concurrent calls | max_batch 1: p50 / p95 | max_batch 8: p50 / p95 |
|---:|---:|---:|
| 1 | 0.5 / 51 ms | 0.4 / 50 ms |
| 2 | 25 / 97 ms | 6 / 75 ms |
| 4 | **585 / 760 ms** | **64 / 126 ms** |

At four calls the unbatched decoder needs 1.2 cores of work on one thread and falls behind, so
every turn decision would wait over half a second. Batched, it keeps up. A pod's capacity is set
here (and `DCR_MODEL_PROVIDER=cuda` moves it to a GPU).

Speech synthesis, one short clause ("Which day would you like?"), Piper on CPU: 127 ms to the
whole clause alone; 157 ms median with 2 at once and 256 ms with 4 (slowest 420 ms). The end-of-turn model costs 36 µs per decision.

## LLM providers

The router's own log over every dev call, simulated providers with an 8% slow tail of +1.2 s
(`reports/eval_dev.json`, calls in `data/calls.sqlite`):

| | requests | first token p50 | p90 | p99 | max |
|---|---:|---:|---:|---:|---:|
| hedged after 450 ms (shipped) | 59 | 371 ms | 788 ms | 959 ms | 1,048 ms |
| no hedging | 59 | 375 ms | 944 ms | 1,818 ms | 2,053 ms |

Hedging halves the tail and leaves the median alone. On caller-side reply times the dev set has
too few slow requests (about 4 of 50 replies) for the difference to be significant.
