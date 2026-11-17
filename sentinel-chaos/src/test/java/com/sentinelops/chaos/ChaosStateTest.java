package com.sentinelops.chaos;

import org.junit.jupiter.api.Test;

import java.util.concurrent.atomic.AtomicLong;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ChaosStateTest {

    @Test
    void latencyRampsUpOverTimeAndIsCapped() {
        AtomicLong now = new AtomicLong(0);
        ChaosState state = new ChaosState(now::get);
        state.startLatency(100, 50);
        assertEquals(100, state.currentLatencyMs());
        now.set(10_000); // 10 s later
        assertEquals(600, state.currentLatencyMs());
        now.set(1_000_000);
        assertEquals(ChaosState.MAX_LATENCY_MS, state.currentLatencyMs());
        state.shutdown();
    }

    @Test
    void errorRateRampsAndIsClampedToOne() {
        AtomicLong now = new AtomicLong(0);
        ChaosState state = new ChaosState(now::get);
        state.startErrors(0.05, 0.01);
        assertEquals(0.05, state.currentErrorRate(), 1e-9);
        now.set(20_000);
        assertEquals(0.25, state.currentErrorRate(), 1e-9);
        now.set(500_000);
        assertEquals(1.0, state.currentErrorRate(), 1e-9);
        state.shutdown();
    }

    @Test
    void memoryLeakRetainsHeapUntilMaxAndResetFreesIt() {
        ChaosState state = new ChaosState(() -> 0L);
        state.startMemoryLeak(3, 5);
        state.leakTick();
        state.leakTick();
        state.leakTick();
        assertEquals(5, state.leakedMb());
        assertTrue(state.isActive());
        state.reset();
        assertEquals(0, state.leakedMb());
        assertFalse(state.isActive());
        state.shutdown();
    }

    @Test
    void inactiveByDefault() {
        ChaosState state = new ChaosState(() -> 0L);
        assertEquals(0, state.currentLatencyMs());
        assertEquals(0.0, state.currentErrorRate(), 0.0);
        assertFalse(state.isActive());
        state.shutdown();
    }
}
