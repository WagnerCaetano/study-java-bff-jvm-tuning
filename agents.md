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
│   ├── pom.xml                 # Excludes tomcat, includes undertow, actuator, micrometer-prometheus, httpclient5
│   ├── Dockerfile              # Multi-stage: maven build → JRE 24 Alpine runtime
│   └── src/main/java/.../
│       ├── BffBlockingApplication.java
│       ├── config/RestClientConfig.java    # Apache HttpClient5 + pool metrics (active/idle/pending/max)
│       ├── controller/ProxyController.java # GET /api/data → returns raw JSON string
│       └── resources/application.yml       # Undertow IO=4/Worker=200, actuator, micrometer tags
├── bff-reactive/               # Java 24 + Spring Boot 3.4.5 + Netty + WebClient
│   ├── pom.xml                 # spring-boot-starter-webflux, actuator, micrometer-prometheus
│   ├── Dockerfile              # Same structure as bff-blocking
│   └── src/main/java/.../
│       ├── BffReactiveApplication.java
│       ├── config/WebClientConfig.java     # Named ConnectionProvider "mock-backend" + pool metrics
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
│           └── bff-comprehensive.json      # Unified 22-panel dashboard (6 rows, includes connection pool)
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

### ParallelGC (Default — No Tuning)
```
-XX:+UseParallelGC -Xms1536m -Xmx1536m
-Xlog:gc*:file=/results/gc.log:time,uptime,level,tags:filecount=5,filesize=10m
```
JVM uses all defaults: adaptive sizing enabled, default generation ratios, default GCTimeRatio=99.

### ParallelGC (Production-Tuned)
```
-XX:+UseParallelGC -XX:MaxGCPauseMillis=200 -XX:GCTimeRatio=9 -XX:SurvivorRatio=4
-XX:ParallelGCThreads=2 -XX:NewSize=650m -XX:MaxNewSize=750m -XX:-UseAdaptiveSizePolicy
-XX:MaxHeapFreeRatio=100 -Xms1536m -Xmx1536m
-Xlog:gc*:file=/results/gc.log:time,uptime,level,tags:filecount=5,filesize=10m
```
Derived from real production GC tuning. Key changes: fixed young gen (650-750m), disabled adaptive sizing, GCTimeRatio=9 (10% GC time budget vs default 1%), SurvivorRatio=4 (larger survivors = less promotion).

### Generational ZGC
```
-XX:+UseZGC -XX:+ZGenerational -Xms1536m -Xmx1536m
-Xlog:gc*:file=/results/gc.log:time,uptime,level,tags:filecount=5,filesize=10m
```

## Test Scenarios (7 total)

| # | SUT | GC Strategy | SCENARIO_NAME |
|---|-----|-------------|---------------|
| 1 | BFF-Blocking | ParallelGC default (no tuning) | `blocking-parallelgc-default` |
| 2 | BFF-Blocking | ParallelGC production-tuned | `blocking-parallelgc-tuned` |
| 3 | BFF-Blocking | Generational ZGC | `blocking-zgc` |
| 4 | BFF-Reactive | ParallelGC default (no tuning) | `reactive-parallelgc-default` |
| 5 | BFF-Reactive | ParallelGC production-tuned | `reactive-parallelgc-tuned` |
| 6 | BFF-Reactive | Generational ZGC | `reactive-zgc` |
| 7 | BFF-Golang | Go runtime GC | `golang` |

Scenarios 1 vs 2 (and 4 vs 5) demonstrate the real-world impact of GC tuning — from default ParallelGC to production-hardened parameters that halved response time in production.

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

### Server-Side Metrics (inbound HTTP)

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

### Outbound Connection Pool Metrics

**Blocking variant** (Apache HttpClient5 via custom Micrometer gauges):

| Metric | Description |
|--------|-------------|
| `httpclient_pool_active` | Connections currently leased (in use) |
| `httpclient_pool_idle` | Connections idle in pool (available for reuse) |
| `httpclient_pool_pending` | Requests waiting for a connection (queue depth) |
| `httpclient_pool_max` | Max connections allowed (default: 25 total, 5 per route) |

**Reactive variant** (Reactor Netty named ConnectionProvider "mock-backend"):

| Metric | Description |
|--------|-------------|
| `reactor_netty_connection_provider_active_connections` | Active connections |
| `reactor_netty_connection_provider_idle_connections` | Idle connections |
| `reactor_netty_connection_provider_pending_connections` | Pending requests waiting for connection |

**Key insight**: The reactive variant defaults to `maxConnections = 2 * availableCPUs` (min 8). With 2 CPUs in the container, this means only ~4-8 outbound connections to the mock backend. At 200 concurrent VUs, most requests queue in the connection pool. The `pending` metric reveals this bottleneck.

All metrics have an `application` tag (set via `management.metrics.tags.application` in application.yml) with values `bff-blocking`, `bff-reactive`, or `bff-golang`.

## Known Issues & Fixes Applied

1. **Prometheus config** — `labels` field is NOT valid in `scrape_config`. Use Micrometer tags instead.
2. **Alpine IPv6** — `localhost` resolves to `::1` in Alpine. All health checks use `127.0.0.1`.
3. **Mock payload size** — 500 items = 224KB. Reduced to 150 items ≈ 47KB.
4. **k6 handleSummary** — Must return actual text for stdout; returning empty string suppresses output.
5. **Histogram buckets missing** — By default, Spring Boot does NOT publish `http_server_requests_seconds_bucket`. Must set `management.metrics.distribution.percentiles-histogram.http.server.requests: true` in application.yml. Without this, `histogram_quantile()` in Grafana returns no data.

## Scenario 1 Results (BFF-Blocking + ParallelGC — old tuning with NewRatio=1, SurvivorRatio=6)

> **Note**: This was run with the previous ParallelGC tuning (`-XX:NewRatio=1 -XX:SurvivorRatio=6`). The new scenario structure uses "default" (no tuning) and "production-tuned" (from real production experience). This data will be replaced when the new scenarios are run.

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
- Prometheus auto-deletes data older than 3 hours (configured retention)
- k6 NDJSON files are large (3-4 GB each); summary JSONs are ~1 KB
- To start fresh: `docker compose down -v` then `docker compose up -d mock-backend prometheus grafana`
