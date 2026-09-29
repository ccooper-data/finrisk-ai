FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FINRISK_MODEL_PATH=/app/model/boosted_tree_model.joblib

WORKDIR /app

RUN groupadd --system finrisk && useradd --system --gid finrisk --create-home finrisk

COPY pyproject.toml README.md /app/
COPY src /app/src
RUN pip install --no-cache-dir .

RUN mkdir -p /app/model && chown -R finrisk:finrisk /app
USER finrisk

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2)"

CMD ["uvicorn", "finrisk.serving:app", "--host", "0.0.0.0", "--port", "8000"]
