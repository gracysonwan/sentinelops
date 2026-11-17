package com.sentinelops.order;

import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class RoutingStateTest {

    @Test
    void defaultsToPrimaryAndSwitchesToStandby() {
        SimpleMeterRegistry registry = new SimpleMeterRegistry();
        RoutingState routing = new RoutingState(registry);
        assertEquals(RoutingState.PRIMARY, routing.paymentTarget());
        routing.setPaymentTarget(RoutingState.STANDBY);
        assertEquals(RoutingState.STANDBY, routing.paymentTarget());
        assertEquals(1.0, registry.get("sentinel.payment.route.standby").gauge().value(), 0.0);
    }

    @Test
    void rejectsUnknownTargets() {
        RoutingState routing = new RoutingState(new SimpleMeterRegistry());
        assertThrows(IllegalArgumentException.class, () -> routing.setPaymentTarget("somewhere-else"));
    }
}
