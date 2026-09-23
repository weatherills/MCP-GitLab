# syntax=docker/dockerfile:1

# Two images from one file:
#   standalone (the default): Caddy serves HTTPS in front of the MCP server, in one container.
#   server (--target server): the MCP server alone, for a proxy or load balancer that
#   terminates TLS in front of it.

ARG CADDY_VERSION=2.11.4

FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir --upgrade pip \
 && pip wheel --no-cache-dir --wheel-dir /wheels .

FROM caddy:${CADDY_VERSION} AS caddy
# The official binary carries the cap_net_bind_service file capability, for ports below 1024.
# This image listens on 8443, and a binary with file capabilities won't start once they are
# dropped (cap_drop: ALL), so remove it.
RUN setcap -r /usr/bin/caddy

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin mcp
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels mcp-gitlab \
 && rm -rf /wheels
# The GitLab instance, preset with --build-arg; GITLAB_BASE_URL at run time still overrides it.
ARG GITLAB_BASE_URL=https://gitlab.com/api/v4
ENV GITLAB_BASE_URL=${GITLAB_BASE_URL}

FROM runtime AS server
ENV MCP_BIND_HOST=0.0.0.0 \
    MCP_BIND_PORT=8080
USER 10001
EXPOSE 8080
# Loopback liveness probe. With native TLS the certificate names the public host, not 127.0.0.1,
# so this one local request skips certificate verification.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --start-interval=2s --retries=3 \
  CMD python -c "import os, ssl, urllib.request as u; tls = bool(os.environ.get('MCP_TLS_CERTFILE')); ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE; u.urlopen('%s://127.0.0.1:%s/healthz' % ('https' if tls else 'http', os.environ.get('MCP_BIND_PORT', '8080')), timeout=2, context=ctx if tls else None)"
ENTRYPOINT ["mcp-gitlab"]

FROM runtime AS standalone
COPY --from=caddy /usr/bin/caddy /usr/bin/caddy
COPY deploy/Caddyfile /etc/caddy/Caddyfile
# Caddy keeps its local CA in /data: keep /data on a volume, or clients must trust a new CA
# each time the container is re-created.
RUN mkdir /config /data \
 && chown 10001:10001 /config /data
# The host name clients connect to, preset with --build-arg; MCP_PUBLIC_HOST at run time
# still overrides it. Certificates are mounted at run time (in /certs), never built in.
ARG MCP_PUBLIC_HOST=localhost
ENV MCP_PUBLIC_HOST=${MCP_PUBLIC_HOST} \
    MCP_HTTPS_PORT=8443 \
    XDG_CONFIG_HOME=/config \
    XDG_DATA_HOME=/data
USER 10001
VOLUME ["/data"]
EXPOSE 8443
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --start-interval=2s --retries=3 \
  CMD ["python", "-m", "mcp_gitlab.standalone", "--healthcheck"]
ENTRYPOINT ["python", "-m", "mcp_gitlab.standalone"]
