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
│   └── provisioning/       # Auto-configured datasource + unified dashboard
│       └── dashboards/
│           └── bff-comprehensive.json   # Unified 22-panel dashboard (6 rows)
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
docker compose run --rm -e BASE_URL=http://<sut-service>:8080 -e SCENARIO_NAME=<name> k6 run --out json=//results/<output>.json //k6/stress-test.js
```

The `--rm` flag removes the k6 container after the test. The `SCENARIO_NAME` env var sets the summary file name.

### Test Scenarios

| # | SUT | GC Strategy | Profile | BASE_URL | SCENARIO_NAME |
|---|-----|-------------|---------|----------|---------------|
| 1 | BFF-Blocking (Undertow) | ParallelGC **default** (no tuning) | `blocking` | `http://bff-blocking:8080` | `blocking-parallelgc-default` |
| 2 | BFF-Blocking (Undertow) | ParallelGC **production-tuned** | `blocking` | `http://bff-blocking:8080` | `blocking-parallelgc-tuned` |
| 3 | BFF-Blocking (Undertow) | Generational ZGC | `blocking` | `http://bff-blocking:8080` | `blocking-zgc` |
| 4 | BFF-Reactive (Netty) | ParallelGC **default** (no tuning) | `reactive` | `http://bff-reactive:8080` | `reactive-parallelgc-default` |
| 5 | BFF-Reactive (Netty) | ParallelGC **production-tuned** | `reactive` | `http://bff-reactive:8080` | `reactive-parallelgc-tuned` |
| 6 | BFF-Reactive (Netty) | Generational ZGC | `reactive` | `http://bff-reactive:8080` | `reactive-zgc` |
| 7 | BFF-Golang | Go runtime GC | `golang` | `http://bff-golang:8080` | `golang` |

> **Scenarios 1 vs 2** (and 4 vs 5) demonstrate the real-world impact of GC tuning — from default ParallelGC behavior to production-hardened parameters that halved response time in production.

---

### Scenario 1: BFF-Blocking + ParallelGC (Default — No Tuning)

This is the baseline — ParallelGC with only fixed heap size, letting the JVM use all defaults (adaptive sizing, default generation ratios).

```bash
# Start the SUT with default ParallelGC (no tuning)
docker compose --profile blocking up -d bff-blocking

# Wait for it to be healthy
docker compose ps

# Run k6 stress test (10 minutes)
docker compose run --rm -e BASE_URL=http://bff-blocking:8080 -e SCENARIO_NAME=blocking-parallelgc-default k6 run --out json=//results/blocking-parallelgc-default.json //k6/stress-test.js

# Rename the GC log before the next test
move results\gc.log results\gc-blocking-parallelgc-default.log

# Stop ONLY the SUT (keeps mock-backend, prometheus, grafana running)
docker compose stop bff-blocking && docker compose rm -f bff-blocking
```

**GC logs** are automatically saved to `results/gc.log` via the mounted volume.

> ⚠️ **Do NOT use `docker compose --profile blocking down`** — it stops ALL containers including infrastructure. Use `docker compose stop <service>` to stop only the SUT.

---

### Scenario 2: BFF-Blocking + ParallelGC (Production-Tuned)

These parameters were derived from real production GC tuning iterations. They fix the young generation size, disable adaptive sizing, and tune survivor ratios to prevent the JVM from shrinking Eden based on throughput goals.

```bash
# Stop previous SUT if running
docker compose stop bff-blocking && docker compose rm -f bff-blocking

# Start with production-tuned ParallelGC flags
docker compose --profile blocking up -d bff-blocking -e "JAVA_OPTS=-XX:+UseParallelGC -XX:MaxGCPauseMillis=200 -XX:GCTimeRatio=9 -XX:SurvivorRatio=4 -XX:ParallelGCThreads=2 -XX:NewSize=650m -XX:MaxNewSize=750m -XX:-UseAdaptiveSizePolicy -XX:MaxHeapFreeRatio=100 -Xms1536m -Xmx1536m -Xlog:gc*:file=/results/gc.log:time,uptime,level,tags:filecount=5,filesize=10m"

docker compose ps

docker compose run --rm -e BASE_URL=http://bff-blocking:8080 -e SCENARIO_NAME=blocking-parallelgc-tuned k6 run --out json=//results/blocking-parallelgc-tuned.json //k6/stress-test.js

move results\gc.log results\gc-blocking-parallelgc-tuned.log
docker compose stop bff-blocking && docker compose rm -f bff-blocking
```

---

### Scenario 3: BFF-Blocking + Generational ZGC

