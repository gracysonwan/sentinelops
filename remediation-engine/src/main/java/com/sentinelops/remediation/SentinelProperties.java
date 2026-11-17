package com.sentinelops.remediation;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.Map;

/** Settings under the "sentinel" prefix in application.yml. */
@ConfigurationProperties(prefix = "sentinel")
public record SentinelProperties(
        boolean autoRemediation,
        boolean dryRun,
        String dockerSocket,
        int cooldownSeconds,
        int recoveryTimeoutSeconds,
        String intelligenceUrl,
        String orderServiceUrl,
        String paymentStandbyUrl,
        String grafanaUrl,
        String prometheusUrl,
        Map<String, ManagedService> services) {
}
