# API, seed job and MCP server share this image.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    QUILORA_HOME=/app

WORKDIR /app

# Dependencies first, so code changes do not invalidate the dependency layer.
COPY pyproject.toml README.md ./
COPY src ./src
ARG INSTALL_EMBEDDINGS=false
RUN if [ "$INSTALL_EMBEDDINGS" = "true" ]; then pip install ".[embeddings]"; else pip install .; fi

COPY data ./data
COPY db ./db
COPY evals ./evals

RUN useradd --create-home --uid 1000 app && chown -R app /app
USER app

EXPOSE 8000
CMD ["uvicorn", "quilora.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
