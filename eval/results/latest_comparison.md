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
| Latency p50 (ms) | 12694 | 3113 | 4762 |
| Latency p95 (ms) | 14508 | 3290 | 6758 |
| Cost per query (USD) | $0.0159 | $0.0130 | $0.0151 |
