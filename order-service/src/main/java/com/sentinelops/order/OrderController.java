package com.sentinelops.order;

import com.sentinelops.order.Dtos.OrderRequest;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/orders")
public class OrderController {

    private final OrderService orders;

    public OrderController(OrderService orders) {
        this.orders = orders;
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public CustomerOrder place(@RequestBody OrderRequest request) {
        return orders.placeOrder(request);
    }

    @GetMapping
    public List<CustomerOrder> recent() {
        return orders.recent();
    }

    @GetMapping("/{id}")
    public CustomerOrder byId(@PathVariable("id") long id) {
        return orders.byId(id);
    }
}
