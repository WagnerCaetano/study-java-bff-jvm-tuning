# BFF JVM Tuning PoC

A local Docker-based environment to stress test a Backend-for-Frontend (BFF) application, comparing **Java 24 (Blocking/Undertow vs Reactive/Netty)** and **Golang** under high memory allocation scenarios with real-time Prometheus + Grafana observability.

## Architecture

```
k6 (Docker) ──► SUT (:8080) ──► Mock Backend (:8081)
                    │
                    ▼
              Prometheus (:9090) ──► Grafana (:3000)
```

All services run on a shared Docker bridge network (`bff-net`). k6 accesses the SUT via Docker service name (e.g., `http://bff-blocking:8080`).

## Prerequisites

- **Docker** with Docker Compose v2+
- **Python 3** (for the k6 results analyzer)
- **6 CPU cores / 32GB RAM** recommended (Docker will use ~5 cores / ~4.5GB)

> **No host-side k6 installation needed** — k6 runs inside Docker via `docker compose run`.

---

## File Structure

```
├── mock-backend/           # Node.js mock service (~50KB JSON, 20ms delay)
│   ├── server.js
│   ├── package.json
│   └── Dockerfile
├── bff-blocking/           # Java 24 + Undertow + RestClient
│   ├── pom.xml
│   ├── Dockerfile
│   └── src/main/java/.../
├── bff-reactive/           # Java 24 + Netty + WebClient
│   ├── pom.xml
│   ├── Dockerfile
│   └── src/main/java/.../
├── bff-golang/             # Go 1.22 HTTP proxy
│   ├── main.go
│   ├── go.mod
│   └── Dockerfile
├── k6/
│   ├── stress-test.js      # 10-min load test (200 VUs) with status tracking
│   └── analyze-k6.py       # Python analyzer for k6 NDJSON results
├── prometheus/
│   └── prometheus.yml      # Scrape config (5s interval)
├── grafana/
│   └── provisioning/       # Auto-configured datasource + 2 dashboards
│       └── dashboards/
│           ├── bff-overview.json        # Original 9-panel dashboard
│           └── bff-comprehensive.json   # Comprehensive 16-panel dashboard
├── docker-compose.yml      # Full orchestration with profiles
├── results/                # k6 output + GC logs + summaries (mounted volume)
└── plans/
    ├── plan.md             # Detailed architecture plan
    └── agents.md           # AI agent context document
```

---

## Data Sources Explained

| Source | What It Contains | Typical Size | Purpose |
|--------|-----------------|-------------|---------|
| **k6 NDJSON** (`results/*.json`) | Every HTTP request, timing, check result from k6 | 3–4 GB | Full post-hoc analysis |
| **k6 Summary** (`results/summary-*.json`) | Compact JSON: status codes, latency percentiles, throughput | ~1 KB | Quick comparison across scenarios |
| **Prometheus** | JVM metrics scraped every 5s from `/actuator/prometheus` | In-memory (Docker volume) | Real-time JVM/HTTP metrics |
| **Grafana** | Visualizes Prometheus data in dashboards | — | Live monitoring during tests |
| **GC log** (`results/gc-*.log`) | JVM unified GC logging — every GC event with pause times | ~400 KB | Detailed GC analysis |

> **These are completely separate data sources.** k6 JSON is client-side load test data. Prometheus/Grafana is server-side JVM internals. GC log is the deepest JVM garbage collection detail.

---

## Quick Start

### Step 1: Build All Images

```bash
docker compose build
```

### Step 2: Start Infrastructure (Mock + Prometheus + Grafana)

```bash
docker compose up -d mock-backend prometheus grafana
```

Wait for services to be healthy:

```bash
docker compose ps
```

All three should show `healthy` status.

### Step 3: Open Grafana

