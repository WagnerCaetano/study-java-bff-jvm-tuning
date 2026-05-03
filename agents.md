# Agent Context — BFF JVM Tuning PoC

This document provides full context for AI agents working on this project. It captures the architecture, design decisions, known issues, and current state.

## Project Overview

A local Docker-based PoC environment to stress test a Backend-for-Frontend (BFF) application, comparing **Java 24 (Blocking/Undertow vs Reactive/Netty)** and **Golang** under high memory allocation scenarios with Prometheus + Grafana observability.

## Architecture

```
k6 (Docker) ──► SUT (:8080) ──► Mock Backend (:8081)
                    │
                    ▼
              Prometheus (:9090) ──► Grafana (:3000)
```

All services run on a shared Docker bridge network (`bff-net`). k6 runs inside Docker via `docker compose run --rm` and accesses the SUT by Docker service name.

## File Structure

```
├── mock-backend/               # Node.js mock service (~50KB JSON, 20ms delay)
│   ├── server.js               # Express server with /api/data and /health endpoints
│   ├── package.json            # Node.js dependencies
│   └── Dockerfile              # Node 20 Alpine
├── bff-blocking/               # Java 24 + Spring Boot 3.4.5 + Undertow + RestClient
│   ├── pom.xml                 # Excludes tomcat, includes undertow, actuator, micrometer-prometheus
│   ├── Dockerfile              # Multi-stage: maven build → JRE 24 Alpine runtime
│   └── src/main/java/.../
│       ├── BffBlockingApplication.java
│       ├── config/RestClientConfig.java    # RestClient bean, baseUrl=http://mock-backend:8081
│       ├── controller/ProxyController.java # GET /api/data → returns raw JSON string
│       └── resources/application.yml       # Undertow IO=4/Worker=200, actuator, micrometer tags
├── bff-reactive/               # Java 24 + Spring Boot 3.4.5 + Netty + WebClient
│   ├── pom.xml                 # spring-boot-starter-webflux, actuator, micrometer-prometheus
│   ├── Dockerfile              # Same structure as bff-blocking
│   └── src/main/java/.../
│       ├── BffReactiveApplication.java
│       ├── config/WebClientConfig.java     # WebClient bean, baseUrl=http://mock-backend:8081
│       ├── controller/ProxyController.java # GET /api/data → returns Mono<ResponseEntity<String>>
│       └── resources/application.yml       # max-in-memory-size=1MB, micrometer tags
├── bff-golang/                 # Go 1.22 HTTP proxy with Prometheus metrics
│   ├── main.go                 # GOMAXPROCS=2, /api/data, /health, /metrics
│   ├── go.mod                  # prometheus/client_golang v1.19.1
│   └── Dockerfile              # Multi-stage Go Alpine build
├── k6/
│   ├── stress-test.js          # 10-min test (1m ramp + 8m sustain @200 VUs + 1m ramp down)
│   └── analyze-k6.py           # Python analyzer for k6 NDJSON (status codes, percentiles, throughput)
├── prometheus/
│   └── prometheus.yml          # 5s scrape interval, 3 jobs (bff-blocking, bff-reactive, bff-golang)
├── grafana/
│   └── provisioning/
│       ├── datasources/datasource.yml      # Auto-configured Prometheus at http://prometheus:9090
│       ├── dashboards/dashboard.yml        # File-based provider
│       └── dashboards/
│           ├── bff-overview.json           # Original 9-panel dashboard
│           └── bff-comprehensive.json      # Comprehensive 16-panel dashboard (recommended)
├── docker-compose.yml          # Profiles: blocking, reactive, golang. k6 service for Docker-based runs
├── results/                    # k6 NDJSON + GC logs + summary JSONs (mounted volume)
├── plans/
│   ├── plan.md                 # Original architecture plan
│   └── agents.md               # This file
├── README.md                   # Full execution instructions
└── .gitignore                  # Ignores results/*.json, results/*.log, prometheus-data/, grafana-data/
```

## Key Design Decisions

1. **Java 24** (not 21) — user requested latest
2. **Undertow** instead of Tomcat for blocking variant — user preference
3. **Netty** via webflux for reactive variant
4. **Docker Compose profiles** — only one SUT runs at a time (`blocking`, `reactive`, `golang`)
5. **k6 runs inside Docker** — no host installation needed, uses `docker compose run --rm`
6. **Prometheus retention** — 3 hour (`--storage.tsdb.retention.time=3h`)
7. **Heap sizing** — 1536m fixed (leaves ~512MB for native within 2GB container limit)
8. **GC logging** — unified JVM format to `/results/gc.log` with 5-file rotation

