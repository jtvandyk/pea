# Stage 1: install dependencies
FROM python:3.11-slim AS builder
WORKDIR /build
COPY requirements-core.txt .
# Install torch CPU-only first via the PyTorch index.
# Without --index-url, pip pulls the 2 GB CUDA wheel from PyPI.
# CPU wheel is ~250 MB and sufficient for the relevance filter (DeBERTa inference).
RUN pip install --no-cache-dir --prefix=/install \
    torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir --prefix=/install -r requirements-core.txt

# Stage 2: lean runtime image
FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /install /usr/local
COPY src/ ./src/
COPY configs/ ./configs/
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "-m", "src.acquisition.pipeline"]
