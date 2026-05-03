import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';

// Custom metrics
const errorRate = new Rate('errors');
const latencyTrend = new Trend('latency');

// HTTP status code counters
const status2xx = new Counter('status_2xx');
const status4xx = new Counter('status_4xx');
const status5xx = new Counter('status_5xx');
const statusTimeout = new Counter('status_timeout');
const statusOther = new Counter('status_other');

// Test configuration: 10 minutes total
export const options = {
    stages: [
        { duration: '1m', target: 200 },   // Ramp up
        { duration: '8m', target: 200 },   // Sustain
        { duration: '1m', target: 0 },     // Ramp down
    ],
    thresholds: {
        http_req_duration: ['p(50)<100', 'p(95)<500', 'p(99)<1000'],
        http_req_failed: ['rate<0.05'],
        errors: ['rate<0.05'],
    },
    summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(50)', 'p(90)', 'p(95)', 'p(99)'],
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8080';

export default function () {
    const url = `${BASE_URL}/api/data`;

    const params = {
        headers: { 'Accept': 'application/json' },
        timeout: '30s',
    };

    const response = http.get(url, params);

    // Track status codes
    if (response.timings.duration >= 30000 || response.error_code === 1050) {
        statusTimeout.add(1);
    } else if (response.status >= 200 && response.status < 300) {
        status2xx.add(1);
    } else if (response.status >= 400 && response.status < 500) {
        status4xx.add(1);
    } else if (response.status >= 500 && response.status < 600) {
        status5xx.add(1);
    } else {
        statusOther.add(1);
    }

    // Check response
    const result = check(response, {
        'status is 200': (r) => r.status === 200,
        'has body': (r) => r.body && r.body.length > 0,
        'body is > 10KB': (r) => r.body && r.body.length > 10240,
    });

    errorRate.add(!result);
    latencyTrend.add(response.timings.duration);

    sleep(Math.random() * 0.1);
}

// Generate summary: save compact JSON + print readable text to stdout
export function handleSummary(data) {
    const m = data.metrics;
    const dur = m.http_req_duration ? m.http_req_duration.values : {};
    const c2xx = m.status_2xx ? m.status_2xx.values.count : 0;
    const c4xx = m.status_4xx ? m.status_4xx.values.count : 0;
    const c5xx = m.status_5xx ? m.status_5xx.values.count : 0;
    const cTimeout = m.status_timeout ? m.status_timeout.values.count : 0;
    const cOther = m.status_other ? m.status_other.values.count : 0;
    const totalReqs = c2xx + c4xx + c5xx + cTimeout + cOther;

    // Readable text summary for stdout
    const text = `
╔══════════════════════════════════════════════════════════════════╗
║                    K6 STRESS TEST SUMMARY                       ║
╠══════════════════════════════════════════════════════════════════╣
║ Test Info                                                        ║
║   Base URL     : ${BASE_URL.padEnd(48)}║
║   Duration     : ${(data.state.testRunDurationMs / 1000).toFixed(1).padEnd(8)}s                                    ║
║   Scenario     : ${(__ENV.SCENARIO_NAME || 'unnamed').padEnd(48)}║
╠══════════════════════════════════════════════════════════════════╣
║ HTTP Status Codes                                                ║
║   Total Requests: ${String(totalReqs).padEnd(47)}║
║   2xx (OK)     : ${String(c2xx).padEnd(47)}║
║   4xx (Client)  : ${String(c4xx).padEnd(47)}║
║   5xx (Server)  : ${String(c5xx).padEnd(47)}║
║   Timeouts      : ${String(cTimeout).padEnd(47)}║
║   Other         : ${String(cOther).padEnd(47)}║
╠══════════════════════════════════════════════════════════════════╣
║ Latency (ms)                                                     ║
║   Avg   : ${String(dur.avg ? dur.avg.toFixed(2) : 'N/A').padEnd(48)}║
║   Min   : ${String(dur.min ? dur.min.toFixed(2) : 'N/A').padEnd(48)}║
║   Med   : ${String(dur.med ? dur.med.toFixed(2) : 'N/A').padEnd(48)}║
║   Max   : ${String(dur.max ? dur.max.toFixed(2) : 'N/A').padEnd(48)}║
║   p50   : ${String(dur['p(50)'] ? dur['p(50)'].toFixed(2) : 'N/A').padEnd(48)}║
║   p90   : ${String(dur['p(90)'] ? dur['p(90)'].toFixed(2) : 'N/A').padEnd(48)}║
║   p95   : ${String(dur['p(95)'] ? dur['p(95)'].toFixed(2) : 'N/A').padEnd(48)}║
║   p99   : ${String(dur['p(99)'] ? dur['p(99)'].toFixed(2) : 'N/A').padEnd(48)}║
╠══════════════════════════════════════════════════════════════════╣
║ Throughput                                                        ║
║   Requests/sec  : ${String(m.http_reqs ? m.http_reqs.values.rate.toFixed(1) : 'N/A').padEnd(47)}║
║   Iterations    : ${String(m.iterations ? m.iterations.values.count : 'N/A').padEnd(47)}║
║   Iter/sec      : ${String(m.iterations ? m.iterations.values.rate.toFixed(1) : 'N/A').padEnd(47)}║
║   Data Received : ${String(m.data_received ? (m.data_received.values.count / 1024 / 1024).toFixed(1) + ' MB' : 'N/A').padEnd(47)}║
╠══════════════════════════════════════════════════════════════════╣
║ Errors                                                           ║
║   Error Rate    : ${String(m.errors ? (m.errors.values.rate * 100).toFixed(2) + '%' : 'N/A').padEnd(47)}║
║   HTTP Failed   : ${String(m.http_req_failed ? (m.http_req_failed.values.rate * 100).toFixed(2) + '%' : 'N/A').padEnd(47)}║
╚══════════════════════════════════════════════════════════════════╝
`;

    // Compact JSON summary for file
    const summary = {
        test_run: {
            scenario: __ENV.SCENARIO_NAME || 'unnamed',
            base_url: BASE_URL,
            test_duration_sec: data.state.testRunDurationMs / 1000,
            timestamp: new Date().toISOString(),
        },
        requests: {
            total: totalReqs,
            rate_per_sec: m.http_reqs ? m.http_reqs.values.rate : 0,
        },
        status_codes: {
            '2xx': c2xx,
            '4xx': c4xx,
            '5xx': c5xx,
            timeouts: cTimeout,
            other: cOther,
        },
        latency_ms: {
            avg: dur.avg || 0,
            min: dur.min || 0,
            med: dur.med || 0,
            max: dur.max || 0,
            p50: dur['p(50)'] || 0,
            p90: dur['p(90)'] || 0,
            p95: dur['p(95)'] || 0,
            p99: dur['p(99)'] || 0,
        },
        iterations: {
            total: m.iterations ? m.iterations.values.count : 0,
            rate_per_sec: m.iterations ? m.iterations.values.rate : 0,
        },
        errors: {
            error_rate: m.errors ? m.errors.values.rate : 0,
            http_failed_rate: m.http_req_failed ? m.http_req_failed.values.rate : 0,
        },
        data_received_mb: m.data_received ? m.data_received.values.count / 1024 / 1024 : 0,
        data_sent_mb: m.data_sent ? m.data_sent.values.count / 1024 / 1024 : 0,
    };

    const summaryFile = `/results/summary-${__ENV.SCENARIO_NAME || 'unnamed'}.json`;

    return {
        stdout: text,
        [summaryFile]: JSON.stringify(summary, null, 2),
    };
}
