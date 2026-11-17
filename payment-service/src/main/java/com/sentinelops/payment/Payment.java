package com.sentinelops.payment;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.time.Instant;

@Entity
@Table(name = "payments")
public class Payment {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    private String orderRef;
    private double amount;
    private String status;
    /** primary or standby - shows which instance processed the payment. */
    private String processedBy;
    private Instant createdAt;

    protected Payment() {
    }

    public Payment(String orderRef, double amount, String status, String processedBy) {
        this.orderRef = orderRef;
        this.amount = amount;
        this.status = status;
        this.processedBy = processedBy;
        this.createdAt = Instant.now();
    }

    public Long getId() { return id; }
    public String getOrderRef() { return orderRef; }
    public double getAmount() { return amount; }
    public String getStatus() { return status; }
    public String getProcessedBy() { return processedBy; }
    public Instant getCreatedAt() { return createdAt; }
}
