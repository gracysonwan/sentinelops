package com.sentinelops.remediation;

import java.util.Map;

/**
 * Alert sent by the AI intelligence layer (or by a person from the control panel).
 *
 * @param service    affected microservice, e.g. "payment-service"
 * @param score      Isolation Forest anomaly score (0..1, higher = more anomalous)
 * @param rootCause  latency | errors | memory | cpu | unavailable
 * @param reason     short human-readable explanation from the AI layer
 * @param detectedAt epoch seconds when the anomaly was confirmed
 * @param features   metric values that led to the decision
 * @param trigger    AI_PREDICTION, SERVICE_DOWN or MANUAL
 */
public record AnomalyAlert(String service, double score, String rootCause, String reason,
                           Double detectedAt, Map<String, Double> features, String trigger) {
}
