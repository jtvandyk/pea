---
name: pea-domain-add
description: Wire a new event domain (e.g. drone, violent_extremism, future custom domain) into the PEA pipeline by templating the codebook YAML, the few-shot examples YAML, the DOMAIN_CONFIGS entry in pipeline.py, and the matching tests. Use when the user wants to extend extraction to a new event class beyond protest. Triggers on phrases like "add a new domain", "wire a domain", "register drone in DOMAIN_CONFIGS", "add a codebook for X".
---

# pea-domain-add

Templates the four touchpoints required to register a new domain. The drone
domain (registered) and `violent_extremism` (intentionally *not* registered)
are the canonical precedents.

## When to use

- Adding a new event class to the multi-domain pipeline.
- Promoting an existing research-prototype codebook (e.g. moving
  `violent_extremism` from intentionally-unregistered to registered).

**Do not use** for adding event types *within* an existing domain — that's
`pea-codebook-edit` instead.

## Touchpoints to wire

1. `configs/<domain>_codebook.yaml` — domain definitions, event types,
   disqualifiers, decision rules. Same structural shape as
   `protest_codebook.yaml`.
2. `configs/<domain>_extraction_examples.yaml` — 3+ pinned few-shot
   examples covering positive, negative, multi-event cases.
3. `src/acquisition/pipeline.py` — `DOMAIN_CONFIGS` dict + `_REQUIRED_CONFIGS`
   list + `_validate_domains` whitelist. Without these the pipeline silently
   runs the new domain with an empty system prompt (per the comment block
   above `_validate_domains`).
4. Tests — at minimum a smoke-test that `_validate_domains([new_domain])`
   doesn't raise, and that the codebook loads.

## Procedure

1. **Confirm the operator has the codebook content.** A new domain is a
   research-grade design problem, not a templating job. If they don't have
   the event-type taxonomy, halt — don't write a stub codebook.

2. **Pick a domain key.** Lowercase, snake_case, single word if possible:
   `drone`, `violent_extremism`, `cybercrime`. This becomes the dict key,
   the file prefix, and the CLI flag (`--domains <key>`).

3. **Create `configs/<domain>_codebook.yaml`** with the structural skeleton
   from `protest_codebook.yaml` § top-level keys. Required top-level keys:

   | Key | Purpose |
   |---|---|
   | `metadata` | version, codebook name, author, date |
   | `general_rules` | scope, what counts, what doesn't |
   | `minimum_criteria` | the bar an article must clear to extract |
   | `event_types` | the core taxonomy with definitions, examples, decision rules |
   | `non_events` | hard disqualifiers |
   | `confidence_guidance` | high / medium / low criteria |

   Drone has additional sections (`platform_classification`, `purpose_taxonomy`)
   that are domain-specific — add what's needed, don't shoehorn.

4. **Create `configs/<domain>_extraction_examples.yaml`** with at least 3
   pinned examples. Use the structural contract from `pea-few-shot-add`.
   Cover one positive, one negative, one boundary case.

5. **Wire `DOMAIN_CONFIGS` in `src/acquisition/pipeline.py`:**

   Find the existing dict (around line 128):
   ```python
   DOMAIN_CONFIGS: dict = {
       "protest": {...},
       "drone": {...},
   }
   ```

   Add the new entry:
   ```python
   "<domain>": {
       "codebook": _REPO_ROOT / "configs" / "<domain>_codebook.yaml",
       "examples": _REPO_ROOT / "configs" / "<domain>_extraction_examples.yaml",
       "query": "<space-separated keyword string for GDELT discovery>",
   },
   ```

   The `query` field is the GDELT discovery keyword set — what GDELT keyword
   query identifies articles likely to contain this domain's events. For
   drone it's `"drone UAV airstrike unmanned aircraft"`. Pick 4–8 strong
   signal words.

6. **Add to `_REQUIRED_CONFIGS`** in `pipeline.py`:
   ```python
   _REPO_ROOT / "configs" / "<domain>_codebook.yaml",
   _REPO_ROOT / "configs" / "<domain>_extraction_examples.yaml",
   ```
   This makes `_assert_required_configs()` fail-fast at startup if either
   file is missing in the container — the same mechanism that protects
   the protest configs.

7. **Add a test** in `tests/` that the new domain wires correctly:
   ```python
   def test_<domain>_domain_registered():
       from src.acquisition.pipeline import DOMAIN_CONFIGS, _validate_domains
       assert "<domain>" in DOMAIN_CONFIGS
       _validate_domains(["<domain>"])  # must not raise
       cfg = DOMAIN_CONFIGS["<domain>"]
       assert cfg["codebook"].exists()
       assert cfg["examples"].exists()
   ```

8. **Run quality checks:**
   ```bash
   python -m black src/ tests/
   python -m flake8 src/ tests/
   python -m pytest tests/ -q
   ```

9. **Run a canary against the new domain:**
   ```bash
   venv/bin/python -m src.acquisition.pipeline \
     --provider azure --countries ZA --days 14 \
     --max-articles 30 --domains <domain>
   ```

   Inspect `summary_*.json`. For a brand-new domain:
   - `total_events` should be > 0 (the domain has *some* signal in 14 days of GDELT for ZA).
   - `events_by_type` distribution should look reasonable, not all-one-type.
   - `failures_*.jsonl` should be empty or near-empty.

10. **Document the new domain:**
    - Add a section to `CLAUDE.md` under "Pipeline Stages" or a new
      "Supported Domains" section.
    - If the domain is research-prototype like drone, mark it explicitly
      and don't enable in cron until validation passes.
    - Add an entry to `.claude/followups.md` for any P2/P3 work the new
      domain inherits (token-budget audit, ground-truth examples per
      country, etc.).

## The violent_extremism precedent

`configs/violent_extremism_codebook.yaml` and the matching examples file
exist on disk but `violent_extremism` is **intentionally not registered**
in `DOMAIN_CONFIGS`. The comment block above `_validate_domains` explains
why: without ground-truth validation the codebook is research-only.

If the operator asks to register `violent_extremism`:
1. Verify ground-truth validation has been run (`pea-validate` against a
   gold dataset for the domain).
2. Recall must be ≥ 60% before registration.
3. Tell them this in advance — don't just register and hope.

## Guard rails

- **Don't register a domain without examples.** Empty `examples` field →
  prompt has no few-shot guidance → extractor produces protest-shaped
  output for the new domain (a real bug we've seen).
- **Don't reuse the protest GDELT query.** Each domain needs its own
  `query` field; reusing protest's pulls protest articles into the new
  domain's run.
- **Don't enable a research-prototype domain in cron.** Per `.claude/followups.md`
  #24, drone is acceptable for monitoring only. New domains start
  research-only and are promoted to cron after validation.
- **Token budget compounds.** Multi-domain runs (`--domains protest,drone`)
  load both codebooks per article. Run `pea-token-audit` after registering
  to make sure the combined budget is acceptable.
- **Don't skip the test.** A wired-but-broken domain will silently fall
  through `DOMAIN_CONFIGS.get(domain, {})` and run with no codebook —
  exactly the failure mode `_validate_domains` was added to prevent.

## Related

- `src/acquisition/pipeline.py` § `DOMAIN_CONFIGS` and `_validate_domains`
  — the mechanism this skill wires into.
- `pea-codebook-edit` — for changes *within* a registered domain.
- `pea-few-shot-add` — for the few-shot examples step (5).
- `pea-token-audit` — combined-domain budget check.
- `pea-validate` — gate before promoting from research-prototype to cron.
- `.claude/followups.md` #24 — drone is research-prototype today.
