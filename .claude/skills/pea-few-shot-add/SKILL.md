---
name: pea-few-shot-add
description: Add a new few-shot extraction example to configs/extraction_examples.yaml following the project's pinning + rationale conventions. Use when the user wants to fix a recurring misclassification pattern by giving the LLM a concrete worked example, or when working through followup items #13/#14 (tier-2 examples, UG/DZ ground truth). Triggers on phrases like "add a few-shot example", "new gold case", "tier-2 example", "ground-truth example".
---

# pea-few-shot-add

Adds an example to `configs/extraction_examples.yaml` (or the matching domain file) without breaking the pinning contract or the country balance.

## When to use

- A recurring misclassification pattern shows up across runs.
- Followup items #13 and #14 (`tier-2 examples`, UG/DZ ground truth, Algeria bilingual) — these are explicitly waiting on this skill's output.
- Adding boundary negatives (e.g. "police-attacked peaceful march stays `demonstration_march`, not `riot`").

## Inputs to ask the user before drafting

1. Which domain? (`protest` → `extraction_examples.yaml`; `drone` → `drone_extraction_examples.yaml`; `ve` → `violent_extremism_extraction_examples.yaml`)
2. What's the disambiguating signal? (the *one* thing you want the LLM to learn from this example)
3. Country? Must be one we actually crawl: `NG | ZA | UG | DZ`. Reject others unless the user has a reason.
4. Is this paraphrased / synthetic, or a real article? Paraphrase real articles — don't ship copyrighted text.

## Procedure

1. **Read the existing file** and the template at `configs/extraction_examples_NEW_template.yaml`. Pick the next free `ex_NN` ID.

2. **Draft the example** following the structural contract (every example must have these keys):

   ```yaml
   - id: ex_NN
     pinned: true
     description: "<one-line summary, names the disambiguating signal>"
     country: "<NG|ZA|UG|DZ>"
     article_snippet: |
       <paraphrased text — make the disambiguating signal lexically explicit>
     extracted_events:
       - event_type: <type or [] for negative example>
         event_date: "YYYY-MM-DD"
         country: "<full name>"
         city: "<city or null>"
         claims: ["..."]
         confidence: "high|medium|low"
     rationale: |
       <why this is the right answer — names the rule the LLM should learn>
   ```

   For negative examples (`extracted_events: []`), the `rationale` must explain *which* of the 8 event types the article superficially resembles and why it's disqualified.

3. **Validate YAML loads:**

   ```bash
   venv/bin/python -c "
   import yaml
   d = yaml.safe_load(open('configs/extraction_examples.yaml'))
   print(f'examples: {len(d[\"examples\"])}, pinned: {sum(1 for e in d[\"examples\"] if e.get(\"pinned\"))}')
   "
   ```

4. **Check country balance.** Pull the country distribution after adding:

   ```bash
   venv/bin/python -c "
   import yaml, collections
   d = yaml.safe_load(open('configs/extraction_examples.yaml'))
   print(collections.Counter(e.get('country','?') for e in d['examples']))
   "
   ```

   Per followup #14, we want at least one ground-truth example per cron-target country. Flag if any of NG/ZA/UG/DZ has zero pinned examples.

5. **Token budget check.** Few-shot context is ~6k tokens per `CLAUDE.md`. Each new example adds ~1.5–2k. After adding:

   ```bash
   venv/bin/python -c "
   from src.acquisition.extractor import _build_few_shot_examples
   s = _build_few_shot_examples()
   print(f'few-shot tokens (rough): {len(s)//4}')
   "
   ```

   If you cross 10k, propose unpinning an older / less-impactful example rather than adding unconditionally.

6. **Run the canary** to confirm the example didn't regress unrelated extractions. Invoke `pea-canary-run`.

7. **If this closes a followup item**, update `.claude/followups.md` to mark the item done — don't leave stale TODOs for completed work (the rule the new `.claude/README.md` just added).

## Guard rails

- **Don't add unpinned examples** without explaining to the user why pinning is off — the system was designed assuming all examples are pinned.
- **Don't include real article text** verbatim. Paraphrase. The codebase has no copyright clearance pipeline.
- **Don't add a 4th example for a country that already has 2** until the under-represented countries are at 1+. The geography balance matters more than the per-type balance.

## Related

- `configs/extraction_examples_NEW_template.yaml` — the canonical scaffold.
- `.claude/followups.md` items #13, #14 — what's currently queued.
- `pea-canary-run` — verification.
