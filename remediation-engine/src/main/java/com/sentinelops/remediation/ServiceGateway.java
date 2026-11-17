package com.sentinelops.remediation;

/** HTTP operations the remediation engine performs on the microservices. */
public interface ServiceGateway {

    /** @return "UP", "DOWN" or "UNREACHABLE" from the service's /actuator/health. */
    String health(String baseUrl);

    /** Switch the order service's payment traffic to "primary" or "standby". */
    void routePayment(String target);

    /** Clears injected faults; used only in dry-run mode when containers cannot be restarted. */
    void resetChaos(String baseUrl);
}
