# `.claude/` — Index

Working notes that supplement [`CLAUDE.md`](../CLAUDE.md). Read this index
first; it tells you which file is current, which is reference-only, and
when each was last reviewed. If a file isn't listed here, it shouldn't be
trusted — delete it or add it to the table.

## Files

| File | Purpose | When to read | Last reviewed |
|---|---|---|---|
| [`deploy.md`](deploy.md) | End-to-end Azure deploy playbook (provision → push → deploy → smoke → first run → hardening). Includes operations runbook, rollback, and troubleshooting. | Deploy day, rollbacks, on-call investigation. | 2026-05-10 |
| [`followups.md`](followups.md) | Working list of P2/P3 follow-up items with file paths, approach, and effort estimates. | Picking the next chunk of hardening work. | 2026-05-10 |
| [`settings.json`](settings.json) | Pre-commit hook config (runs `black --check` + `flake8` before any `git commit`). | Editing local Claude Code behavior. | — |

## Skills

Project-scoped skills live under [`skills/`](skills/). Each is a self-contained
`SKILL.md` with YAML frontmatter that Claude Code surfaces by description
when its triggers match what the user is asking.

### Tier 1 — recurring loops

| Skill | Triggers on… | Last reviewed |
|---|---|---|
| [`pea-canary-run`](skills/pea-canary-run/SKILL.md) | "canary run", "diff the last run", post-codebook verification | 2026-05-10 |
| [`pea-codebook-edit`](skills/pea-codebook-edit/SKILL.md) | "edit the codebook", "add a disqualifier", "tune extraction" | 2026-05-10 |
| [`pea-few-shot-add`](skills/pea-few-shot-add/SKILL.md) | "add a few-shot example", "new gold case", "tier-2 example" | 2026-05-10 |
| [`pea-deploy-phase`](skills/pea-deploy-phase/SKILL.md) | "deploy to Azure", "phase N", "resume the deploy" | 2026-05-10 |
| [`pea-followup-pick`](skills/pea-followup-pick/SKILL.md) | "what should I work on", "next followup", "pick a P2 item" | 2026-05-10 |

### Tier 2 — diagnostics for known failure shapes

| Skill | Triggers on… | Last reviewed |
|---|---|---|
| [`pea-degraded-mode`](skills/pea-degraded-mode/SKILL.md) | "degraded mode", "keyword fallback", "degraded_modes non-empty" | 2026-05-10 |
| [`pea-rollback`](skills/pea-rollback/SKILL.md) | "rollback the deploy", "revert to previous SHA", "pause the cron" | 2026-05-10 |
| [`pea-token-audit`](skills/pea-token-audit/SKILL.md) | "audit prompt size", "check token budget", "did the codebook bloat" | 2026-05-10 |

### Tier 3 — validators / annotation / smoke

| Skill | Triggers on… | Last reviewed |
|---|---|---|
| [`pea-validate`](skills/pea-validate/SKILL.md) | "validate against gold", "check recall", "run CEHA / CASE / GLOCON" | 2026-05-10 |
| [`pea-annotation-batch`](skills/pea-annotation-batch/SKILL.md) | "export annotation tasks", "import label studio", "training pairs" | 2026-05-10 |
| [`pea-smoke`](skills/pea-smoke/SKILL.md) | "post-deploy smoke", "is foundry reachable", "test the foundry endpoint" | 2026-05-10 |

### Tier 4 — extension / hygiene

| Skill | Triggers on… | Last reviewed |
|---|---|---|
| [`pea-domain-add`](skills/pea-domain-add/SKILL.md) | "add a new domain", "wire a domain", "register drone in DOMAIN_CONFIGS" | 2026-05-10 |
| [`claude-doc-rot`](skills/claude-doc-rot/SKILL.md) | "audit .claude docs", "are these docs stale", "doc rot check" | 2026-05-10 |

### Imported — general-purpose patterns (not PEA-specific)

| Skill | Triggers on… | Origin |
|---|---|---|
| [`pytorch-patterns`](skills/pytorch-patterns/SKILL.md) | PyTorch model authoring, training loops, AMP / `torch.compile`, checkpointing, anti-patterns | ECC |

## Agents

Project-scoped subagents live under [`agents/`](agents/). Each is a single
`<name>.md` with YAML frontmatter (`name`, `description`, `tools`, `model`)
and a system-prompt body. Spawn via the Agent tool with `subagent_type:
<name>`.

| Agent | Use when… | Model |
|---|---|---|
| [`python-pro`](agents/python-pro.md) | Building type-safe, production-ready Python (web APIs, async, type coverage) | sonnet |
| [`nlp-engineer`](agents/nlp-engineer.md) | Production NLP — text pipelines, NER, classification, multilingual, fine-tuning | sonnet |
| [`data-scientist`](agents/data-scientist.md) | EDA, hypothesis testing, model development, translating findings into recommendations | sonnet |
| [`ml-engineer`](agents/ml-engineer.md) | Production ML lifecycle — training pipelines, serving, monitoring, retraining | sonnet |

These four are **general-purpose imports** (no PEA-specific knowledge baked
in). Useful for the relevance-filter / fine-tuning / validation workstreams,
but not a substitute for the PEA skills above when the task is project-scoped.

## Rules to keep this from rotting

1. **One source of truth per topic.** `CLAUDE.md` is the project context.
   `deploy.md` is the deploy runbook. `followups.md` is the work queue.
   Anything else is suspect.
2. **Date every doc.** New `.claude/*.md` files must carry a
   `> Last reviewed: YYYY-MM-DD` line directly under the H1.
3. **Update or delete — don't deprecate in place.** If guidance is
   superseded, delete the file and update this index in the same commit.
   Stub "see other doc" files (like the old `implementation-guide.md`)
   become a second source of stale truth and get read by Claude as if
   they were current.
4. **Cross-reference by relative path** (e.g. `deploy.md`, not
   `.claude/deploy.md`) when linking from inside `.claude/`. Use the
   `.claude/`-prefixed form from `CLAUDE.md` and `README.md`.
