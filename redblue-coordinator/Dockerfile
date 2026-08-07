# redblue-coordinator image (plan 02 §1.4 / plan 07). Minimal uv-based build.
FROM python:3.13-slim

# uv for fast, reproducible installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml ./
COPY redblue ./redblue
RUN uv pip install --system .

EXPOSE 8900 8902
# The app is a factory (`create_app()` — no module-level `app`), so uvicorn needs --factory.
# `redblue.api:create_app` with no args builds the live connector deps (lazy clients — safe to
# construct before the engines are up; they retry with backoff at request time).
CMD ["uvicorn", "redblue.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8900"]