```bash
docker compose stop bff-blocking && docker compose rm -f bff-blocking

# Start with ZGC flags by overriding JAVA_OPTS
docker compose --profile blocking up -d bff-blocking -e "JAVA_OPTS=-XX:+UseZGC -XX:+ZGenerational -Xms1536m -Xmx1536m -Xlog:gc*:file=/results/gc.log:time,uptime,level,tags:filecount=5,filesize=10m"

docker compose ps

docker compose run --rm -e BASE_URL=http://bff-blocking:8080 -e SCENARIO_NAME=blocking-zgc k6 run --out json=//results/blocking-zgc.json //k6/stress-test.js

move results\gc.log results\gc-blocking-zgc.log
docker compose stop bff-blocking && docker compose rm -f bff-blocking
```

---

### Scenario 4: BFF-Reactive + ParallelGC (Default — No Tuning)

```bash
docker compose --profile reactive up -d bff-reactive
docker compose ps

docker compose run --rm -e BASE_URL=http://bff-reactive:8080 -e SCENARIO_NAME=reactive-parallelgc-default k6 run --out json=//results/reactive-parallelgc-default.json //k6/stress-test.js

move results\gc.log results\gc-reactive-parallelgc-default.log
docker compose stop bff-reactive && docker compose rm -f bff-reactive
```

---

### Scenario 5: BFF-Reactive + ParallelGC (Production-Tuned)

```bash
docker compose --profile reactive up -d bff-reactive -e "JAVA_OPTS=-XX:+UseParallelGC -XX:MaxGCPauseMillis=200 -XX:GCTimeRatio=9 -XX:SurvivorRatio=4 -XX:ParallelGCThreads=2 -XX:NewSize=650m -XX:MaxNewSize=750m -XX:-UseAdaptiveSizePolicy -XX:MaxHeapFreeRatio=100 -Xms1536m -Xmx1536m -Xlog:gc*:file=/results/gc.log:time,uptime,level,tags:filecount=5,filesize=10m"
docker compose ps

docker compose run --rm -e BASE_URL=http://bff-reactive:8080 -e SCENARIO_NAME=reactive-parallelgc-tuned k6 run --out json=//results/reactive-parallelgc-tuned.json //k6/stress-test.js

move results\gc.log results\gc-reactive-parallelgc-tuned.log
docker compose stop bff-reactive && docker compose rm -f bff-reactive
```

---

### Scenario 6: BFF-Reactive + Generational ZGC

```bash
docker compose --profile reactive up -d bff-reactive -e "JAVA_OPTS=-XX:+UseZGC -XX:+ZGenerational -Xms1536m -Xmx1536m -Xlog:gc*:file=/results/gc.log:time,uptime,level,tags:filecount=5,filesize=10m"
docker compose ps

docker compose run --rm -e BASE_URL=http://bff-reactive:8080 -e SCENARIO_NAME=reactive-zgc k6 run --out json=//results/reactive-zgc.json //k6/stress-test.js

move results\gc.log results\gc-reactive-zgc.log
docker compose stop bff-reactive && docker compose rm -f bff-reactive
```

---

### Scenario 7: BFF-Golang

```bash
docker compose --profile golang up -d bff-golang
docker compose ps

docker compose run --rm -e BASE_URL=http://bff-golang:8080 -e SCENARIO_NAME=golang k6 run --out json=//results/golang.json //k6/stress-test.js

docker compose stop bff-golang && docker compose rm -f bff-golang
```

---

## Analyzing Results

### k6 Test Summary (auto-generated)

Each k6 run automatically generates a compact summary JSON at `results/summary-<scenario>.json`. The k6 script also prints a formatted summary to the terminal at the end of the test.

### Python Analyzer (for detailed analysis)

For a more detailed analysis including request timing breakdown:

```bash
python k6/analyze-k6.py results/blocking-parallelgc-default.json
```

Output includes:
- **Status code breakdown** (2xx, 4xx, 5xx, timeouts)
- **Latency percentiles** (p50, p90, p95, p99, p99.9)
- **Request timing breakdown** (connect, TLS, sending, waiting, receiving)
- **Throughput** (req/s, data transferred)
- **Error rate**

Saves a compact JSON to `results/summary-<name>.json`.

### Comparing Scenarios

After running all 7 scenarios, compare the summary files:

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

### Scenario A: ParallelGC (Default — No Tuning)

```bash
-XX:+UseParallelGC \
-Xms1536m \
-Xmx1536m \
-Xlog:gc*:file=/results/gc.log:time,uptime,level,tags:filecount=5,filesize=10m
```

| Flag | Purpose |
|------|---------|
| `-XX:+UseParallelGC` | Use the parallel scavenge collector |
| `-Xms1536m -Xmx1536m` | Fixed heap at 1.5GB (leaves ~512MB for native) |
| `-Xlog:gc*...` | GC logging with rotation (5 files × 10MB max) |

