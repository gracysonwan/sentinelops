package com.sentinelops.remediation;

import com.sentinelops.remediation.RemediationEvent.Status;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class RemediationOrchestratorTest {

    /** Records every call; health becomes UP after a configurable number of polls. */
    static class FakeGateway implements ServiceGateway {
        final List<String> calls = new ArrayList<>();
        int pollsUntilUp;

        FakeGateway(int pollsUntilUp) {
            this.pollsUntilUp = pollsUntilUp;
        }

        @Override
        public String health(String baseUrl) {
            calls.add("health " + baseUrl);
            return pollsUntilUp-- <= 0 ? "UP" : "UNREACHABLE";
        }

        @Override
        public void routePayment(String target) {
            calls.add("route " + target);
        }

        @Override
        public void resetChaos(String baseUrl) {
            calls.add("reset " + baseUrl);
        }
    }

    static class FakeDocker extends DockerClient {
        final List<String> restarted = new ArrayList<>();
        int status = 204;

        FakeDocker() {
            super("/nonexistent.sock");
        }

        @Override
        public boolean isAvailable() {
            return true;
        }

        @Override
        public int restart(String containerName, int stopTimeoutSeconds) throws IOException {
            restarted.add(containerName);
            return status;
        }
    }

    static class CountingListener implements RemediationOrchestrator.Listener {
        int actions;
        int finished;

        @Override
        public void onAction(String service, RemediationPolicy.Action action) {
            actions++;
        }

        @Override
        public void onFinished(RemediationEvent event) {
            finished++;
        }
    }

    private static final Map<String, ManagedService> SERVICES = Map.of(
            "payment-service", new ManagedService("sentinel-payment", "http://payment:8082", true),
            "inventory-service", new ManagedService("sentinel-inventory", "http://inventory:8083", false));

    private final AtomicLong clock = new AtomicLong(1_000_000L);

    private RemediationOrchestrator orchestrator(FakeGateway gw, DockerClient docker, CountingListener l,
                                                 boolean dryRun, boolean auto) {
        // Executor runs inline so the test is deterministic; each clock read advances time by 1 s.
        return new RemediationOrchestrator(SERVICES, gw, docker, Runnable::run,
                () -> clock.addAndGet(1000), l, dryRun, auto, 60_000, 30_000, 0);
    }

    private static AnomalyAlert alert(String service, String cause) {
        return new AnomalyAlert(service, 0.81, cause, "test", null, Map.of(), "AI_PREDICTION");
    }

    @Test
    void paymentAnomalyIsReroutedRestartedVerifiedAndFailedBack() {
        FakeGateway gw = new FakeGateway(2);
        FakeDocker docker = new FakeDocker();
        CountingListener listener = new CountingListener();
        RemediationOrchestrator o = orchestrator(gw, docker, listener, false, true);

        var result = o.submit(alert("payment-service", "latency"), false);

        assertTrue(result.accepted());
        RemediationEvent e = o.events(10).get(0);
        assertEquals(Status.RECOVERED, e.getStatus());
        assertEquals(List.of("sentinel-payment"), docker.restarted);
        assertEquals("route standby", gw.calls.get(0));
        assertEquals("route primary", gw.calls.get(gw.calls.size() - 1));
        assertEquals(4, listener.actions);
        assertEquals(1, listener.finished);
        assertTrue(e.getRecoverySeconds() > 0);
    }

    @Test
    void serviceWithoutStandbyIsOnlyRestarted() {
        FakeGateway gw = new FakeGateway(0);
        FakeDocker docker = new FakeDocker();
        RemediationOrchestrator o = orchestrator(gw, docker, new CountingListener(), false, true);

        o.submit(alert("inventory-service", "errors"), false);

        assertEquals(List.of("sentinel-inventory"), docker.restarted);
        assertFalse(gw.calls.stream().anyMatch(c -> c.startsWith("route")));
        assertEquals(Status.RECOVERED, o.events(1).get(0).getStatus());
    }

    @Test
    void cooldownBlocksRepeatedRemediation() {
        RemediationOrchestrator o = orchestrator(new FakeGateway(0), new FakeDocker(), new CountingListener(), false, true);
        assertTrue(o.submit(alert("inventory-service", "errors"), false).accepted());
        var second = o.submit(alert("inventory-service", "errors"), false);
        assertFalse(second.accepted());
        assertTrue(second.message().startsWith("cooldown"));
    }

    @Test
    void autoRemediationOffMeansDetectionOnlyButManualStillWorks() {
        RemediationOrchestrator o = orchestrator(new FakeGateway(0), new FakeDocker(), new CountingListener(), false, false);
        assertFalse(o.submit(alert("inventory-service", "memory"), false).accepted());
        assertTrue(o.submit(alert("inventory-service", "memory"), true).accepted());
        assertEquals("MANUAL", o.events(1).get(0).getTrigger());
    }

    @Test
    void dryRunClearsFaultsInsteadOfRestarting() {
        FakeGateway gw = new FakeGateway(0);
        FakeDocker docker = new FakeDocker();
        RemediationOrchestrator o = orchestrator(gw, docker, new CountingListener(), true, true);

        o.submit(alert("inventory-service", "latency"), false);

        assertTrue(docker.restarted.isEmpty());
        assertTrue(gw.calls.contains("reset http://inventory:8083"));
        assertTrue(o.isDryRun());
    }

    @Test
    void failedRestartIsReportedAndTrafficStaysOnStandby() {
        FakeGateway gw = new FakeGateway(0);
        FakeDocker docker = new FakeDocker();
        docker.status = 404;
        RemediationOrchestrator o = orchestrator(gw, docker, new CountingListener(), false, true);

        o.submit(alert("payment-service", "memory"), false);

        RemediationEvent e = o.events(1).get(0);
        assertEquals(Status.FAILED, e.getStatus());
        assertFalse(gw.calls.contains("route primary"));
    }

    @Test
    void unhealthyAfterTimeoutIsMarkedFailed() {
        FakeGateway gw = new FakeGateway(1_000);
        RemediationOrchestrator o = orchestrator(gw, new FakeDocker(), new CountingListener(), false, true);
        o.submit(alert("inventory-service", "errors"), false);
        assertEquals(Status.FAILED, o.events(1).get(0).getStatus());
    }

    @Test
    void unknownServiceIsRejected() {
        RemediationOrchestrator o = orchestrator(new FakeGateway(0), new FakeDocker(), new CountingListener(), false, true);
        assertFalse(o.submit(alert("billing-service", "errors"), false).accepted());
    }

    @Test
    void dockerStatusLineIsParsed() throws IOException {
        assertEquals(204, DockerClient.parseStatus("HTTP/1.1 204 No Content\r\nApi-Version: 1.45\r\n\r\n"));
        assertEquals(404, DockerClient.parseStatus("HTTP/1.1 404 Not Found\r\n\r\n{\"message\":\"No such container\"}"));
    }
}