Open [http://localhost:3000](http://localhost:3000) in your browser.

- **Username:** `admin`
- **Password:** `admin`

Two dashboards are pre-loaded:
- **"BFF JVM Tuning - Comprehensive"** (16 panels — recommended)
- **"BFF JVM Tuning Overview"** (9 panels — original)

---

## Running the Tests

### How k6 Works in Docker

k6 runs as a one-off container via `docker compose run --rm`. It connects to the SUT using Docker service names:

```bash
# General pattern:
docker compose run --rm -e BASE_URL=http://<sut-service>:8080 -e SCENARIO_NAME=<name> k6 run --out json=/results/<output>.json /k6/stress-test.js
```

The `--rm` flag removes the k6 container after the test. The `SCENARIO_NAME` env var sets the summary file name.

### Test Scenarios

| # | SUT | GC Strategy | Profile | BASE_URL | SCENARIO_NAME |
|---|-----|-------------|---------|----------|---------------|
| 1 | BFF-Blocking (Undertow) | ParallelGC tuned | `blocking` | `http://bff-blocking:8080` | `blocking-parallelgc` |
| 2 | BFF-Blocking (Undertow) | Generational ZGC | `blocking` | `http://bff-blocking:8080` | `blocking-zgc` |
| 3 | BFF-Reactive (Netty) | ParallelGC tuned | `reactive` | `http://bff-reactive:8080` | `reactive-parallelgc` |
| 4 | BFF-Reactive (Netty) | Generational ZGC | `reactive` | `http://bff-reactive:8080` | `reactive-zgc` |
| 5 | BFF-Golang | Go runtime GC | `golang` | `http://bff-golang:8080` | `golang` |

---

### Scenario 1: BFF-Blocking + ParallelGC (Tuned)

```bash
# Start the SUT with ParallelGC flags
docker compose --profile blocking up -d bff-blocking

# Wait for it to be healthy
docker compose ps

# Run k6 stress test (10 minutes)
docker compose run --rm -e BASE_URL=http://bff-blocking:8080 -e SCENARIO_NAME=blocking-parallelgc k6 run --out json=/results/blocking-parallelgc.json /k6/stress-test.js

# Rename the GC log before the next test
move results\gc.log results\gc-blocking-parallelgc.log

# Stop the SUT
docker compose --profile blocking down
```

**GC logs** are automatically saved to `results/gc.log` via the mounted volume.

---

### Scenario 2: BFF-Blocking + Generational ZGC

```bash
docker compose --profile blocking down

# Start with ZGC flags by overriding JAVA_OPTS
docker compose --profile blocking up -d bff-blocking -e "JAVA_OPTS=-XX:+UseZGC -XX:+ZGenerational -Xms1536m -Xmx1536m -Xlog:gc*:file=/results/gc.log:time,uptime,level,tags:filecount=5,filesize=10m"

docker compose ps

docker compose run --rm -e BASE_URL=http://bff-blocking:8080 -e SCENARIO_NAME=blocking-zgc k6 run --out json=/results/blocking-zgc.json /k6/stress-test.js

move results\gc.log results\gc-blocking-zgc.log
docker compose --profile blocking down
```

---

### Scenario 3: BFF-Reactive + ParallelGC (Tuned)

```bash
docker compose --profile reactive up -d bff-reactive
docker compose ps

docker compose run --rm -e BASE_URL=http://bff-reactive:8080 -e SCENARIO_NAME=reactive-parallelgc k6 run --out json=/results/reactive-parallelgc.json /k6/stress-test.js

move results\gc.log results\gc-reactive-parallelgc.log
docker compose --profile reactive down
```

---

### Scenario 4: BFF-Reactive + Generational ZGC

```bash
docker compose --profile reactive up -d bff-reactive -e "JAVA_OPTS=-XX:+UseZGC -XX:+ZGenerational -Xms1536m -Xmx1536m -Xlog:gc*:file=/results/gc.log:time,uptime,level,tags:filecount=5,filesize=10m"
docker compose ps

docker compose run --rm -e BASE_URL=http://bff-reactive:8080 -e SCENARIO_NAME=reactive-zgc k6 run --out json=/results/reactive-zgc.json /k6/stress-test.js

move results\gc.log results\gc-reactive-zgc.log
docker compose --profile reactive down
```

---

### Scenario 5: BFF-Golang

```bash
docker compose --profile golang up -d bff-golang
docker compose ps

docker compose run --rm -e BASE_URL=http://bff-golang:8080 -e SCENARIO_NAME=golang k6 run --out json=/results/golang.json /k6/stress-test.js

docker compose --profile golang down
```

---

## Analyzing Results

### k6 Test Summary (auto-generated)

Each k6 run automatically generates a compact summary JSON at `results/summary-<scenario>.json`. The k6 script also prints a formatted summary to the terminal at the end of the test.

### Python Analyzer (for detailed analysis)

For a more detailed analysis including request timing breakdown:

```bash
python k6/analyze-k6.py results/blocking-parallelgc.json
```

Output includes:
- **Status code breakdown** (2xx, 4xx, 5xx, timeouts)
- **Latency percentiles** (p50, p90, p95, p99, p99.9)
- **Request timing breakdown** (connect, TLS, sending, waiting, receiving)
- **Throughput** (req/s, data transferred)
- **Error rate**

Saves a compact JSON to `results/summary-<name>.json`.

### Comparing Scenarios

After running all 5 scenarios, compare the summary files:

```powershell
# View all summaries side by side
Get-ChildItem results\summary-*.json | ForEach-Object {
    $json = Get-Content $_.FullName | ConvertFrom-Json
    Write-Host "`n$($_.Name):"
    Write-Host "  Requests: $($json.requests.total) | 2xx: $($json.status_codes.'2xx') | 5xx: $($json.status_codes.'5xx')"
    Write-Host "  p50: $($json.latency_ms.p50)ms | p95: $($json.latency_ms.p95)ms | p99: $($json.latency_ms.p99)ms"
    Write-Host "  Req/s: $($json.requests.rate_per_sec) | Errors: $($json.errors.error_rate)%"
}
```

---

## JVM Flags Reference

### Scenario A: ParallelGC (Tuned)

```bash
-XX:+UseParallelGC \
-XX:NewRatio=1 \
-XX:SurvivorRatio=6 \
-Xms1536m \
-Xmx1536m \
-Xlog:gc*:file=/results/gc.log:time,uptime,level,tags:filecount=5,filesize=10m
```

| Flag | Purpose |
|------|---------|
| `-XX:+UseParallelGC` | Use the parallel scavenge collector |
| `-XX:NewRatio=1` | Young Gen = Old Gen (50/50 split) |
| `-XX:SurvivorRatio=6` | Each survivor space = 1/6 of Young Gen |
| `-Xms1536m -Xmx1536m` | Fixed heap at 1.5GB (leaves ~512MB for native) |
| `-Xlog:gc*...` | GC logging with rotation (5 files × 10MB max) |

### Scenario B: Generational ZGC

```bash
-XX:+UseZGC \
-XX:+ZGenerational \
-Xms1536m \
-Xmx1536m \
-Xlog:gc*:file=/results/gc.log:time,uptime,level,tags:filecount=5,filesize=10m
```

| Flag | Purpose |
|------|---------|
| `-XX:+UseZGC` | Use Z Garbage Collector |
| `-XX:+ZGenerational` | Enable generational mode (Java 21+) |
| `-Xms1536m -Xmx1536m` | Fixed heap at 1.5GB |
| `-Xlog:gc*...` | GC logging with rotation |

---

## Grafana Dashboards

Two dashboards are auto-provisioned:

### BFF JVM Tuning - Comprehensive (recommended)

16 panels in 4 rows:

| Row | Panels |
|-----|--------|
| **HTTP Latency & Throughput** | Latency percentiles (p50/p90/p95/p99), Requests/sec |
| **CPU & Memory** | CPU gauge, Heap by pool (Eden/Survivor/Old Gen stacked), Non-heap (Metaspace/CodeHeap) |
| **GC Analysis** | GC pause time/s (Young vs Full), GC count rate, Allocation rate (Eden), Promotion rate (Old Gen) |
| **Memory Pool Details** | Eden used vs max, Survivor used vs max, Old Gen used vs max, Thread count, Total heap used vs max |

Use the **`application` dropdown** at the top to switch between `bff-blocking`, `bff-reactive`, `bff-golang`.

### BFF JVM Tuning Overview (original)

9 panels covering HTTP latency, req/s, JVM heap, non-heap, GC pauses, GC count, threads, CPU.

---

## GC Log Analysis

GC logs are written in unified JVM logging format. Analyze them with:

### Using GCViewer

1. Download [GCViewer](https://github.com/chewiebug/GCViewer)
2. Open `results/gc-*.log` files
3. Compare pause times, throughput, and allocation rates

### Using Command Line

```powershell
# Quick summary of GC pauses
Select-String "Pause" results\gc-blocking-parallelgc.log | Measure-Object -Line

