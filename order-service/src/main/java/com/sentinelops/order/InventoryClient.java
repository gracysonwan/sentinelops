package com.sentinelops.order;

import com.sentinelops.order.Dtos.ReserveRequest;
import com.sentinelops.order.Dtos.ReserveResponse;
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.server.ResponseStatusException;

@Component
public class InventoryClient {

    private final RestClient client;

    public InventoryClient(@Value("${sentinel.inventory-url}") String inventoryUrl,
                           @Value("${sentinel.client.read-timeout-ms:3000}") int readTimeoutMs) {
        this.client = HttpClients.create(inventoryUrl, 1000, readTimeoutMs);
    }

    @CircuitBreaker(name = "inventory", fallbackMethod = "reserveFallback")
    public ReserveResponse reserve(String productId, int quantity) {
        return client.post()
                .uri("/inventory/reserve")
                .contentType(MediaType.APPLICATION_JSON)
                .body(new ReserveRequest(productId, quantity))
                .retrieve()
                .body(ReserveResponse.class);
    }

    /** Containment: when inventory is failing (or the breaker is open) answer fast with 503 instead of hanging. */
    public ReserveResponse reserveFallback(String productId, int quantity, Throwable cause) {
        throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,
                "Inventory unavailable (" + cause.getClass().getSimpleName() + ")");
    }
}
