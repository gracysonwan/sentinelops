package com.sentinelops.remediation;

import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

/**
 * Prevents remediation storms: at most one remediation per service at a time, and no new one
 * for {@code cooldownMs} after the previous one finished (a freshly restarted JVM looks
 * "anomalous" while it warms up, and must not be restarted again because of that).
 */
public class CooldownTracker {

    private final long cooldownMs;
    private final Set<String> inProgress = new HashSet<>();
    private final Map<String, Long> finishedAt = new HashMap<>();

    public CooldownTracker(long cooldownMs) {
        this.cooldownMs = cooldownMs;
    }

    /** @return null if the service may be remediated now (and marks it in progress), otherwise the reason it may not. */
    public synchronized String tryAcquire(String service, long nowMs) {
        if (inProgress.contains(service)) {
            return "remediation already in progress";
        }
        Long last = finishedAt.get(service);
        if (last != null && nowMs - last < cooldownMs) {
            long remaining = (cooldownMs - (nowMs - last) + 999) / 1000;
            return "cooldown active (" + remaining + "s left)";
        }
        inProgress.add(service);
        return null;
    }

    public synchronized void release(String service, long nowMs) {
        inProgress.remove(service);
        finishedAt.put(service, nowMs);
    }

    public synchronized boolean isBusy(String service) {
        return inProgress.contains(service);
    }

    public synchronized int activeCount() {
        return inProgress.size();
    }
}
