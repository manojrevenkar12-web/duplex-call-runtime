# Evaluation: set1 set

12 simulated calls per configuration, scored from the caller's side of the line.

| | full |
|---|---:|
| Task success | 4/12 |
| Time to first audio, p50 (ms) | 1517.3 |
| Time to first audio, p90 (ms) | 2270.8 |
| vs full: median difference, 95% CI (ms) | - |
| Takeovers in mid-sentence pauses | 0% of 6 |
| Interruptions stopped within 1.5 s | 1/1 |
| Interruption stop time, p50 (ms) | 980.0 |
| Backchannels that stopped the agent | 0/3 |
| False stops (echo, noise) | 0 |
| Transcript WER | 0.273 |
| Requests hedged to the second provider | 27 |

## Per call (full configuration)

| Scenario | Task | Replies (ms) | Pause takeovers | Interrupt stop (ms) | False stops |
|---|---|---|---|---|---:|
| de-am-dienstag-faerben-paare | False | 1459, 1693, 1522, 3315, 1774 | 0/0 | - | 0 |
| de-morgen-bart-korrektur-nummer | False | 1885, 1493, 1548, 2252, 2318, 1765 | 0/0 | None | 0 |
| de-samstag-belegt-laerm | False | 1515, 1653, 1826, 1681, 998 | 0/1 | - | 0 |
| de-uebermorgen-halb-drei | False | 1848, 1819, 2249, 3296, 1346 | 0/1 | - | 0 |
| en-ask-for-person | True | 1406, 1766, 1572 | 0/0 | - | 0 |
| en-car-speakerphone-thursday-late | False | 1005, 1339, 1569, 1571, 1519 | 0/1 | - | 0 |
| en-fourth-colour-double | False | 1360, 1912, 1123, 1496, 1273 | 0/1 | - | 0 |
| en-hours-question-backchannel | True | 1045, 1511, 908 | 0/0 | - | 0 |
| en-interrupt-change-time | True | 1035, 1300, 1014, 1233, 2313, 1278 | 0/0 | 980.0 | 0 |
| en-next-friday-haircut | False | 951, 1928, 1557, 1122, 1308 | 0/1 | - | 0 |
| en-taken-saturday-slot | False | 2418, 1995, 1374, 3399, 953 | 0/0 | - | 0 |
| en-tomorrow-beard-card-pauses | True | 1128, 1558, 1113, 1500, 1424 | 0/1 | - | 0 |

## Calls that failed their expectation

- `de-am-dienstag-faerben-paare` (full): false stops 0, WER 16/26 words
- `de-morgen-bart-korrektur-nummer` (full): false stops 0, WER 26/40 words
- `de-samstag-belegt-laerm` (full): false stops 0, WER 25/33 words
- `de-uebermorgen-halb-drei` (full): false stops 0, WER 19/37 words
- `en-car-speakerphone-thursday-late` (full): false stops 0, WER 8/39 words
- `en-fourth-colour-double` (full): false stops 0, WER 4/42 words
- `en-next-friday-haircut` (full): false stops 0, WER 5/43 words
- `en-taken-saturday-slot` (full): false stops 0, WER 6/44 words