## Docker Compose Profiles

| Profile | Service | Port |
|---------|---------|------|
| `blocking` | bff-blocking | 8080 |
| `reactive` | bff-reactive | 8080 |
| `golang` | bff-golang | 8080 |
| (none) | k6 | one-off |

Infrastructure services (mock-backend, prometheus, grafana) always run regardless of profile.

## JVM Flags

### ParallelGC (Tuned)
```
-XX:+UseParallelGC -XX:NewRatio=1 -XX:SurvivorRatio=6 -Xms1536m -Xmx1536m
-Xlog:gc*:file=/results/gc.log:time,uptime,level,tags:filecount=5,filesize=10m
```

### Generational ZGC
```
-XX:+UseZGC -XX:+ZGenerational -Xms1536m -Xmx1536m
-Xlog:gc*:file=/results/gc.log:time,uptime,level,tags:filecount=5,filesize=10m
```

## Data Sources

| Source | Description | Location |
|--------|-------------|----------|
| k6 NDJSON | Raw load test data (3-4 GB per test) | `results/<scenario>.json` |
| k6 Summary | Compact JSON (~1 KB) with status codes, percentiles | `results/summary-<scenario>.json` |
| Prometheus | JVM metrics (heap, GC, CPU, HTTP) scraped every 5s | Docker volume `prometheus-data` |
| Grafana Dashboards | Visualizes Prometheus data | Docker volume `grafana-data` |
| GC Log | JVM unified GC logging | `results/gc-<scenario>.log` |

## Prometheus Metrics Available

Key metrics exposed by Spring Boot Actuator + Micrometer:

| Metric | Description |
|--------|-------------|
| `http_server_requests_seconds_bucket` | HTTP latency histogram (for percentile queries) |
| `http_server_requests_seconds_count` | HTTP request count |
| `jvm_memory_used_bytes` | Memory used by pool (area=heap/nonheap, id=Eden/Old/Survivor/Metaspace) |
| `jvm_memory_max_bytes` | Max memory by pool |
| `jvm_gc_pause_seconds_sum` | GC pause time (action=end of minor/major GC, gc=PS Scavenge/PS MarkSweep) |
| `jvm_gc_pause_seconds_count` | GC event count |
| `jvm_gc_memory_allocated_bytes_total` | Total allocated in young gen |
| `jvm_gc_memory_promoted_bytes_total` | Total promoted to old gen |
| `process_cpu_usage` | CPU usage gauge |
| `jvm_threads_live_threads` | Live thread count |

All metrics have an `application` tag (set via `management.metrics.tags.application` in application.yml) with values `bff-blocking`, `bff-reactive`, or `bff-golang`.

## Known Issues & Fixes Applied

1. **Prometheus config** — `labels` field is NOT valid in `scrape_config`. Use Micrometer tags instead.
2. **Alpine IPv6** — `localhost` resolves to `::1` in Alpine. All health checks use `127.0.0.1`.
3. **Mock payload size** — 500 items = 224KB. Reduced to 150 items ≈ 47KB.
4. **k6 handleSummary** — Must return actual text for stdout; returning empty string suppresses output.

## Scenario 1 Results (BFF-Blocking + ParallelGC)

```
HTTP STATUS CODES
  Total Requests:  921,656
     2xx:          921,656  (100.00%)
     5xx:                0  (0.00%)
  Timeouts:             0  (0.00%)

LATENCY (ms)
  Avg: 66.60  |  p50: 67.56  |  p95: 109.57  |  p99: 146.46  |  Max: 319.80

THROUGHPUT
  Requests/sec: 1,533.9
  Data Received: 42,636.6 MB

GC (from gc.log)
  Young GC pauses: 2.5–6ms (460 events)
  Full GC pauses: ~35ms (6 events, all at startup/metadata)
  Allocation rate: ~640 MB/s
  Old Gen growth: 16KB → 262MB over 10 min
```

## Cleanup & Data Management

- `docker compose down` — stops containers, preserves volumes
- `docker compose down -v` — stops containers AND removes Prometheus/Grafana data
- Prometheus auto-deletes data older than 1 hour (configured retention)
- k6 NDJSON files are large (3-4 GB each); summary JSONs are ~1 KB
- To start fresh: `docker compose down -v` then `docker compose up -d mock-backend prometheus grafana`
