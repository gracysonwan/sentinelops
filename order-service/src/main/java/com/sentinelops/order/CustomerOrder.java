package com.sentinelops.order;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.time.Instant;

@Entity
@Table(name = "orders")
public class CustomerOrder {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    private String productId;
    private int quantity;
    private double amount;
    /** CREATED, PAID or PAYMENT_PENDING (payment could not be completed - order kept for retry). */
    private String status;
    /** Which payment instance handled the order: primary, standby, or *-fallback via the circuit breaker. */
    private String paymentRoute;
    private String paymentId;
    private Instant createdAt;

    protected CustomerOrder() {
    }

    public CustomerOrder(String productId, int quantity, double amount) {
        this.productId = productId;
        this.quantity = quantity;
        this.amount = amount;
        this.status = "CREATED";
        this.createdAt = Instant.now();
    }

    public Long getId() { return id; }
    public String getProductId() { return productId; }
    public int getQuantity() { return quantity; }
    public double getAmount() { return amount; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public String getPaymentRoute() { return paymentRoute; }
    public void setPaymentRoute(String paymentRoute) { this.paymentRoute = paymentRoute; }
    public String getPaymentId() { return paymentId; }
    public void setPaymentId(String paymentId) { this.paymentId = paymentId; }
    public Instant getCreatedAt() { return createdAt; }
}
