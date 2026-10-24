# Evaluation: dev set

10 simulated calls per configuration, scored from the caller's side of the line.

| | full | silence_endpoint | no_speculation | no_echo_cancel | no_hedging | pause_on_barge_in |
|---|---:|---:|---:|---:|---:|---:|
| Task success | 3/10 | 3/10 | 4/10 | 5/10 | 4/10 | 3/10 |
| Time to first audio, p50 (ms) | 1485.1 | 1824.1 | 1674.5 | 1435.0 | 1482.8 | 1355.0 |
| Time to first audio, p90 (ms) | 2538.9 | 2223.6 | 2701.8 | 2359.7 | 2872.2 | 2304.3 |
| vs full: median difference, 95% CI (ms) | - | +339.0 [+68.9, +445.8] | +189.4 [-301.7, +375.5] | -50.1 [-412.1, +211.9] | -2.3 [-332.8, +170.1] | -130.1 [-394.6, +205.7] |
| vs full: 90th percentile difference, 95% CI (ms) | - | -315.3 [-1416.5, +654.5] | +162.9 [-1148.2, +1603.5] | -179.2 [-1371.5, +1629.3] | +333.3 [-1128.8, +1441.6] | -234.6 [-1521.8, +1458.5] |
| Takeovers in mid-sentence pauses | 0% of 3 | 0% of 3 | 0% of 3 | 0% of 3 | 0% of 3 | 0% of 3 |
| Interruptions stopped within 1.5 s | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| Interruption stop time, p50 (ms) | 880.0 | 950.0 | 900.0 | 1030.0 | 950.0 | 470.0 |
| Backchannels that stopped the agent | 0/1 | 0/1 | 0/1 | 0/1 | 0/1 | 1/1 |
| False stops (echo, noise) | 0 | 0 | 0 | 19 | 0 | 0 |
| Transcript WER | 0.216 | 0.199 | 0.213 | 0.376 | 0.199 | 0.206 |
| Requests hedged to the second provider | 19 | 19 | 20 | 25 | 0 | 20 |

## Per call (full configuration)

| Scenario | Task | Wrong | Replies (ms) | Pause takeovers | Interrupt stop (ms) | False stops |
|---|---|---|---|---|---|---:|
| de-book-basic | False | no booking | 1937, 1893, 1479, 2559, 1766 | 0/1 | - | 0 |
| de-interrupt | False | no booking | 1779, 1785, 1700, 1680, 1981, 2508 | 0/0 | 800.0 | 0 |
| en-backchannel | True | - | 916, 1481 | 0/0 | - | 0 |
| en-book-basic | True | - | 790, 946, 1393, 1268, 1203 | 0/1 | - | 0 |
| en-interrupt-correction | False | date, phone | 968, 1228, 1787, 3657, 1661, 1421 | 0/0 | 960.0 | 0 |
| en-loud-echo | False | phone | 850, 1485, 1287, 3852, 1403 | 0/0 | - | 0 |
| en-noisy-street | False | phone | 870, 1786, 1119, 3573, 1237 | 0/0 | - | 0 |
| en-number-pauses | False | no booking | 1683, 1237, 1065, 1038, 1703 | 0/1 | - | 0 |
| en-taken-slot | False | no booking | 1614, 1754, 1464, 3388, 1458 | 0/0 | - | 0 |
| en-transfer | True | - | 1767 | 0/0 | - | 0 |

## Calls that failed their expectation

- `de-book-basic` (full): wrong no booking; transcript WER 16/35 words
- `de-interrupt` (full): wrong no booking; transcript WER 22/33 words
- `en-interrupt-correction` (full): wrong date, phone; transcript WER 5/36 words
- `en-loud-echo` (full): wrong phone; transcript WER 4/28 words
- `en-noisy-street` (full): wrong phone; transcript WER 5/31 words
- `en-number-pauses` (full): wrong no booking; transcript WER 1/32 words
- `en-taken-slot` (full): wrong no booking; transcript WER 4/29 words
- `de-book-basic` (silence_endpoint): wrong no booking; transcript WER 15/35 words
- `de-interrupt` (silence_endpoint): wrong no booking; transcript WER 21/33 words
- `en-interrupt-correction` (silence_endpoint): wrong date, phone; transcript WER 6/36 words
- `en-loud-echo` (silence_endpoint): wrong phone; transcript WER 4/28 words
- `en-noisy-street` (silence_endpoint): wrong name; transcript WER 3/31 words
- `en-number-pauses` (silence_endpoint): wrong time, name; transcript WER 3/32 words
- `en-taken-slot` (silence_endpoint): wrong no booking; transcript WER 2/29 words
- `de-interrupt` (no_speculation): wrong no booking; transcript WER 23/33 words
- `en-interrupt-correction` (no_speculation): wrong date, phone; transcript WER 4/36 words
- `en-loud-echo` (no_speculation): wrong name, phone; transcript WER 4/28 words
- `en-noisy-street` (no_speculation): wrong name; transcript WER 4/31 words
- `en-number-pauses` (no_speculation): wrong no booking; transcript WER 3/32 words
- `en-taken-slot` (no_speculation): wrong no booking; transcript WER 3/29 words
- `de-book-basic` (no_echo_cancel): wrong name, phone; transcript WER 17/35 words
- `de-interrupt` (no_echo_cancel): wrong no booking; transcript WER 18/33 words
- `en-book-basic` (no_echo_cancel): wrong no booking; transcript WER 8/37 words
- `en-interrupt-correction` (no_echo_cancel): wrong date, phone; transcript WER 12/36 words
- `en-loud-echo` (no_echo_cancel): wrong no booking; transcript WER 36/28 words
- `de-book-basic` (no_hedging): wrong no booking; transcript WER 18/35 words
- `de-interrupt` (no_hedging): wrong no booking; transcript WER 20/33 words
- `en-interrupt-correction` (no_hedging): wrong date, phone; transcript WER 6/36 words
- `en-loud-echo` (no_hedging): wrong phone; transcript WER 4/28 words
- `en-noisy-street` (no_hedging): wrong name; transcript WER 3/31 words
- `en-number-pauses` (no_hedging): wrong no booking; transcript WER 2/32 words
- `de-book-basic` (pause_on_barge_in): wrong phone; transcript WER 16/35 words
- `de-interrupt` (pause_on_barge_in): wrong no booking; transcript WER 22/33 words
- `en-interrupt-correction` (pause_on_barge_in): wrong phone; transcript WER 5/36 words
- `en-loud-echo` (pause_on_barge_in): wrong name, phone; transcript WER 4/28 words
- `en-noisy-street` (pause_on_barge_in): wrong name; transcript WER 2/31 words
- `en-number-pauses` (pause_on_barge_in): wrong no booking; transcript WER 2/32 words
- `en-taken-slot` (pause_on_barge_in): wrong no booking; transcript WER 3/29 words
