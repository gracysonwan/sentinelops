package com.sentinelops.remediation;

/**
 * A microservice the remediation engine is allowed to act on.
 *
 * @param container  Docker container name (used for restarts)
 * @param baseUrl    HTTP base URL (used for health checks)
 * @param hasStandby true if a standby instance exists that traffic can be rerouted to
 */
public record ManagedService(String container, String baseUrl, boolean hasStandby) {
}
