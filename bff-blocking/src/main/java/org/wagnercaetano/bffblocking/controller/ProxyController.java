package org.wagnercaetano.bffblocking.controller;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestClient;

/**
 * Blocking proxy controller that forwards requests to the mock backend.
 * Uses RestClient (blocking) to call the downstream service.
 * Returns raw JSON string to force full memory allocation per request.
 */
@RestController
public class ProxyController {

    private static final Logger log = LoggerFactory.getLogger(ProxyController.class);

    private final RestClient restClient;

    public ProxyController(RestClient restClient) {
        this.restClient = restClient;
    }

    @GetMapping(value = "/api/data", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<String> proxyData() {
        String responseBody = restClient.get()
                .uri("/api/data")
                .accept(MediaType.APPLICATION_JSON)
                .retrieve()
                .body(String.class);

        return ResponseEntity.ok()
                .contentType(MediaType.APPLICATION_JSON)
                .body(responseBody);
    }

    @GetMapping("/health")
    public ResponseEntity<String> health() {
        return ResponseEntity.ok("{\"status\":\"UP\"}");
    }
}
