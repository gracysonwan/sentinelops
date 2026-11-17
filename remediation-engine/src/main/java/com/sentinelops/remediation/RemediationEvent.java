package com.sentinelops.remediation;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/** One remediation run: what triggered it, what was done, and how long recovery took. */
public class RemediationEvent {

    public enum Status { IN_PROGRESS, RECOVERED, FAILED }

    private final long id;
    private final String service;
    private final String trigger;
    private final String rootCause;
    private final double anomalyScore;
    private final String reason;
    private final double detectedAt;
    private final double startedAt;
    private volatile double finishedAt;
    private volatile Status status = Status.IN_PROGRESS;
    private volatile String explanation;
    private final List<String> steps = Collections.synchronizedList(new ArrayList<>());

    public RemediationEvent(long id, String service, String trigger, String rootCause, double anomalyScore,
                            String reason, double detectedAt, double startedAt) {
        this.id = id;
        this.service = service;
        this.trigger = trigger;
        this.rootCause = rootCause;
        this.anomalyScore = anomalyScore;
        this.reason = reason;
        this.detectedAt = detectedAt;
        this.startedAt = startedAt;
    }

    public void step(double atEpochSec, String text) {
        steps.add(String.format("+%.1fs %s", atEpochSec - startedAt, text));
    }

    public void finish(Status finalStatus, double atEpochSec) {
        this.status = finalStatus;
        this.finishedAt = atEpochSec;
    }

    public long getId() { return id; }
    public String getService() { return service; }
    public String getTrigger() { return trigger; }
    public String getRootCause() { return rootCause; }
    public double getAnomalyScore() { return anomalyScore; }
    public String getReason() { return reason; }
    public double getDetectedAt() { return detectedAt; }
    public double getStartedAt() { return startedAt; }
    public double getFinishedAt() { return finishedAt; }
    public Status getStatus() { return status; }
    public String getExplanation() { return explanation; }
    public void setExplanation(String explanation) { this.explanation = explanation; }

    public List<String> getSteps() {
        synchronized (steps) {
            return new ArrayList<>(steps);
        }
    }

    /** Time from the AI detection to verified recovery (mean time to recovery for this incident). */
    public Double getRecoverySeconds() {
        if (status != Status.RECOVERED) {
            return null;
        }
        return Math.round((finishedAt - detectedAt) * 10) / 10.0;
    }
}
