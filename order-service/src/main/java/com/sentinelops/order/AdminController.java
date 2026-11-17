package com.sentinelops.order;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.util.Map;

/** Traffic-routing switch used by the remediation engine (reroute / failback). */
@RestController
@RequestMapping("/admin/routing")
public class AdminController {

    private final RoutingState routing;

    public AdminController(RoutingState routing) {
        this.routing = routing;
    }

    @GetMapping
    public Map<String, String> current() {
        return Map.of("payment", routing.paymentTarget());
    }

    @PostMapping("/payment")
    public Map<String, String> routePayment(@RequestParam("target") String target) {
        try {
            routing.setPaymentTarget(target);
        } catch (IllegalArgumentException e) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, e.getMessage());
        }
        return Map.of("payment", routing.paymentTarget());
    }
}
