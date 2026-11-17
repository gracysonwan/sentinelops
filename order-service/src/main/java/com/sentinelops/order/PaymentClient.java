package com.sentinelops.order;

import com.sentinelops.order.Dtos.PaymentOutcome;
import com.sentinelops.order.Dtos.PaymentRequest;
import com.sentinelops.order.Dtos.PaymentResponse;
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

/**
 * Calls the payment service. Traffic goes to the instance chosen by {@link RoutingState}
 * (primary by default). The Resilience4j circuit breaker contains failures: when the chosen
 * instance fails or the breaker is open, the fallback retries once on the other instance, and if
 * that fails too the order is kept as PAYMENT_PENDING instead of returning an error.
 */
@Component
public class PaymentClient {

    private static final Logger log = LoggerFactory.getLogger(PaymentClient.class);

    private final RestClient primary;
    private final RestClient standby;
    private final RoutingState routing;

    public PaymentClient(@Value("${sentinel.payment-primary-url}") String primaryUrl,
                         @Value("${sentinel.payment-standby-url}") String standbyUrl,
                         @Value("${sentinel.client.read-timeout-ms:3000}") int readTimeoutMs,
                         RoutingState routing) {
        this.primary = HttpClients.create(primaryUrl, 1000, readTimeoutMs);
        this.standby = HttpClients.create(standbyUrl, 1000, readTimeoutMs);
        this.routing = routing;
    }

    @CircuitBreaker(name = "payment", fallbackMethod = "chargeFallback")
    public PaymentOutcome charge(String orderRef, double amount) {
        String route = routing.paymentTarget();
        PaymentResponse response = call(route, orderRef, amount);
        return new PaymentOutcome(true, response.paymentId(), route);
    }

    public PaymentOutcome chargeFallback(String orderRef, double amount, Throwable cause) {
        String alternate = RoutingState.STANDBY.equals(routing.paymentTarget())
                ? RoutingState.PRIMARY : RoutingState.STANDBY;
        try {
            PaymentResponse response = call(alternate, orderRef, amount);
            return new PaymentOutcome(true, response.paymentId(), alternate + "-fallback");
        } catch (Exception e) {
            log.warn("Payment failed on both instances for {}: {}", orderRef, e.getMessage());
            return new PaymentOutcome(false, null, "none");
        }
    }

    private PaymentResponse call(String route, String orderRef, double amount) {
        RestClient client = RoutingState.STANDBY.equals(route) ? standby : primary;
        return client.post()
                .uri("/payments")
                .contentType(MediaType.APPLICATION_JSON)
                .body(new PaymentRequest(orderRef, amount))
                .retrieve()
                .body(PaymentResponse.class);
    }
}
