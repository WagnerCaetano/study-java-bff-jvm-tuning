const http = require('http');

const PORT = 8081;
const LATENCY_MS = 20;

// Pre-generate a ~50KB JSON payload at startup
function generatePayload() {
    const items = [];
    for (let i = 0; i < 150; i++) {
        items.push({
            id: i,
            name: `item-${i}-` + 'x'.repeat(10),
            description: `Description for item ${i}`,
            category: `category-${i % 20}`,
            tags: [`tag-${i % 50}`, `group-${i % 30}`],
            status: ['active', 'inactive', 'pending', 'archived'][i % 4],
            value: Math.random() * 10000,
            metadata: {
                created: new Date(Date.now() - Math.random() * 86400000 * 365).toISOString(),
                updated: new Date().toISOString(),
                version: `v${Math.floor(Math.random() * 10)}.${Math.floor(Math.random() * 100)}`,
                source: `source-${i % 15}`,
                region: ['us-east', 'us-west', 'eu-west', 'eu-central', 'ap-south'][i % 5]
            }
        });
    }
    return JSON.stringify({ data: items, total: items.length, timestamp: new Date().toISOString() });
}

const payload = generatePayload();
const payloadSize = Buffer.byteLength(payload);
console.log(`Payload generated: ${payloadSize} bytes (~${(payloadSize / 1024).toFixed(1)} KB)`);

const server = http.createServer((req, res) => {
    // Health check endpoint
    if (req.url === '/health' && req.method === 'GET') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ status: 'UP' }));
        return;
    }

    // Main data endpoint
    if (req.url === '/api/data' && req.method === 'GET') {
        setTimeout(() => {
            res.writeHead(200, {
                'Content-Type': 'application/json',
                'X-Payload-Size': payloadSize
            });
            res.end(payload);
        }, LATENCY_MS);
        return;
    }

    // 404 for everything else
    res.writeHead(404, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'Not Found' }));
});

server.listen(PORT, '0.0.0.0', () => {
    console.log(`Mock Backend listening on port ${PORT}`);
    console.log(`  GET /api/data  -> ${payloadSize} bytes with ${LATENCY_MS}ms delay`);
    console.log(`  GET /health    -> health check`);
});
