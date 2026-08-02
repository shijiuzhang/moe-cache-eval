# Event-atomic toy trace

This executable example contains 3 layers, 4 experts per layer, and 5 scheduler steps.
Each layer has capacity 2; the total cache capacity is 6 blocks.
LRU decisions occur only after every expert in an event has been served.

| step | layer | requested local experts | hits | misses |
|---:|---:|---|---:|---:|
| 0 | 0 | {0, 1} | 0 | 2 |
| 0 | 1 | {0, 1} | 0 | 2 |
| 0 | 2 | {0, 1} | 0 | 2 |
| 1 | 0 | {0, 2} | 1 | 1 |
| 1 | 1 | {0, 2} | 1 | 1 |
| 1 | 2 | {0, 2} | 1 | 1 |
| 2 | 0 | {0, 1} | 1 | 1 |
| 2 | 1 | {0, 1} | 1 | 1 |
| 2 | 2 | {0, 1} | 1 | 1 |
| 3 | 0 | {0, 3} | 1 | 1 |
| 3 | 1 | {0, 3} | 1 | 1 |
| 3 | 2 | {0, 3} | 1 | 1 |
| 4 | 0 | {0, 1} | 1 | 1 |
| 4 | 1 | {0, 1} | 1 | 1 |
| 4 | 2 | {0, 1} | 1 | 1 |

Hand-check: step 0 cold-loads two experts per layer (6 misses). At each later step, expert 0 remains resident and the second expert changes, giving one hit and one miss per layer (12 further misses).

Total: 30 accesses, 12 hits, 18 misses.
