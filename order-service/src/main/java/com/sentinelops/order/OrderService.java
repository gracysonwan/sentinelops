package com.sentinelops.order;

import com.sentinelops.order.Dtos.OrderRequest;
import com.sentinelops.order.Dtos.PaymentOutcome;
import com.sentinelops.order.Dtos.ReserveResponse;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;

@Service
public class OrderService {

    private final OrderRepository repository;
    private final InventoryClient inventory;
    private final PaymentClient payments;

    public OrderService(OrderRepository repository, InventoryClient inventory, PaymentClient payments) {
        this.repository = repository;
        this.inventory = inventory;
        this.payments = payments;
    }

    /** Reserve stock -> save order -> charge payment -> update status. */
    public CustomerOrder placeOrder(OrderRequest request) {
        if (request.productId() == null || request.quantity() <= 0) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "productId and a positive quantity are required");
        }
        ReserveResponse reservation = inventory.reserve(request.productId(), request.quantity());
        double amount = Math.round(reservation.unitPrice() * request.quantity() * 100) / 100.0;

        CustomerOrder order = repository.save(new CustomerOrder(request.productId(), request.quantity(), amount));

        PaymentOutcome payment = payments.charge("ORD-" + order.getId(), amount);
        order.setStatus(payment.approved() ? "PAID" : "PAYMENT_PENDING");
        order.setPaymentRoute(payment.route());
        order.setPaymentId(payment.paymentId());
        return repository.save(order);
    }

    public List<CustomerOrder> recent() {
        return repository.findTop20ByOrderByIdDesc();
    }

    public CustomerOrder byId(long id) {
        return repository.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "order not found"));
    }
}
