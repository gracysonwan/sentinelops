package com.sentinelops.order;

import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.stereotype.Component;

import java.util.concurrent.atomic.AtomicReference;

/**
 * Which payment instance new orders are sent to. The remediation engine switches this to
 * "standby" while it heals the primary instance, then switches it back (failback).
 */
@Component
public class RoutingState {

    public static final String PRIMARY = "primary";
    public static final String STANDBY = "standby";

    private final AtomicReference<String> paymentTarget = new AtomicReference<>(PRIMARY);

    public RoutingState(MeterRegistry registry) {
        Gauge.builder("sentinel.payment.route.standby", this, r -> STANDBY.equals(r.paymentTarget()) ? 1 : 0)
                .description("1 when order traffic is routed to the standby payment instance")
                .register(registry);
    }

    public String paymentTarget() {
        return paymentTarget.get();
    }

    public void setPaymentTarget(String target) {
        if (!PRIMARY.equals(target) && !STANDBY.equals(target)) {
            throw new IllegalArgumentException("target must be 'primary' or 'standby'");
        }
        paymentTarget.set(target);
    }
}