# Find the longest pause
Select-String "Pause Young" results\gc-blocking-parallelgc.log |
  ForEach-Object { $_.Line } | Sort-Object -Descending | Select-Object -First 5
```

---

## Observability

| Service | URL | Credentials |
|---------|-----|-------------|
| Grafana | [http://localhost:3000](http://localhost:3000) | admin / admin |
| Prometheus | [http://localhost:9090](http://localhost:9090) | — |
| Mock Backend Health | [http://localhost:8081/health](http://localhost:8081/health) | — |
| SUT Health | [http://localhost:8080/health](http://localhost:8080/health) | — |
| SUT Prometheus Metrics | [http://localhost:8080/actuator/prometheus](http://localhost:8080/actuator/prometheus) | — |

---

## Stopping & Cleanup

### Stop everything (preserve data)

```bash
docker compose --profile blocking --profile reactive --profile golang down
```

This stops and removes all containers but **preserves**:
- Prometheus data (in Docker volume `prometheus-data`)
- Grafana data (in Docker volume `grafana-data`)
- k6 results and GC logs (in `./results/`)

### Full cleanup (remove all data)

```bash
# Stop containers + remove volumes (Prometheus + Grafana data)
docker compose --profile blocking --profile reactive --profile golang down -v

# Also remove built images
docker compose --profile blocking --profile reactive --profile golang down -v --rmi local
```

### Clean up results folder

```bash
# Delete k6 NDJSON files (large, can be regenerated from summaries)
del results\*.json

