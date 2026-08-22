FROM debian:bookworm-slim AS multimon-build

ARG MULTIMON_VERSION=1.6.0
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git cmake build-essential libpulse-dev libx11-dev && \
    git clone --depth 1 --branch "${MULTIMON_VERSION}" https://github.com/EliasOenal/multimon-ng.git /src/multimon-ng && \
    cmake -S /src/multimon-ng -B /src/multimon-ng/build -DCMAKE_BUILD_TYPE=Release && \
    cmake --build /src/multimon-ng/build -j"$(nproc)" && \
    cmake --install /src/multimon-ng/build --prefix /usr/local

FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    rtl-sdr libusb-1.0-0 libpulse0 libx11-6 ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY --from=multimon-build /usr/local/bin/multimon-ng /usr/local/bin/multimon-ng
COPY pyproject.toml README.md LICENSE /app/
COPY src /app/src
RUN pip install --no-cache-dir /app

WORKDIR /app
VOLUME ["/config", "/data"]
ENV P2000_CONFIG=/config/config.yaml

HEALTHCHECK --interval=90s --timeout=10s --start-period=30s --retries=3 \
    CMD ["p2000-rtlsdr", "--healthcheck"]

ENTRYPOINT ["p2000-rtlsdr"]
