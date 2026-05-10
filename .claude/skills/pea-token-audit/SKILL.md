---
name: pea-token-audit
description: Audit the per-extraction token budget (SYSTEM_PROMPT + few-shot examples + article) against the documented ~40k input target before merging codebook or example changes. Use to prevent codebook bloat from silently inflating per-article cost. Triggers on phrases like "audit prompt size", "check token budget", "extraction cost", "did the codebook bloat".
---

# pea-token-audit

Computes the current input-token footprint of an extraction call and compares
it to the documented budget in `CLAUDE.md` § "Extraction Quality Architecture":

- System prompt (codebook injection): ~22k tokens documented.
- Few-shot examples: ~6k tokens documented.
- Article body: ~4–5k tokens (variable, p95 input).
- **Total per-call input target: ~40k tokens.**

This is the dominant input-token cost driver. Drift here directly multiplies
spend across every article in every run.

## When to use

- Before merging a PR that touches `configs/protest_codebook.yaml`.
- Before merging a PR that adds to `configs/extraction_examples.yaml`.
- After a months-long stretch of small additions, as a periodic check.
- When the operator asks "is the prompt getting too big".

## Procedure

1. **Measure the codebook context:**
   ```bash
   venv/bin/python -c "
   from src.utils.codebook_manager import CodebookManager
   ctx = CodebookManager('configs/protest_codebook.yaml').get_prompt_context()
   chars = len(ctx)
   tokens = chars // 4  # rough
   print(f'codebook: {chars} chars / ~{tokens} tokens')
   "
   ```

2. **Measure the few-shot examples:**
   ```bash
   venv/bin/python -c "
   from src.acquisition.extractor import _build_few_shot_examples
   s = _build_few_shot_examples()
   chars = len(s)
   tokens = chars // 4
   print(f'few-shot: {chars} chars / ~{tokens} tokens')
   "
   ```

3. **Measure the static system-prompt scaffold** (the part before codebook injection):
   ```bash
   venv/bin/python -c "
   from src.acquisition.extractor import SYSTEM_PROMPT
   chars = len(SYSTEM_PROMPT)
   tokens = chars // 4
   print(f'system_prompt total (incl. codebook): {chars} chars / ~{tokens} tokens')
   "
   ```

4. **Compare to budget.** Use this rubric:

   | Component | Budget | Warn at | Block at |
   |---|---|---|---|
   | Codebook context | 22k | 25k | 30k |
   | Few-shot examples | 6k | 10k | 14k |
   | System prompt (total) | 29k | 35k | 42k |
   | Per-call input p95 | 40k | 50k | 60k |

5. **For a precise per-call measurement**, run a single extraction with logging:
   ```bash
   venv/bin/python -c "
   import json, logging
   logging.basicConfig(level=logging.DEBUG)
   from src.acquisition.extractor import extract_from_article
   art = {'title': 't', 'text': 'About 500 workers gathered outside.', 'url': 'https://example.com'}
   r = extract_from_article(art, provider='azure', model='gpt-5.4')
   print(json.dumps(r, default=str)[:200])
   "
   ```
   Watch for the prompt-caching log line written by `_call_azure` — it shows
   `input_tokens` for the actual call.

6. **If over the warn threshold**, propose specific cuts:
   - **Codebook:** look for duplicated `negative_examples` across types, or `african_context` rules that overlap `disqualify_immediately`.
   - **Few-shot:** unpin the oldest / lowest-impact example (`pinned: false`) rather than deleting; rotate based on observed misclassification frequency.
   - **System prompt:** check for verbose markdown headers or worked-example duplication.

7. **If over the block threshold**, refuse to merge. Open a followup to refactor before adding more.

## Caching offset

Per `CLAUDE.md` § "Extraction Quality Architecture", the system-prompt prefix
(~29k tokens) is identical across every article in a run. Azure auto-caches
when the prefix exceeds 1024 tokens; cached tokens are billed at 50%.

So effective cost per call is roughly:
- First call in a run: full 29k system + 6k few-shot + article.
- Subsequent calls: 29k × 0.5 + 6k × 0.5 + article = ~17.5k cached + article.

When you add to the codebook, the warm-cache cost grows half as fast as the
cold-cache cost. Don't use this as license to bloat — the cold cost still
hits at the start of every run.

## Guard rails

- **Token counts here are rough** (`chars // 4`). For accurate counts, use
  `tiktoken` against the model's actual encoding — but the rough version is
  enough for budget thresholds.
- **Don't optimise for tokens at the cost of recall.** A 23k codebook that
  catches 5 more event types per run is better than a 21k one that misses
  them. Validate quality after any cuts (`pea-canary-run`).
- **Per-domain budgets differ.** Drone and VE codebooks are smaller today;
  this skill defaults to protest. For other domains, edit the codebook path
  in step 1.

## Related

- `CLAUDE.md` § "Extraction Quality Architecture" — documented budget.
- `pea-codebook-edit` — the skill that should call this one as a gate.
- `pea-few-shot-add` — already does a token check; this skill formalises it.
