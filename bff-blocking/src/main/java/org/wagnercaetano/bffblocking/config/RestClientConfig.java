package org.wagnercaetano.bffblocking.config;

import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.binder.MeterBinder;
import org.apache.hc.client5.http.impl.io.PoolingHttpClientConnectionManager;
import org.springframework.boot.web.client.RestClientCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.HttpComponentsClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

@Configuration
public class RestClientConfig {

    @Bean
    public PoolingHttpClientConnectionManager connectionManager() {
        // Default pool: maxTotal=25, defaultMaxPerRoute=5
        // Keeping defaults to observe behavior — tune later.
        return new PoolingHttpClientConnectionManager();
    }

    @Bean
    public RestClient restClient(RestClient.Builder builder, PoolingHttpClientConnectionManager connectionManager) {
        var httpClient = org.apache.hc.client5.http.impl.classic.HttpClients.custom()
                .setConnectionManager(connectionManager)
                .build();

        HttpComponentsClientHttpRequestFactory factory = new HttpComponentsClientHttpRequestFactory(httpClient);

        return builder
                .baseUrl("http://mock-backend:8081")
                .requestFactory(factory)
                .build();
    }

    /**
     * Expose Apache HttpClient5 connection pool stats as Micrometer gauges.
     * Metrics registered:
     *   httpclient.pool.active   — connections with active requests (leased)
     *   httpclient.pool.idle     — idle connections available for reuse
     *   httpclient.pool.pending  — requests waiting for a connection
     *   httpclient.pool.max      — max connections allowed in the pool
     */
    @Bean
    public MeterBinder connectionPoolMetrics(PoolingHttpClientConnectionManager cm) {
        return registry -> {
            Gauge.builder("httpclient.pool.active", cm, c -> c.getTotalStats().getLeased())
                    .description("Active connections in the pool")
                    .register(registry);
            Gauge.builder("httpclient.pool.idle", cm, c -> c.getTotalStats().getAvailable())
                    .description("Idle connections in the pool")
                    .register(registry);
            Gauge.builder("httpclient.pool.pending", cm, c -> c.getTotalStats().getPending())
                    .description("Pending requests waiting for a connection")
                    .register(registry);
            Gauge.builder("httpclient.pool.max", cm, c -> (double) c.getTotalStats().getMax())
                    .description("Max connections allowed in the pool")
                    .register(registry);
        };
    }
}
