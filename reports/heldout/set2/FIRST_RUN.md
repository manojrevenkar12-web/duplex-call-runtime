# Evaluation: set2 set

12 simulated calls per configuration, scored from the caller's side of the line.

| | full |
|---|---:|
| Task success | 5/12 |
| Time to first audio, p50 (ms) | 1579.8 |
| Time to first audio, p90 (ms) | 2435.3 |
| vs full: median difference, 95% CI (ms) | - |
| Takeovers in mid-sentence pauses | 0% of 7 |
| Interruptions stopped within 1.5 s | 2/2 |
| Interruption stop time, p50 (ms) | 720.0 |
| Backchannels that stopped the agent | 0/5 |
| False stops (echo, noise) | 0 |
| Transcript WER | 0.336 |
| Requests hedged to the second provider | 24 |

## Per call (full configuration)

| Scenario | Task | Wrong | Replies (ms) | Pause takeovers | Interrupt stop (ms) | False stops |
|---|---|---|---|---|---|---:|
| de-babble-echo-bart-abend | False | no booking | 1889, 1429, 1425 | 0/1 | - | 0 |
| de-dienstag-faerben-interrupt-day | False | no booking | 2242, 1789, 1670, 2167, 2073, 1451 | 0/1 | 440.0 | 0 |
| de-sonntag-frage-kein-termin | True | - | 2080, 1976, 1592 | 0/0 | - | 0 |
| de-uebermorgen-halb-drei | True | - | 2283, 1794, 1652, 2101, 1734 | 0/1 | - | 0 |
| en-ask-for-stylist | True | - | 1182, 1046 | 0/0 | - | 0 |
| en-car-noise-thursday-late | False | no booking | 5258, 1386, 1267 | 0/0 | - | 0 |
| en-fourth-colour-double-triple | False | no booking | 1042, 1708, 907, 1056, 971 | 0/1 | - | 0 |
| en-hours-services-backchannel | True | - | 1150, 1272, 874 | 0/0 | - | 0 |
| en-next-week-fri-haircut | False | no booking | 2197, 1406, 921, 3371, 966 | 0/1 | - | 0 |
| en-readback-interrupt-time | False | phone | 2478, 1438, 3485, 1851, 1424 | 0/0 | 1000.0 | 0 |
| en-sat-taken-slot | True | - | 1794, 2549, 1344, 1716, 1567 | 0/1 | - | 0 |
| en-speakerphone-echo-beard | False | name | 1168, 1481, 1158, 1456, 2430 | 0/1 | - | 0 |

## Calls that failed their expectation

- `de-babble-echo-bart-abend` (full): wrong no booking; transcript WER 24/26 words
- `de-dienstag-faerben-interrupt-day` (full): wrong no booking; transcript WER 23/36 words
- `en-car-noise-thursday-late` (full): wrong no booking; transcript WER 30/36 words
- `en-fourth-colour-double-triple` (full): wrong no booking; transcript WER 7/37 words
- `en-next-week-fri-haircut` (full): wrong no booking; transcript WER 8/43 words
- `en-readback-interrupt-time` (full): wrong phone; transcript WER 8/43 words
- `en-speakerphone-echo-beard` (full): wrong name; transcript WER 5/30 words
