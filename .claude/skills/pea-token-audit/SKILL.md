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

## When to use

- Before merging a PR that touches `configs/protest_codebook.yaml`.
- Before merging a PR that adds to `configs/extraction_examples.yaml`.
- After a months-long stretch of small additions, as a periodic check.

## Procedure

1. **Measure the codebook context:**
   ```bash
   venv/bin/python -c "
   import yaml
   text = yaml.dump(yaml.safe_load(open('configs/protest_codebook.yaml')))
   chars = len(text)
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

3. **Measure the system-prompt total:**
   ```bash
   venv/bin/python -c "
   from src.acquisition.extractor import SYSTEM_PROMPT
   chars = len(SYSTEM_PROMPT)
   tokens = chars // 4
   print(f'system_prompt total (incl. codebook): {chars} chars / ~{tokens} tokens')
   "
   ```

4. **Compare to budget:**

   | Component | Budget | Warn at | Block at |
   |---|---|---|---|
   | Codebook context | 22k | 25k | 30k |
   | Few-shot examples | 6k | 10k | 14k |
   | System prompt (total) | 29k | 35k | 42k |
   | Per-call input p95 | 40k | 50k | 60k |

5. **For a precise per-call measurement**, run a single extraction with `logging.DEBUG` and watch for the `input_tokens` line from `_call_azure`.

6. **If over warn threshold**, propose cuts:
   - Codebook: look for duplicated `negative_examples` or `african_context` overlapping `disqualify_immediately`.
   - Few-shot: unpin lowest-impact example rather than deleting.

7. **If over block threshold**, refuse to merge.

## Caching offset

The system-prompt prefix (~29k tokens) is cached by Azure; cached tokens billed at 50%. Effective cost per subsequent call: ~17.5k cached + article. Don't use this as license to bloat.

## Guard rails

- **Token counts are rough** (`chars // 4`). Use `tiktoken` for accuracy if needed.
- **Don't optimise tokens at the cost of recall.**
- **Per-domain budgets differ.** This skill defaults to protest.

## Related

- `CLAUDE.md` § "Extraction Quality Architecture".
- `pea-codebook-edit` — should call this as a gate.
- `pea-few-shot-add` — already does a token check.