> **Behavior**: The JVM uses default adaptive sizing (`UseAdaptiveSizePolicy` is on by default). It dynamically adjusts Eden/Survivor/Old generation sizes based on `MaxGCPauseMillis` (default 200ms) and `GCTimeRatio` (default 99). This often leads to the JVM shrinking Eden to meet pause goals, causing more frequent GC events.

### Scenario B: ParallelGC (Production-Tuned)

```bash
-XX:+UseParallelGC \
-XX:MaxGCPauseMillis=200 \
-XX:GCTimeRatio=9 \
-XX:SurvivorRatio=4 \
-XX:ParallelGCThreads=2 \
-XX:NewSize=650m \
-XX:MaxNewSize=750m \
-XX:-UseAdaptiveSizePolicy \
-XX:MaxHeapFreeRatio=100 \
-Xms1536m \
-Xmx1536m \
-Xlog:gc*:file=/results/gc.log:time,uptime,level,tags:filecount=5,filesize=10m
```

| Flag | Purpose |
|------|---------|
| `-XX:+UseParallelGC` | Use the parallel scavenge collector |
| `-XX:MaxGCPauseMillis=200` | Target max GC pause of 200ms (hint to GC) |
| `-XX:GCTimeRatio=9` | Target ~10% of time in GC (1/(1+9) = 10%) |
| `-XX:SurvivorRatio=4` | Each survivor = 1/4 of young gen (larger survivors = less promotion) |
| `-XX:ParallelGCThreads=2` | Match container CPU limit (2 cores) |
| `-XX:NewSize=650m` | Fix minimum young gen to 650MB |
| `-XX:MaxNewSize=750m` | Cap young gen at 750MB (~47% of 1536m heap) |
| `-XX:-UseAdaptiveSizePolicy` | **Disable** adaptive sizing — prevents JVM from shrinking Eden |
| `-XX:MaxHeapFreeRatio=100` | Don't shrink heap after GC (avoids unnecessary resize) |
| `-Xms1536m -Xmx1536m` | Fixed heap at 1.5GB |
| `-Xlog:gc*...` | GC logging with rotation |

> **Why this matters**: In production, the default adaptive sizing caused the JVM to shrink Eden space to meet throughput/pause goals, resulting in more frequent minor GCs. By fixing the young gen size and disabling adaptive sizing, GC events became less frequent and response time dropped by ~50%. The `GCTimeRatio=9` (vs default 99) tells the JVM that spending up to 10% of time in GC is acceptable, which prevents it from over-tuning for throughput at the expense of latency.

### Scenario C: Generational ZGC

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

## Further Reading

📖 **[ParallelGC Optimization Journey →](docs/gc-optimization-journey.md)** — A real-world case study of GC tuning for a high-throughput BFF application. Covers 4 iterations of JVM parameter tuning, from 3-second Full GC pauses to halved response time. Includes detailed flag explanations, memory layout diagrams, and the reasoning behind each change.

---

## Grafana Dashboards

Two dashboards are auto-provisioned:

### BFF JVM Tuning - Comprehensive (recommended)

22 panels in 6 rows:

| Row | Panels |
|-----|--------|
| **HTTP Latency & Throughput** | Latency (avg/max + percentiles), Requests/sec |
| **CPU & Memory** | CPU gauge, Heap by pool (Eden/Survivor/Old Gen stacked), Non-heap (Metaspace/CodeHeap) |
| **GC Analysis** | GC pause time/s (Young vs Full), GC count rate, Allocation rate (Eden), Promotion rate (Old Gen) |
| **Memory Pool Details** | Eden used vs max, Survivor used vs max, Old Gen used vs max, Thread count, Total heap used vs max |
| **Threads & Heap** | Live threads, Total heap used vs committed |
| **Outbound Connection Pool** | Active connections, Idle connections, Pending requests, Pool summary, Utilization % |

Use the **`application` dropdown** at the top to switch between `bff-blocking`, `bff-reactive`, `bff-golang`.

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
Select-String "Pause" results\gc-blocking-parallelgc-default.log | Measure-Object -Line

# Find the longest pause
Select-String "Pause Young" results\gc-blocking-parallelgc-default.log |
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

### Switching SUT variants (between scenarios)

To stop **only** the SUT container while keeping infrastructure (mock-backend, prometheus, grafana) running:

```bash
# Stop and remove only the SUT
docker compose stop bff-blocking && docker compose rm -f bff-blocking

# Then start the next variant
docker compose --profile reactive up -d bff-reactive
```

> ⚠️ **Do NOT use `docker compose --profile blocking down`** between scenarios — it stops ALL containers including mock-backend, prometheus, and grafana. Use `docker compose stop <service>` instead.

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
docker compose run --rm -e BASE_URL=http://bff-blocking:8080 -e SCENARIO_NAME=blocking-parallelgc-default k6 run --out json=//results/blocking-parallelgc-default.json //k6/stress-test.js
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
