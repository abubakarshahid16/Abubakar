# Answer quality: techniques worth testing (order 189, part A)

One page. A "gain" below is what the cited paper or vendor reports on ITS task;
none is measured on our answers yet. Part B (`eval/answer_quality/`) is how we
measure it, on invented sheets only. A technique is kept only if it scores the
same or better on every measure there and never costs citation quality or the
0-false-Meets rule.

| # | Technique | Source | Reported gain (their task) | Fit for us |
|---|---|---|---|---|
| 1 | **Quote first, then write** (the model copies the verbatim sentence it relies on before each claim; code already checks quotes) | ALCE citation prompting, [Gao et al. 2023](https://arxiv.org/pdf/2305.14627): even the best models lack full citation support about half the time on ELI5 | Not a number: it is the measured gap this targets | Best fit: our verifier already rejects a quote not in the source |
| 2 | **Prune the context to the sentences that matter** (drop passage sentences that do not touch the question) | Provence, [ICLR 2025](https://iclr.cc/virtual/2025/poster/29557); [Kapa write-up](https://www.kapa.ai/blog/how-we-prune-rag-context) (vendor: about two thirds of chunks dropped at about 96% recall) | Vendor-reported, not peer reviewed | Helps the 4b model on CPU (less to read); risk: dropping the one qualifier sentence, so keep the sentence before and after |
| 3 | **Put the best passage first or last, never in the middle** | [Lost in the Middle](https://arxiv.org/pdf/2307.03172): accuracy is highest at the start or end of the context and falls in the middle | U-shaped curve, no single number | Cheap, no model change; `answer._holding_first` already does part of it |
| 4 | **Self-consistency, narrow form** (3 samples, keep only claims that appear in at least 2) | [Wang et al. 2022](https://arxiv.org/pdf/2203.11171): +17.9 points on GSM8K in the final version | Maths reasoning, not citation answers | Costs 3x time on CPU; try last, only for the figure sentences |
| 5 | **Short reasoning step before the answer** | Same family as 4 | Mixed on small models | Test only; never show the reasoning, never let it add a figure |

## How part B scores (names from [Ragas](https://docs.ragas.io/en/v0.3.8/concepts/metrics/available_metrics/noise_sensitivity/) and ALCE)
- **Faithfulness**: share of the answer's claims whose quote is in the passage it cites (code, no judge model).
- **Response relevancy**: share of the expected facts of the question present; none of the forbidden ones.
- **Noise sensitivity**: answers re-asked with extra irrelevant passages; share of claims that change or turn wrong (lower is better).
- **Citation quality (ALCE style)**: recall (every claim cites) and precision (each cited passage holds the claim).
Ragas and ALCE score these with a judge model or an NLI model. We use code checks only (verbatim quote, figure and unit, clause), so our numbers are stricter on figures and cruder on meaning, and are not comparable to published scores.
