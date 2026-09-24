# Latest comparison

## dev

| Metric | +verifier | baseline | dense | hybrid |
|---|---|---|---|---|
| Questions | 8 answerable, 3 unanswerable, 3 policy | 8 answerable, 3 unanswerable, 3 policy | 8 answerable, 3 unanswerable, 3 policy | 8 answerable, 3 unanswerable, 3 policy |
| Retrieval recall@k | 87.5% | 87.5% | 87.5% | 87.5% |
| Answer correctness | 90.0% | 90.0% | 90.0% | 90.0% |
| Faithfulness | 100.0% | 100.0% | 100.0% | 100.0% |
| Invalid citation rate | 0.0% | 0.0% | 0.0% | 0.0% |
| Correct refusal rate (unanswerable) | 100.0% | 100.0% | 100.0% | 100.0% |
| False refusal rate (answerable) | 0.0% | 0.0% | 0.0% | 0.0% |
| Policy block rate (any refusal) | 66.7% | 66.7% | 66.7% | 66.7% |
| Policy block rate (reason = policy) | 66.7% | 66.7% | 66.7% | 66.7% |
| Latency p50 (ms) | 6967 | 4981 | 2661 | 2703 |
| Latency p95 (ms) | 10893 | 7816 | 7439 | 6879 |
| Cost per query (USD, pipeline only) | $0.0229 | $0.0164 | $0.0163 | $0.0178 |
| Eval cost per question (USD, judge) | $0.0093 | $0.0093 | $0.0091 | $0.0100 |
