package com.sentinelops.chaos;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.web.servlet.HandlerInterceptor;

import java.util.concurrent.ThreadLocalRandom;

/**
 * Applies the active faults to every business request before it reaches the controller.
 * Actuator, chaos and admin endpoints are excluded (see {@link ChaosWebConfig}) so that
 * monitoring and remediation keep working while a fault is active.
 */
public class ChaosInterceptor implements HandlerInterceptor {

    private final ChaosState state;

    public ChaosInterceptor(ChaosState state) {
        this.state = state;
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) throws Exception {
        long delay = state.currentLatencyMs();
        if (delay > 0) {
            // +/-15% jitter so the injected latency looks like real network/database slowness
            double jitter = 0.85 + ThreadLocalRandom.current().nextDouble() * 0.30;
            try {
                Thread.sleep(Math.round(delay * jitter));
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }
        double errorRate = state.currentErrorRate();
        if (errorRate > 0 && ThreadLocalRandom.current().nextDouble() < errorRate) {
            response.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
            response.setContentType("application/json");
            response.getWriter().write("{\"error\":\"chaos-injected failure\"}");
            return false;
        }
        return true;
    }
}
