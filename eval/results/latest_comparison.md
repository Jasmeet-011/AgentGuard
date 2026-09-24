# Latest comparison

## dev

**PRELIMINARY: the golden set is incomplete (fewer verified entries than the minimum), so these numbers are not headline numbers.**

| Metric | baseline | dense | hybrid |
|---|---|---|---|
| Questions | 2 answerable, 0 unanswerable, 0 policy | 2 answerable, 0 unanswerable, 0 policy | 2 answerable, 0 unanswerable, 0 policy |
| Retrieval recall@k | 100.0% | 100.0% | 100.0% |
| Answer correctness | 100.0% | 100.0% | 100.0% |
| Faithfulness | 100.0% | 100.0% | 100.0% |
| Invalid citation rate | 0.0% | 0.0% | 0.0% |
| Correct refusal rate (unanswerable) | n/a | n/a | n/a |
| False refusal rate (answerable) | 0.0% | 0.0% | 0.0% |
| Policy block rate (any refusal) | n/a | n/a | n/a |
| Policy block rate (reason = policy) | n/a | n/a | n/a |
| Latency p50 (ms) | 6989 | 3116 | 4773 |
| Latency p95 (ms) | 8621 | 3298 | 6772 |
| Cost per query (USD, pipeline only) | $0.0159 | $0.0130 | $0.0151 |
| Eval cost per question (USD, judge) | $0.0318 | $0.0124 | $0.0162 |
