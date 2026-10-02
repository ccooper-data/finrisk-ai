# Python and the pinned libraries in constraints/serving.txt must match the training run,
# because scikit-learn model pickles are version-specific.
FROM python:3.12-slim

ARG GIT_SHA=unknown
ARG MODEL_SHA256=none
ARG MODEL_RUN_ID=none

LABEL org.opencontainers.image.source="https://github.com/ccooper-data/finrisk-ai" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      io.finrisk.model.sha256="${MODEL_SHA256}" \
      io.finrisk.model.run-id="${MODEL_RUN_ID}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FINRISK_MODEL_PATH=/app/model/boosted_tree_model.joblib

WORKDIR /app

# Numeric UID/GID so Kubernetes runAsNonRoot can verify the user (it rejects named users).
RUN groupadd --system --gid 10001 finrisk && useradd --system --uid 10001 --gid finrisk --create-home finrisk

COPY pyproject.toml README.md /app/
COPY constraints/serving.txt /app/constraints/serving.txt
COPY src /app/src
RUN pip install --no-cache-dir -c /app/constraints/serving.txt .

# Holds only README.md in CI; build-inference-image.yml adds the reviewed model artifact.
COPY model/ /app/model/
RUN chown -R 10001:10001 /app
USER 10001:10001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2)"

CMD ["uvicorn", "finrisk.serving:app", "--host", "0.0.0.0", "--port", "8000"]
