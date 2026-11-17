package com.sentinelops.remediation;

import com.sentinelops.remediation.RemediationEvent.Status;
import com.sentinelops.remediation.RemediationPolicy.Action;

import java.io.IOException;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Executor;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.LongSupplier;

/**
 * Layer 5 core: turns an anomaly alert into a sequence of recovery actions and executes them
 * without human involvement. Plain Java (no Spring) so it can be unit-tested with fakes.
 *
 * Flow per alert:  validate -> cooldown check -> plan (policy) -> execute steps asynchronously
 *                  (reroute, restart, verify health, failback) -> record event + metrics.
 */
public class RemediationOrchestrator {

    /** Callback used for metrics (implemented by the Spring layer). */
    public interface Listener {
        void onAction(String service, Action action);

        void onFinished(RemediationEvent event);
    }

    public record SubmitResult(boolean accepted, String message, RemediationEvent event) {
    }

    private static final int MAX_EVENTS = 200;

    private final Map<String, ManagedService> services;
    private final ServiceGateway gateway;
    private final DockerClient docker;
    private final RemediationPolicy policy = new RemediationPolicy();
    private final CooldownTracker cooldown;
    private final Executor executor;
    private final LongSupplier clockMs;
    private final Listener listener;
    private final boolean dryRun;
    private final long recoveryTimeoutMs;
    private final long healthPollMs;
    private final AtomicBoolean autoRemediation;
    private final AtomicLong ids = new AtomicLong();
    private final Deque<RemediationEvent> events = new ArrayDeque<>();

    public RemediationOrchestrator(Map<String, ManagedService> services, ServiceGateway gateway, DockerClient docker,
                                   Executor executor, LongSupplier clockMs, Listener listener,
                                   boolean dryRun, boolean autoRemediation, long cooldownMs,
                                   long recoveryTimeoutMs, long healthPollMs) {
        this.services = Map.copyOf(services);
        this.gateway = gateway;
        this.docker = docker;
        this.executor = executor;
        this.clockMs = clockMs;
        this.listener = listener;
        this.dryRun = dryRun;
        this.autoRemediation = new AtomicBoolean(autoRemediation);
        this.cooldown = new CooldownTracker(cooldownMs);
        this.recoveryTimeoutMs = recoveryTimeoutMs;
        this.healthPollMs = healthPollMs;
    }

    public SubmitResult submit(AnomalyAlert alert, boolean manual) {
        if (alert == null || alert.service() == null) {
            return new SubmitResult(false, "service is required", null);
        }
        ManagedService target = services.get(alert.service());
        if (target == null) {
            return new SubmitResult(false, "unknown service " + alert.service(), null);
        }
        if (!manual && !autoRemediation.get()) {
            return new SubmitResult(false, "auto-remediation is switched off (detection only)", null);
        }
        long nowMs = clockMs.getAsLong();
        String blocked = cooldown.tryAcquire(alert.service(), nowMs);
        if (blocked != null) {
            return new SubmitResult(false, blocked, null);
        }
        double now = nowMs / 1000.0;
        double detectedAt = alert.detectedAt() != null ? alert.detectedAt() : now;
        String trigger = manual ? "MANUAL" : (alert.trigger() != null ? alert.trigger() : "AI_PREDICTION");
        RemediationEvent event = new RemediationEvent(ids.incrementAndGet(), alert.service(), trigger,
                alert.rootCause(), alert.score(), alert.reason(), detectedAt, now);
        event.setExplanation(policy.explain(alert.rootCause(), target.hasStandby()));
        synchronized (events) {
            events.addFirst(event);
            while (events.size() > MAX_EVENTS) {
                events.removeLast();
            }
        }
        executor.execute(() -> execute(event, target));
        return new SubmitResult(true, "remediation started", event);
    }

    void execute(RemediationEvent event, ManagedService target) {
        String service = event.getService();
        try {
            for (Action action : policy.plan(target.hasStandby())) {
                switch (action) {
                    case REROUTE_TO_STANDBY -> {
                        gateway.routePayment("standby");
                        event.step(nowSec(), "Rerouted live traffic to the standby instance");
                    }
                    case RESTART_CONTAINER -> restart(event, target);
                    case VERIFY_HEALTH -> {
                        if (!waitUntilHealthy(target)) {
                            event.step(nowSec(), "Service did not report UP within "
                                    + (recoveryTimeoutMs / 1000) + "s - escalate to on-call");
                            event.finish(Status.FAILED, nowSec());
                            return;
                        }
                        event.step(nowSec(), "Health check passed (status UP)");
                    }
                    case FAILBACK_TO_PRIMARY -> {
                        gateway.routePayment("primary");
                        event.step(nowSec(), "Failed traffic back to the healed primary");
                    }
                }
                listener.onAction(service, action);
            }
            event.finish(Status.RECOVERED, nowSec());
        } catch (Exception e) {
            event.step(nowSec(), "Remediation error: " + e.getMessage());
            event.finish(Status.FAILED, nowSec());
        } finally {
            cooldown.release(service, clockMs.getAsLong());
            listener.onFinished(event);
        }
    }

    private void restart(RemediationEvent event, ManagedService target) throws IOException {
        if (dryRun || !docker.isAvailable()) {
            gateway.resetChaos(target.baseUrl());
            event.step(nowSec(), "DRY-RUN: Docker socket not available - simulated restart of "
                    + target.container() + " by clearing its fault state");
            return;
        }
        int status = docker.restart(target.container(), 5);
        if (status != 204) {
            throw new IOException("Docker API returned HTTP " + status + " for restart of " + target.container());
        }
        event.step(nowSec(), "Restarted container " + target.container() + " via Docker Engine API");
    }

    private boolean waitUntilHealthy(ManagedService target) throws InterruptedException {
        long deadline = clockMs.getAsLong() + recoveryTimeoutMs;
        do {
            if ("UP".equals(gateway.health(target.baseUrl()))) {
                return true;
            }
            if (healthPollMs > 0) {
                Thread.sleep(healthPollMs);
            }
        } while (clockMs.getAsLong() < deadline);
        return false;
    }

    private double nowSec() {
        return clockMs.getAsLong() / 1000.0;
    }

    public List<RemediationEvent> events(int limit) {
        synchronized (events) {
            List<RemediationEvent> copy = new ArrayList<>(events);
            return copy.subList(0, Math.min(limit, copy.size()));
        }
    }

    public boolean isAutoRemediation() {
        return autoRemediation.get();
    }

    public void setAutoRemediation(boolean enabled) {
        autoRemediation.set(enabled);
    }

    public boolean isDryRun() {
        return dryRun || !docker.isAvailable();
    }

    public int activeRemediations() {
        return cooldown.activeCount();
    }

    public Map<String, ManagedService> services() {
        return services;
    }
}
