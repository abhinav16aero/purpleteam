# redblue-coordinator image (plan 02 §1.4 / plan 07). Minimal uv-based build.
FROM python:3.13-slim

# uv for fast, reproducible installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml ./
COPY redblue ./redblue
RUN uv pip install --system .

EXPOSE 8900 8902
# The FastAPI app (redblue.api.app:app) lands in P4. Until then this image builds the
# package and this CMD is the intended entrypoint once the app module exists.
CMD ["uvicorn", "redblue.api.app:app", "--host", "0.0.0.0", "--port", "8900"]
