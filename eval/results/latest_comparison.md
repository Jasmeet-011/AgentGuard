# Latest comparison

## dev

| Metric | +decompose | +policy | +verifier | +verifier+decompose | baseline | dense | hybrid |
|---|---|---|---|---|---|---|---|
| Questions | 8 answerable, 3 unanswerable, 3 policy | 8 answerable, 3 unanswerable, 3 policy | 8 answerable, 3 unanswerable, 3 policy | 8 answerable, 3 unanswerable, 3 policy | 8 answerable, 3 unanswerable, 3 policy | 8 answerable, 3 unanswerable, 3 policy | 8 answerable, 3 unanswerable, 3 policy |
| Retrieval recall@k | 100.0% | 100.0% | 87.5% | 100.0% | 87.5% | 87.5% | 87.5% |
| Answer correctness | 100.0% | 100.0% | 90.0% | 100.0% | 90.0% | 90.0% | 90.0% |
| Faithfulness | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| Invalid citation rate | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| Correct refusal rate (unanswerable) | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| False refusal rate (answerable) | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| Policy block rate (any refusal) | 66.7% | 100.0% | 66.7% | 66.7% | 66.7% | 66.7% | 66.7% |
| Policy block rate (reason = policy) | 66.7% | 100.0% | 66.7% | 66.7% | 66.7% | 66.7% | 66.7% |
| Latency p50 (ms) | 5710 | 8330 | 7171 | 7797 | 5088 | 2664 | 2811 |
| Latency p95 (ms) | 9536 | 14864 | 10970 | 13652 | 8046 | 7447 | 6882 |
| Cost per query (USD, pipeline only) | $0.0179 | $0.0226 | $0.0229 | $0.0246 | $0.0164 | $0.0163 | $0.0178 |
| Eval cost per question (USD, judge) | $0.0092 | $0.0092 | $0.0093 | $0.0092 | $0.0093 | $0.0091 | $0.0100 |
