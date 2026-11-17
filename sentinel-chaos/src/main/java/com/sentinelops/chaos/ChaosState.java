package com.sentinelops.chaos;

import jakarta.annotation.PreDestroy;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.function.LongSupplier;

/**
 * Holds the currently active fault-injection settings for one microservice.
 *
 * Faults can be static (a fixed extra latency or error rate) or ramped, so that a
 * service degrades gradually the way real services usually do before they fail.
 * Gradual degradation is what gives the AI layer a chance to predict the failure.
 *
 * Supported faults:
 *   latency     - extra delay per request = baseMs + rampMsPerSec * secondsSinceStart
 *   errors      - probability of an HTTP 500 = rate + rampPerSec * secondsSinceStart
 *   memory leak - retains mbPerSec MB of heap every second until maxMb is held
 */
@Component
public class ChaosState {

    public static final long MAX_LATENCY_MS = 8_000;
    private static final int ONE_MB = 1024 * 1024;

    private final LongSupplier clock;
    private final ScheduledExecutorService leakExecutor;

    private volatile long latencyBaseMs;
    private volatile double latencyRampMsPerSec;
    private volatile long latencyStartedAt;

    private volatile double errorBaseRate;
    private volatile double errorRampPerSec;
    private volatile long errorStartedAt;

    private volatile int leakMbPerSec;
    private volatile int leakMaxMb;
    private final List<byte[]> leakedBlocks = new ArrayList<>();
    private ScheduledFuture<?> leakTask;

    public ChaosState() {
        this(System::currentTimeMillis);
    }

    ChaosState(LongSupplier clock) {
        this.clock = clock;
        this.leakExecutor = Executors.newSingleThreadScheduledExecutor(r -> {
            Thread t = new Thread(r, "chaos-memory-leak");
            t.setDaemon(true);
            return t;
        });
    }

    // ------------------------------------------------------------------ latency

    public synchronized void startLatency(long baseMs, double rampMsPerSec) {
        this.latencyBaseMs = Math.max(0, baseMs);
        this.latencyRampMsPerSec = Math.max(0, rampMsPerSec);
        this.latencyStartedAt = clock.getAsLong();
    }

    public long currentLatencyMs() {
        if (latencyBaseMs == 0 && latencyRampMsPerSec == 0) {
            return 0;
        }
        double elapsedSec = (clock.getAsLong() - latencyStartedAt) / 1000.0;
        long value = Math.round(latencyBaseMs + latencyRampMsPerSec * elapsedSec);
        return Math.min(value, MAX_LATENCY_MS);
    }

    // ------------------------------------------------------------------ errors

    public synchronized void startErrors(double rate, double rampPerSec) {
        this.errorBaseRate = clamp01(rate);
        this.errorRampPerSec = Math.max(0, rampPerSec);
        this.errorStartedAt = clock.getAsLong();
    }

    public double currentErrorRate() {
        if (errorBaseRate == 0 && errorRampPerSec == 0) {
            return 0;
        }
        double elapsedSec = (clock.getAsLong() - errorStartedAt) / 1000.0;
        return clamp01(errorBaseRate + errorRampPerSec * elapsedSec);
    }

    // ------------------------------------------------------------------ memory leak

    public synchronized void startMemoryLeak(int mbPerSec, int maxMb) {
        stopLeakTask();
        this.leakMbPerSec = Math.max(1, mbPerSec);
        this.leakMaxMb = Math.max(1, maxMb);
        this.leakTask = leakExecutor.scheduleAtFixedRate(this::leakTick, 0, 1, TimeUnit.SECONDS);
    }

    /** One step of the leak: retain more heap until the configured maximum is reached. */
    void leakTick() {
        synchronized (leakedBlocks) {
            try {
                for (int i = 0; i < leakMbPerSec && leakedBlocks.size() < leakMaxMb; i++) {
                    byte[] block = new byte[ONE_MB];
                    block[0] = 1; // touch the block so it is clearly in use
                    leakedBlocks.add(block);
                }
            } catch (OutOfMemoryError oom) {
                // The JVM is out of heap; stop growing but keep what is held (the service is now failing).
                leakMaxMb = leakedBlocks.size();
            }
        }
    }

    public int leakedMb() {
        synchronized (leakedBlocks) {
            return leakedBlocks.size();
        }
    }

    // ------------------------------------------------------------------ reset / status

    public synchronized void reset() {
        latencyBaseMs = 0;
        latencyRampMsPerSec = 0;
        errorBaseRate = 0;
        errorRampPerSec = 0;
        stopLeakTask();
        leakMbPerSec = 0;
        leakMaxMb = 0;
        synchronized (leakedBlocks) {
            leakedBlocks.clear();
        }
    }

    public boolean isActive() {
        return currentLatencyMs() > 0 || currentErrorRate() > 0 || leakedMb() > 0 || leakTask != null;
    }

    public Map<String, Object> snapshot() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("active", isActive());
        m.put("latencyMs", currentLatencyMs());
        m.put("latencyRampMsPerSec", latencyRampMsPerSec);
        m.put("errorRate", Math.round(currentErrorRate() * 1000) / 1000.0);
        m.put("errorRampPerSec", errorRampPerSec);
        m.put("leakedMb", leakedMb());
        m.put("leakMaxMb", leakMaxMb);
        return m;
    }

    private void stopLeakTask() {
        if (leakTask != null) {
            leakTask.cancel(false);
            leakTask = null;
        }
    }

    @PreDestroy
    public void shutdown() {
        leakExecutor.shutdownNow();
    }

    private static double clamp01(double v) {
        return Math.max(0.0, Math.min(1.0, v));
    }
}
