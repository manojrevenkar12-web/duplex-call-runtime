# The runtime: FastAPI + the Twilio Media Streams socket, the speech models, the built console.
# CPU image. deploy/k8s/ runs the same image with GPU speech serving next to it.

FROM node:20-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN useradd --create-home --uid 10001 dcr
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install .
COPY config/ config/
# models are pinned by SHA-256 in config/assets.yaml; fetched once, at build time
RUN DCR_HOME=/app dcr fetch --only runtime && rm -rf /app/data/models/downloads
COPY --from=web /web/dist web/dist
RUN mkdir -p /app/data /app/reports && chown -R dcr /app/data /app/reports
USER dcr
ENV DCR_HOME=/app DCR_DB=/app/data/calls.sqlite
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=60s CMD python -c "import urllib.request,sys; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/healthz').status != 200)"
CMD ["dcr", "serve", "--host", "0.0.0.0", "--port", "8000"]
