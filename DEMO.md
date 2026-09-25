# Demo run-of-show (12 minutes)

## Pre-call checklist

- [ ] Open the app 10 minutes early: `make demo`, then open http://localhost:8501.
- [ ] Ask one warm-up question (question 1). The first query loads the models and takes 15 to 20 s;
      after that queries take 2 to 8 s.
- [ ] Sidebar defaults: hybrid_rerank, Verifier OFF, Query decomposition ON, Policy guard ON.
- [ ] Close other apps and browser tabs. Turn on Do Not Disturb.
- [ ] Have `eval/results/latest_comparison.md` open in case the Evals tab misbehaves.
- [ ] Backup: the screen recording. `make demo` also works with the network off (answers come from
      the LLM cache).
- [ ] The live, uncached call is a free-text question, "What fees does Facet charge?", on the
      default toggles (Q2 slot below). Do not run it before the call, or it will be cached.

## Run of show

| Time | Segment | What to do and say |
|---|---|---|
| 0:00 | Problem | Advisors read hundreds of pages of ADV filings. An LLM that invents a fee is worse than useless. I built a baseline, measured it, added components one at a time, and kept only what moved the numbers. |
| 1:00 | Q1: simple | Ask "What is Savvy's minimum account size?" Click citation 1: firm, item, page, exact source text. Point out that "generally" and "negotiable" are kept from the source. |
| 2:30 | Q2: Vanguard, and the live call | Ask "Has Vanguard's advisory business been subject to any SEC enforcement action?" Then pick the free-text option, type "What fees does Facet charge?" and ask. This is the live, uncached call: say so, and point at the trace panel (no "cached" tags, real per-node time and cost). Click one citation. |
| 4:00 | Q3: decomposition | Ask "What does Wealthfront charge on an Automated Investing Account, and has it faced any SEC enforcement action?" Show the two sub-queries and both citations (Item 5 and Item 9). Switch **Query decomposition OFF**, ask again: fee only, the SEC part is silently gone. Switch it back ON. |
| 6:00 | Q4: comparison | Ask "How does Wealthfront's annual fee on an Automated Investing Account compare with Betterment's Digital wrap fee?" Two firms, each sentence cites its own firm. |
| 7:00 | Q5: unanswerable | Ask "What were Fisher Investments' client returns in 2025?" It refuses: the filing does not say. Reason: insufficient_evidence. |
| 7:45 | Q6 and Q7: policy guard | Ask "What is the home address of Atwood Financial Planning's founder?": blocked, category pii_request, no retrieval, about a second. Then "What is Atwood Financial Planning's business address?": allowed and answered from the cover page. Similar words, different intent. |
| 8:45 | Evals tab | Test headline first: baseline vs full, n on every card, held out and run once. Then the dev table and the chart. Then the policy probes. Then the failures browser: open q015 and say plainly that it is a retrieval miss the recall metric did not catch. |
| 11:15 | What is next | Bigger golden set, human-labelled judge calibration, run-to-run variance, real advisor documents. Name two limitations yourself: 8 test questions, and the judge is the same model family. |
| 12:00 | Stop, questions | |

## Toggles to flip

- None for the live call: the free-text question runs on the default toggles.
- Verifier: leave OFF. Talk about it from the eval numbers (below); flipping it on would be an
  uncached, unrehearsed call.
- Query decomposition: OFF for Q3, then ON.
- Leave retrieval mode and Policy guard alone. (Optional, not rehearsed: Policy guard OFF on Q6
  shows the unguarded pipeline answering the address question.)

## Three numbers to say out loud

1. **100% faithfulness** on dev and test: every answer sentence was judged supported by its cited
   chunk. (Small samples: 8 and 4 answerable questions.)
2. **Policy block rate 66.7% to 100%** on dev with 0% false blocks; 4 of 4 blocked and 0 of 4
   falsely blocked on the adversarial probes. That is what the guard bought.
3. **Verifier: no measured change for +2.1 s and +$0.0065 per query**, so it is off by default. This
   is the "kept only what moved the numbers" line. It is a toggle in the sidebar; say what it does
   (checks each sentence against its cited chunks) and that it removed nothing in the eval.

Test headline if asked: full and baseline are identical on quality (correctness 87.5%, faithfulness
100%); full costs 7.9 s vs 5.0 s and $0.0192 vs $0.0164 per query.

## If something breaks

- Evals tab blank or slow: read `eval/results/latest_comparison.md` instead.
- API errors: questions 1 to 7 with the default toggles are cached; the free-text Facet question is
  the only one that needs the network. Skip it and say so, or swap in a cached demo question.
- Models slow on the first query: that is the one-time load; keep talking through the architecture.
