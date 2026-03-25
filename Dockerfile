# Stage 1: install dependencies
FROM python:3.11-slim AS builder
WORKDIR /build
COPY requirements-core.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements-core.txt

# Stage 2: lean runtime image
FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /install /usr/local
COPY src/ ./src/
COPY configs/ ./configs/
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "-m", "src.acquisition.pipeline"]
