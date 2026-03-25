# CLAUDE.md — PEA Project Context

## Project Overview

Protest Event Analysis (PEA) pipeline. Discovers news articles via GDELT DOC 2.0 API, scrapes + translates, extracts structured protest events via Claude API (Anthropic), and stores results as JSONL/CSV.

**Codebook version:** 2.2 (Halterman & Keith 2025, Type III)
**LLM backend:** `claude-sonnet-4-6` via `anthropic` SDK
**Target geography:** African countries (NG, ZA, UG, DZ)

## Key Files

| File | Purpose |
|------|---------|
| `configs/protest_codebook.yaml` | Codebook v2.2 — event types, non-event disqualifiers, minimum criteria |
| `src/acquisition/pipeline.py` | Entry point — 5-stage pipeline (discover → scrape → translate → extract → store) |
| `src/acquisition/extractor.py` | LLM extraction — Claude API, SYSTEM_PROMPT with two-step disqualifier gate |
| `src/acquisition/storage.py` | Output — JSONL, CSV, run summary JSON, `_derive_turmoil_level()` |

## Environment

- Requires `ANTHROPIC_API_KEY` environment variable (or `.env` file once dotenv is activated)
- Python virtualenv at `venv/` — use `venv/bin/python3` for manual runs

---

## Production-Readiness Improvements (Planned)

The pipeline is functionally solid (5-stage GDELT → scrape → translate → Claude → store). Error handling, retries, and data output are already well-implemented. The gaps are in the DevOps/infra layer: no container, no cloud storage, no structured logs, no checkpoint capability.

All seven improvements below are independent and can be done in any order. **Recommended implementation order is listed at the end.**

---

### Improvement 1 — Dockerfile + .dockerignore

**Why:** Everything in AWS (ECS/Fargate/Lambda container) and Azure (ACI/App Service/AKS) runs containers.

**Files:** create `Dockerfile`, `.dockerignore`

**Approach — multi-stage build:**
```dockerfile
# Stage 1: deps
FROM python:3.11-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: runtime (no build tools)
FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /install /usr/local
COPY src/ ./src/
COPY configs/ ./configs/
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "-m", "src.acquisition.pipeline"]
```

`.dockerignore`: exclude `data/`, `tests/`, `docs/`, `*.pyc`, `.git`, `.env`

> **Note:** `vllm` and `torch` in `requirements.txt` are GPU-only and bloat the image. Recommend splitting into `requirements-core.txt` (pipeline only) and `requirements-ml.txt` (vllm, torch, transformers). Dockerfile uses core only.

**Verify:** `docker build -t pea . && docker run --env-file .env.dev pea --help`

---

### Improvement 2 — Activate python-dotenv (2-line fix)

**Why:** `python-dotenv` is already in `requirements.txt` but never called. Without it, `.env` files are silently ignored in local dev and CI.

**Files:** `src/acquisition/pipeline.py` (entry point)

**Change — add at top of `main()`:**
```python
from dotenv import load_dotenv
load_dotenv()  # loads .env if present; no-op if not
```

Also create `.env.example` → `.env.dev` and `.env.prod` with appropriate values for a dev/prod config split.

**Verify:** Create `.env` with a test key → confirm `os.environ.get("ANTHROPIC_API_KEY")` resolves.

---

### Improvement 3 — Structured JSON Logging

**Why:** CloudWatch Logs Insights (AWS) and Log Analytics (Azure Monitor) parse JSON logs natively. Text logs require regex parsing. JSON logs unlock filtering, dashboards, and alerting with zero extra config.

**Files:** `src/acquisition/pipeline.py` (logging setup)

**Change — replace `basicConfig` with a JSON formatter:**
```python
import json, logging

class _JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            **({"exc": self.formatException(record.exc_info)} if record.exc_info else {}),
        })

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(_JsonFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler])
```

No new dependencies.

**Verify:** Run pipeline with one article → confirm stdout is valid JSON lines.

---

### Improvement 4 — Optional Cloud Storage Upload in storage.py

**Why:** Writing to `data/raw/` only works if the container has a persistent volume. On ECS/Fargate or ACI (serverless containers) the local disk is ephemeral.

**Files:** `src/acquisition/storage.py`, `requirements.txt`

