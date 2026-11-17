package com.sentinelops.order;

/** Request/response records exchanged with clients and with the other microservices. */
public final class Dtos {

    private Dtos() {
    }

    public record OrderRequest(String productId, int quantity) {
    }

    public record ReserveRequest(String productId, int quantity) {
    }

    public record ReserveResponse(String productId, double unitPrice, int reserved, int remaining) {
    }

    public record PaymentRequest(String orderRef, double amount) {
    }

    public record PaymentResponse(String paymentId, String status, String instance) {
    }

    /** Result of a payment attempt as seen by the order service. */
    public record PaymentOutcome(boolean approved, String paymentId, String route) {
    }
}
