# ==============================================================================
# Stage 1: Build the FairFlow React + Vite + Three.js Production Frontend
# ==============================================================================
FROM node:20-alpine AS frontend-build

WORKDIR /app

# Install frontend dependencies with layer caching
COPY package.json package-lock.json ./
RUN npm ci

# Copy frontend source and configuration files
COPY index.html postcss.config.js tailwind.config.js tsconfig.json tsconfig.app.json tsconfig.node.json vite.config.ts ./
COPY src ./src

# Build production static bundle (same-origin API on port 8000)
ENV VITE_API_URL=""
ENV VITE_USE_MOCK="false"
RUN npm run build

# ==============================================================================
# Stage 2: FairFlow Real-Time Linux QoS Controller & API Runtime
# ==============================================================================
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="FairFlow"
LABEL org.opencontainers.image.description="Safety-verified adaptive Linux QoS controller (HTB + fq_codel/CAKE) with 3D telemetry dashboard"
LABEL org.opencontainers.image.source="https://github.com/nayanjain24/fairflow"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Install Linux kernel networking & QoS tools required by the FairFlow testbed:
# - iproute2: tc (HTB, fq_codel, CAKE, netem, u32 filters), ip (netns, veth), ss
# - iperf3: bulk TCP/UDP traffic generation
# - ethtool: NIC TSO/GSO/GRO offload control
# - iputils-ping & procps: active RTT probes and process management
RUN apt-get update && apt-get install -y --no-install-recommends \
    iproute2 \
    iperf3 \
    ethtool \
    iputils-ping \
    procps \
    sudo \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python backend dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy FairFlow contract, backend source, scenarios, scripts, and baseline results
COPY contract.yaml contract.sha256 ./
COPY experiments ./experiments
COPY scripts ./scripts
COPY src/fairflow ./src/fairflow
COPY tests ./tests
COPY results ./results

# Copy compiled production frontend bundle from Stage 1
COPY --from=frontend-build /app/dist ./dist

# Expose FastAPI + Production Frontend port
EXPOSE 8000

# Verify service health via the FairFlow health endpoint
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/v1/health || exit 1

# Run the FairFlow API & SPA server (run container with --privileged or --cap-add=NET_ADMIN for live kernel tc/netns)
CMD ["uvicorn", "src.fairflow.api:app", "--host", "0.0.0.0", "--port", "8000"]

