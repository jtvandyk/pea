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

6. **Add to `_REQUIRED_CONFIGS`** in `pipeline.py`:
   ```python
   _REPO_ROOT / "configs" / "<domain>_codebook.yaml",
   _REPO_ROOT / "configs" / "<domain>_extraction_examples.yaml",
   ```

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

10. **Document the new domain** in `CLAUDE.md` and `.claude/followups.md`.

## The violent_extremism precedent

`configs/violent_extremism_codebook.yaml` exists but `violent_extremism` is
**intentionally not registered** in `DOMAIN_CONFIGS`. Recall must be ≥60%
before registration.

## Guard rails

- **Don't register a domain without examples.**
- **Don't reuse the protest GDELT query.**
- **Don't enable a research-prototype domain in cron.**
- **Token budget compounds.** Run `pea-token-audit` after registering.
- **Don't skip the test.**

## Related

- `src/acquisition/pipeline.py` § `DOMAIN_CONFIGS` and `_validate_domains`.
- `pea-codebook-edit` — for changes *within* a registered domain.
- `pea-few-shot-add` — for the few-shot examples step.
- `pea-token-audit` — combined-domain budget check.
- `pea-validate` — gate before promoting from research-prototype to cron.
