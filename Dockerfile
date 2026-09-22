# syntax=docker/dockerfile:1

FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir --upgrade pip \
 && pip wheel --no-cache-dir --wheel-dir /wheels .

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MCP_BIND_HOST=0.0.0.0 \
    MCP_BIND_PORT=8080
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin mcp
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels mcp-gitlab \
 && rm -rf /wheels
USER 10001
EXPOSE 8080
# Loopback liveness probe. With native TLS the certificate names the public host, not 127.0.0.1,
# so this one local request skips certificate verification.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --start-interval=2s --retries=3 \
  CMD python -c "import os, ssl, urllib.request as u; tls = bool(os.environ.get('MCP_TLS_CERTFILE')); ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE; u.urlopen('%s://127.0.0.1:%s/healthz' % ('https' if tls else 'http', os.environ.get('MCP_BIND_PORT', '8080')), timeout=2, context=ctx if tls else None)"
ENTRYPOINT ["mcp-gitlab"]
