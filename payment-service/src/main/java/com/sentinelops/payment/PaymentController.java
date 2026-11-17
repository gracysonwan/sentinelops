package com.sentinelops.payment;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;
import java.util.concurrent.ThreadLocalRandom;

@RestController
@RequestMapping("/payments")
public class PaymentController {

    public record PaymentRequest(String orderRef, double amount) {
    }

    public record PaymentResponse(String paymentId, String status, String instance) {
    }

    private final PaymentRepository repository;
    private final String instanceName;

    public PaymentController(PaymentRepository repository,
                             @Value("${sentinel.instance-name:primary}") String instanceName) {
        this.repository = repository;
        this.instanceName = instanceName;
    }

    @PostMapping
    public PaymentResponse pay(@RequestBody PaymentRequest request) {
        if (request.orderRef() == null || request.amount() <= 0) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "orderRef and a positive amount are required");
        }
        simulateGatewayCall();
        Payment saved = repository.save(new Payment(request.orderRef(), request.amount(), "APPROVED", instanceName));
        return new PaymentResponse("PAY-" + saved.getId(), saved.getStatus(), instanceName);
    }

    @GetMapping
    public List<Payment> recent() {
        return repository.findTop20ByOrderByIdDesc();
    }

    /** A real payment gateway round-trip takes a little time; 15-40 ms keeps the baseline realistic. */
    private static void simulateGatewayCall() {
        try {
            Thread.sleep(ThreadLocalRandom.current().nextLong(15, 41));
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }
}
