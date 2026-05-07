# Implementation Guide — Superseded

The previous contents of this file described an early, local-only
architecture (Llama via Ollama, no cloud APIs, single-machine batch
processor) that no longer matches the codebase. PEA now runs on Azure
Container Apps with Azure AI Foundry as the LLM backend.

For current implementation guidance, see:

- **`.claude/azure-deploy-playbook.md`** — end-to-end deploy playbook
  (provision → push → deploy → smoke test → first run → hardening).
- **`.claude/improvement-guide.md`** — codebook + few-shot expansion guidance.
- **`.claude/production-followups.md`** — remaining P2/P3 priority items
  with file paths and effort estimates.
- **`README.md`** — user-facing architecture overview, CLI reference,
  and "Production Deployment (Azure)" section.
- **`CLAUDE.md`** — project-level Claude Code context (codebook version,
  pipeline stages, env vars, code-quality rules).