# Keep only summaries and GC logs
# (summary-*.json and gc-*.log files)
```

### Prometheus Data Management

Prometheus stores data in the `prometheus-data` Docker volume. The current config sets:
- `--storage.tsdb.retention.time=3h` — auto-deletes data older than 3 hour
- Data is **NOT** lost when you stop containers (it persists in the volume)
- Data **IS** lost when you run `docker compose down -v` (removes volumes)
- To manually purge: `docker compose down -v && docker compose up -d mock-backend prometheus grafana`

### Starting Over Another Day

```bash
# 1. Full cleanup from previous session
docker compose --profile blocking --profile reactive --profile golang down -v

# 2. Start infrastructure fresh
docker compose up -d mock-backend prometheus grafana

# 3. Wait for healthy
docker compose ps

# 4. Run your next test
docker compose --profile blocking up -d bff-blocking
docker compose run --rm -e BASE_URL=http://bff-blocking:8080 -e SCENARIO_NAME=blocking-parallelgc k6 run --out json=/results/blocking-parallelgc.json /k6/stress-test.js
```

---

## Resource Budget

| Service | CPU | RAM | Notes |
|---------|-----|-----|-------|
| mock-backend | 0.5 | 512MB | Lightweight Node.js |
| SUT (active) | 2.0 | 2GB | Java or Go |
| Prometheus | 1.0 | 1GB | Metrics storage |
| Grafana | 0.5 | 512MB | Dashboard rendering |
| k6 (during test) | 1.0 | 512MB | Load generator (one-off) |
| **Total (peak)** | **5.0** | **~4.5GB** | Leaves 1 core for host OS |

---

## Troubleshooting

### Container won't start / OOMKilled

```bash
docker compose logs bff-blocking
docker stats
# If OOMKilled, reduce heap: -Xms1280m -Xmx1280m
```

### k6 connection refused

```bash
docker compose ps  # SUT must show "healthy"
curl http://localhost:8080/api/data  # Test from host
```

### Grafana dashboard not showing data

1. Check Prometheus targets: [http://localhost:9090/targets](http://localhost:9090/targets)
2. Ensure the SUT is running and the `application` variable matches
3. Set time range to "Last 15 minutes"

### Port already in use

```bash
netstat -ano | findstr :8080
taskkill /PID <pid> /F
```
