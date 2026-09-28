# career-architect MCP server.
# Build from the repository root (the image needs jobs/scripts/career.py as well as this folder):
#   docker build -f mcp-server/Dockerfile -t career-architect-mcp:local .
#
# The base image is pinned by digest so a build is reproducible. Refresh it (and requirements.lock) when
# security fixes land: see docs/OPERATIONS.md, "Updating".
FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8080

RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin career
WORKDIR /app

# Every dependency, transitive ones included, is pinned with hashes; pip refuses anything else.
COPY mcp-server/requirements.lock ./
RUN pip install --require-hashes --no-deps -r requirements.lock

COPY mcp-server/server.py ./server.py
COPY jobs/scripts/career.py ./career.py

USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3).status == 200 else 1)"]
CMD ["python", "server.py"]