**Approach — add optional `upload_to` parameter to `save_results()`:**
```python
def save_results(events, output_dir, run_id, upload_to: str | None = None):
    # ... existing write logic ...
    if upload_to:
        _upload_outputs(upload_to, [jsonl_path, csv_path, summary_path])

def _upload_outputs(destination: str, paths: list[Path]):
    """destination: 's3://bucket/prefix' or 'az://container/prefix'"""
    if destination.startswith("s3://"):
        import boto3
        s3 = boto3.client("s3")
        bucket, prefix = destination[5:].split("/", 1)
        for p in paths:
            s3.upload_file(str(p), bucket, f"{prefix}/{p.name}")
    elif destination.startswith("az://"):
        from azure.storage.blob import BlobServiceClient
        # connection string from AZURE_STORAGE_CONNECTION_STRING env var
        client = BlobServiceClient.from_connection_string(
            os.environ["AZURE_STORAGE_CONNECTION_STRING"]
        )
        container, prefix = destination[5:].split("/", 1)
        for p in paths:
            blob = client.get_blob_client(container, f"{prefix}/{p.name}")
            with open(p, "rb") as f:
                blob.upload_blob(f, overwrite=True)
```

**Verify:** Run pipeline with `--upload-to s3://bucket/prefix` → check S3 console.

---

### Improvement 5 — Checkpoint / Resume for Long Runs

**Why:** A multi-hour pipeline run that fails at article 800/1000 currently loses all progress. A checkpoint file lets it resume from where it stopped.

**Files:** `src/acquisition/pipeline.py`, `src/acquisition/storage.py`

**Approach:**
```python
def _load_checkpoint(output_dir: Path, run_id: str) -> set[str]:
    cp = output_dir / "checkpoint.txt"
    return set(cp.read_text().splitlines()) if cp.exists() else set()

def _save_checkpoint(output_dir: Path, url: str):
    with open(output_dir / "checkpoint.txt", "a") as f:
        f.write(url + "\n")
```

In the extraction loop (pipeline.py Stage 4):
```python
done_urls = _load_checkpoint(output_dir, run_id)
scraped = [a for a in scraped if a.get("url") not in done_urls]
# after each article:
_save_checkpoint(output_dir, article["url"])
```

If `all_events.jsonl` is uploaded to S3/Blob (Improvement 4), the checkpoint file can also be uploaded there for durability across container restarts.

**Verify:** Kill pipeline mid-run → restart → confirm processed URLs are skipped.

---

### Improvement 6 — Dead-Letter File for Failed Articles

**Why:** Articles that fail extraction (parse error, timeout, empty result) are currently silently logged and discarded. In production, a record is needed for manual review or reprocessing.

**Files:** `src/acquisition/extractor.py`, `src/acquisition/storage.py`

**Approach — `extract_events()` returns a secondary list of failures:**
```python
def extract_events(...) -> tuple[list[dict], list[dict]]:
    ...
    failures = []
    # when all retries exhausted:
    failures.append({
        "url": article.get("url"),
        "title": article.get("title"),
        "reason": "extraction_failed",
        "lang": lang
    })
    return all_events, failures
```

`save_results()` writes `failures_{run_id}.jsonl` alongside the events files.

**Verify:** Pass a bad URL → confirm `failures_*.jsonl` is written with the entry.

---

### Improvement 7 — GitHub Actions: Docker Build + Push to ECR or ACR

**Why:** Extends the existing CI (tests + lint) with a deployment step. After merge to main, the image is built and pushed so it's always ready to deploy.

**Files:** create `.github/workflows/docker.yml`

**For AWS (ECR):**
```yaml
name: Docker Build & Push (ECR)
on:
  push:
    branches: [main]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: us-east-1
      - uses: aws-actions/amazon-ecr-login@v2
      - name: Build and push
        env:
          ECR_REGISTRY: ${{ steps.login-ecr.outputs.registry }}
        run: |
          docker build -t $ECR_REGISTRY/pea:${{ github.sha }} .
          docker push $ECR_REGISTRY/pea:${{ github.sha }}
          docker tag $ECR_REGISTRY/pea:${{ github.sha }} $ECR_REGISTRY/pea:latest
          docker push $ECR_REGISTRY/pea:latest
```

For Azure (ACR): swap ECR steps for `azure/docker-login@v1` with `ACR_LOGIN_SERVER`, `ACR_USERNAME`, `ACR_PASSWORD`.

Secrets are stored in GitHub repo → Settings → Secrets.

**Verify:** Push to main → check GitHub Actions → confirm image appears in ECR/ACR.

---

## Recommended Implementation Order

| # | Improvement | Effort | Risk |
|---|-------------|--------|------|
| 1 | **Improvement 2** — Activate dotenv | 2 lines | Zero |
| 2 | **Improvement 1** — Dockerfile | ~20 lines | Low |
| 3 | **Improvement 3** — JSON logging | ~15 lines | Low |
| 4 | **Improvement 6** — Dead-letter file | Medium | Low |
| 5 | **Improvement 5** — Checkpoint/resume | Medium | Medium |
| 6 | **Improvement 4** — Cloud storage upload | Medium | Low |
| 7 | **Improvement 7** — CI deploy step | Medium | Low (needs ECR/ACR set up first) |
