package org.wagnercaetano.bffreactive.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.netty.http.client.HttpClient;
import reactor.netty.resources.ConnectionProvider;

import java.time.Duration;

@Configuration
public class WebClientConfig {

    @Bean
    public WebClient webClient(WebClient.Builder builder) {
        // Named ConnectionProvider so Reactor Netty registers pool metrics with Micrometer:
        //   reactor.netty.connection.provider.active.connections  (gauge)
        //   reactor.netty.connection.provider.idle.connections    (gauge)
        //   reactor.netty.connection.provider.pending.connections (gauge)
        //
        // Default pool size = 2 * availableProcessors.
        // Keeping defaults to observe the bottleneck — tune later.
        ConnectionProvider provider = ConnectionProvider.builder("mock-backend")
                .maxConnections(2 * Runtime.getRuntime().availableProcessors())
                .pendingAcquireMaxCount(2 * 2 * Runtime.getRuntime().availableProcessors())
                .pendingAcquireTimeout(Duration.ofSeconds(45))
                .build();

        HttpClient httpClient = HttpClient.create(provider)
                .responseTimeout(Duration.ofSeconds(10));

        return builder
                .baseUrl("http://mock-backend:8081")
                .clientConnector(new ReactorClientHttpConnector(httpClient))
                .build();
    }
}
