ARG BUILD_FROM=ghcr.io/hassio-addons/base:20.1.1
FROM ${BUILD_FROM}

ARG BUILD_ARCH
ARG CLOUDFLARED_VERSION=2026.8.2

RUN apk add --no-cache python3 py3-aiohttp curl \
    && case "${BUILD_ARCH}" in \
      amd64) CF_ASSET=amd64; CF_SHA=fcfb02b575a52ca1af2e3267af4e1517bcdeb30ac48c834c69abaed3c0576ad2 ;; \
      aarch64) CF_ASSET=arm64; CF_SHA=7747d94570fb390cf47dcb4f9555c193c6355cda9793f0d878d9049e5d6a7790 ;; \
      *) echo "Unsupported BUILD_ARCH: ${BUILD_ARCH}" >&2; exit 1 ;; \
    esac \
    && curl -fsSL "https://github.com/cloudflare/cloudflared/releases/download/${CLOUDFLARED_VERSION}/cloudflared-linux-${CF_ASSET}" -o /usr/local/bin/cloudflared \
    && echo "${CF_SHA}  /usr/local/bin/cloudflared" | sha256sum -c - \
    && chmod 0755 /usr/local/bin/cloudflared
COPY rootfs /
RUN chmod a+x /etc/services.d/proxy/run /etc/services.d/cloudflared/run

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl --fail --silent --show-error http://127.0.0.1:8099/health >/dev/null || exit 1
