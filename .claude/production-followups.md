# Production Follow-ups — Remaining Priority Items

Working reference for items not landed in the two production-readiness commits
(`f1b2acc` B1-B5, `bdfa472` priority items #1-10). Items below are the rest of
the priority table from the May 7 review, refreshed against what's now in main.

**Ordering inside each priority tier is roughly impact / hour.**

---

## P2 — Operational hygiene + post-deploy quality work

### 11. Stop pushing `:latest` unconditionally from `docker.yml`

**Why it matters.** A bad image taints `:latest` until the next merge. Manual
rollback requires re-pushing an older SHA. With the new `verify` job in place,
this is less acute, but the pattern is still risky.

**Files.** `.github/workflows/docker.yml` (lines around the `docker tag … :latest`
+ `docker push :latest` steps for both pipeline and dashboard).

**Approach.** Drop the `:latest` push entirely. Reference images by SHA in
`infra/deploy.sh` (`az containerapp job update --image $ACR/pea-pipeline:$GITHUB_SHA`).
The `update-container-apps` job already runs after `build-and-push` and has the
SHA available — just propagate it instead of relying on `:latest`.

**Effort.** ~30 min. **Signal needed:** none — do this as part of the next CI cleanup.

---

### 12. Add image vulnerability scan in CI

**Why it matters.** `python:3.11-slim` accumulates CVEs weekly. We have zero
visibility today. A HIGH/CRITICAL kernel CVE in a base image will sit in
production until someone reads a CVE feed.

**Files.** `.github/workflows/docker.yml`.

**Approach.** Insert a `trivy image` step after `docker build` in both
`docker-build-test` and `build-and-push`:

```yaml
- name: Scan image for HIGH/CRITICAL CVEs
  uses: aquasecurity/trivy-action@master
  with:
    image-ref: pea-pipeline:test  # or the ACR-tagged SHA
    severity: HIGH,CRITICAL
    exit-code: 1
    ignore-unfixed: true
```

`ignore-unfixed: true` keeps the gate from failing on CVEs without an upstream
patch (we can't act on those anyway).

**Effort.** ~45 min including pinning a CI cadence we won't be paged by.

---

### 13. Tier-2 few-shot examples: standalone strike, cultural-celebration negative, peaceful-march-attacked negative

**Why it matters.** After Day 5 the highest-frequency misclassifications will
be:
- A strike that's **not** part of a multi-event article gets coded with the
  multi-event bias from `ex_03`.
- A cultural celebration with incidental political speeches gets coded as
  `demonstration_march`.
- A peaceful march that **police attack** gets upgraded to `confrontation` /
  `riot` even though codebook v2.4 says it stays `demonstration_march`.

**Files.** `configs/extraction_examples.yaml` — add `ex_09`, `ex_10`, `ex_11`.

**Pattern to follow.** The `ex_06`/`ex_07`/`ex_08` examples added in `bdfa472`
are the template. Each should:
- be paraphrased / synthetic (no copyright dependency on a real article)
- be `pinned: true`
- make the disambiguating signal **explicit** in the rationale field
- pick a country we actually crawl (NG / ZA / UG / DZ)

**Concrete sketch:**

| ID | Type | Country | Disambiguating signal |
|---|---|---|---|
| `ex_09` | `strike_boycott` (standalone) | South Africa | Mining-sector wage strike — explicit downing of tools, named union, no co-occurring events |
| `ex_10` | `[]` (negative) | Nigeria | Cultural festival with a politician giving a speech — primary purpose is celebration |
| `ex_11` | `demonstration_march` (police-attacked) | Uganda | Peaceful march; police fire teargas; **still demonstration_march, not riot** |

**Effort.** 1-2h to draft and YAML-validate.

---

### 14. UG and DZ ground-truth examples; Algeria bilingual stress test

**Why it matters.** After `ex_06`/`ex_07`/`ex_08` we have one UG and one DZ
example each, but they're paraphrased. A real ground-truth example from each
of the four cron-target countries (NG, ZA, UG, DZ) closes the geographic gap.
Algeria is the one that most stresses translation: French-language source body
with Arabic slogans embedded.

**Files.** `configs/extraction_examples.yaml`.

**Approach.** Wait for the first 7 days of real data, pick highest-confidence
events from each country, paraphrase to remove copyright issues, add. Reuse the
new `algeria_hirak` rules from codebook v2.4 to coach extractor on Hirak
specifics.

**Effort.** 2h after Day 7. **Signal needed:** wait for first week of data.

---

### 15. End-to-end LLM regression test in CI

**Why it matters.** `scripts/smoke_extract.py` runs at deploy time only.
A schema drift on the Foundry side (or a codebook change that breaks the
JSON shape we expect) won't be caught until the next deploy. CI should hit
the live endpoint on every PR.

**Files.** New `tests/integration/test_extract_live.py`. CI gating in
`.github/workflows/tests.yml`.

**Approach.**
- Pytest mark: `@pytest.mark.integration`
- Skip unless `AZURE_FOUNDRY_API_KEY` is set in CI secrets
- One canned protest article, one canned non-event — assert event count for
  each
- Add to `tests.yml`: a separate job that runs `pytest -m integration` only
  on push to main or when a `run-integration` label is set on the PR
- Cost: ~$0.01 per test run; cap at 2 articles

**Effort.** ~2h, but only if you want it on every push. Optional.

---

### 16. Deduplicator boundary tests

**Why it matters.** `CLAUDE.md` highlights three recent fixes to the
deduplicator (TF-IDF claims similarity, null-city merge, ±3 day window).
None of them are exercised by tests today. A regression that re-introduces
the null-city merge bug would silently degrade output quality.

**Files.** `tests/test_processing.py` — extend with three cases:

| Case | Setup | Expected |
|---|---|---|
| Null city, different events | Two events in same country, both `city=None`, different `claims` | Stay separate |
| Same city/day, different demands | Two events in Lagos same day, `claims_similarity` < 0.20 | Stay separate |
| Same city/day, similar demands | Two events in Lagos same day, `claims_similarity` ≥ 0.20 | Merge |

**Effort.** ~1.5h. Pure unit work, no infra needed.

---

### 17. Crash-atomic checkpoint append

**Why it matters.** Threading lock makes append thread-safe but not
crash-safe. SIGKILL during an open-append-flush sequence can leave a
truncated URL line. On resume that line won't match any URL exactly, so the
article gets re-extracted. One article per crash is small money but the
behavior is surprising and hard to debug if it ever does cluster.

**Files.** `src/acquisition/extractor.py:_write_checkpoint`.

**Approach.**

```python
def _write_checkpoint(url: str) -> None:
    if not checkpoint_path:
        return
    with _checkpoint_lock:
        # Read full state, append, atomic rename
        cp = Path(checkpoint_path)
        existing = cp.read_text() if cp.exists() else ""
        tmp = cp.with_suffix(cp.suffix + ".tmp")
        tmp.write_text(existing + url + "\n")
        os.replace(tmp, cp)  # atomic on POSIX
```

Cost: O(N) per append where N = lines in checkpoint. For 50k-article
backfills, this is non-trivial. Keep an in-memory mirror and write that out
to the tmpfile each time, instead of re-reading the file.

**Effort.** ~1h with tests. Lower priority than #11-#16.

---

### 18. End-to-end test of the multi-domain pipeline path

**New item — surfaced during follow-up work.** `bdfa472` and the multi-domain
follow-up commit added stage-context tagging to `run_pipeline_multi_codebook`
but there is **no test** that exercises this function. If a future refactor
breaks the per-domain loop (e.g. wrong `_set_domain` ordering, missed
`_stage` block, broken degraded-mode collection), nothing fails until prod.

**Files.** New `tests/test_pipeline_multi_domain.py`.

**Approach.** Mock `_discover_articles`, `scrape_articles`,
`translate_articles`, `extract_events`, `geocode_events`, `save_results`.
Pass `domains=["protest", "drone"]`, assert that each is invoked once with
the correct codebook/examples paths.

**Effort.** ~1.5h.

---

## P3 — Lower-priority polish

### 19. Bump dashboard's Container Apps REST API version

**Why it matters.** `2023-05-01` is 2 years old. Likely still works (this
surface is stable) but drift risk grows. Combine with end-to-end test of
the trigger flow.

**Files.** `src/web/app.py:143, 308` (and any other API-version references).
Change to `2024-03-01` or later. Test the trigger and log-tail tabs against
a live deployment before merging.

**Effort.** 30 min.

---

### 20. Flag truncated translations on the article record

**Why it matters.** `src/acquisition/translator.py:86` silently truncates
articles >4000 chars before translation. The LLM sees partial text without
any signal. A long article with the protest reported in paragraph 3 will be
translated; a long article with the protest in paragraph 9 may not be.

**Files.** `src/acquisition/translator.py`.

**Approach.** When truncation happens, set `article["_text_truncated"] =
True` and `article["_truncated_at_chars"] = 4000`. Log at WARNING. Surface
truncation count in the run summary.

**Effort.** 20 min.

---

### 21. Add jitter to extractor exponential backoff

**Why it matters.** Every worker retries at exactly the same backoff
intervals (`2**attempt`). On an Azure 5xx blip, all N workers retry in
lockstep — synchronized retry storm. At our scale (`workers=4`) this is
mostly cosmetic; matters more for backfills with `workers=8`.

**Files.** `src/acquisition/extractor.py:440` (and any other `time.sleep(2**attempt)`
sites — there's at least one in `extract_from_article`).

**Approach.**

```python
import random
sleep_s = (2**attempt) + random.uniform(0, 2**attempt)  # ±100% jitter
time.sleep(sleep_s)
```

**Effort.** 15 min. Add a unit test if you care.

---

### 22. End-to-end test of the annotation export → import roundtrip

**Why it matters.** The annotation pipeline (`src/annotation/`) is documented
in CLAUDE.md but no test covers `export_for_annotation` → mock Label Studio
JSON → `import_annotations`. First user to run it through the docs hits any
breakage.

**Files.** New `tests/test_annotation_roundtrip.py`.

**Approach.**
- Mock 3 events
- Run `export_for_annotation` → JSON file
- Hand-craft a "Label Studio export" JSON that mimics the format
- Run `import_annotations` → assert reviewed_events.jsonl + training_data.jsonl
  are well-formed and contain the corrections

**Effort.** ~2h.

---

### 23. Pin Container Apps API version + add fallback in dashboard

Tied to #19. If you bump the API version, also wrap the calls in a graceful
fallback that surfaces "API version no longer supported" as a clear error
in the Streamlit UI instead of an opaque 4xx/5xx.

---

### 24. Drone codebook is research prototype, not production

**Why it matters.** Acceptable for monitoring; not production-ready. Don't
expand `--domains` to include `drone` in the cron job until ground-truth
validation is run.

**Files.** None to change today. Track separately. The `_validate_domains`
guard in `pipeline.py` already rejects unknown domains, so the only way
drone gets used is by explicit operator opt-in via `--domains protest,drone`.

**Effort.** Zero today; revisit when you have drone ground-truth data.

---

### 25. QLoRA fine-tuning prep

**Why it matters.** Long-horizon quality work. Tier-1/2 example expansion
gets ~80% of the lift first, so don't fine-tune until the few-shot ceiling
is clearly hit.

**Files.** `src/annotation/` — already wired to produce
`training_data.jsonl`. Path is:

1. Run annotation workflow weekly (Label Studio → import → reviewed events)
2. Accumulate ≥40 gold examples per event type, ≥100 negatives, held-out
   test set from a different month than training
3. Fine-tune (out of repo scope)
4. Replace `--model` deployment name with the fine-tuned variant

**Effort.** Weeks of annotation work. Defer until the codebook tuning loop
plateaus.

---

## Items intentionally **not** on this list

- **VE codebook expansion.** Treat as research-only until a domain owner
  signs off. `_validate_domains` blocks accidental enablement. Don't widen
  the cron to VE without ground-truth validation. (See `DOMAIN_CONFIGS`
  comment in `src/acquisition/pipeline.py`.)
- **Single-domain pipeline stage-ordering refactor.** Done in `bdfa472` —
  translation now runs before relevance filter to match the multi-domain
  path. No further work needed unless you want to factor the duplication
  out into a shared helper (which would be the abstraction-too-early kind
  of refactor; the duplication is ~30 lines).
- **`process_articles_multi_domain` was never a real function name.** The
  multi-domain function is `run_pipeline_multi_codebook` in `pipeline.py`.
  Earlier review notes used the wrong name; the stage-tagging follow-up
  applied to the correct function.

---

## Cadence sketch

- **Day 1–7:** First cron run + manual review. Don't touch this list yet.
- **Week 2:** P2 items 11, 12, 15, 16 (CI hardening + integration test).
- **Week 3:** P2 items 13, 17, 18 (codebook examples + checkpoint atomicity
  + multi-domain test).
- **Week 4:** P2 item 14 (UG/DZ ground-truth examples) — by now you have
  real data to draw from.
- **Month 2:** P3 polish + start the annotation cadence for #25.

If a single one of these is more urgent than this ordering suggests, it'll
be visible in either the run-summary `degraded_modes` list (added in the
follow-up commit) or in `failures_*.jsonl`. Let those signals drive the
real cadence rather than this static list.
