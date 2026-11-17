package com.sentinelops.chaos;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * Layer 2 - Chaos API. Every microservice that includes this library exposes:
 *
 *   POST /chaos/latency?baseMs=0&rampMsPerSec=20      gradual latency creep
 *   POST /chaos/errors?rate=0.05&rampPerSec=0.01      growing error burst
 *   POST /chaos/memory-leak?mbPerSec=1&maxMb=200      heap leak toward OutOfMemory
 *   POST /chaos/reset                                 clear all faults
 *   GET  /chaos/status                                current fault values
 */
@RestController
@RequestMapping("/chaos")
public class ChaosController {

    private static final Logger log = LoggerFactory.getLogger(ChaosController.class);

    private final ChaosState state;

    public ChaosController(ChaosState state) {
        this.state = state;
    }

    @PostMapping("/latency")
    public Map<String, Object> latency(@RequestParam(name = "baseMs", defaultValue = "0") long baseMs,
                                       @RequestParam(name = "rampMsPerSec", defaultValue = "20") double rampMsPerSec) {
        state.startLatency(baseMs, rampMsPerSec);
        log.warn("CHAOS latency injected: base={}ms ramp={}ms/s", baseMs, rampMsPerSec);
        return state.snapshot();
    }

    @PostMapping("/errors")
    public Map<String, Object> errors(@RequestParam(name = "rate", defaultValue = "0.05") double rate,
                                      @RequestParam(name = "rampPerSec", defaultValue = "0.01") double rampPerSec) {
        state.startErrors(rate, rampPerSec);
        log.warn("CHAOS errors injected: rate={} ramp={}/s", rate, rampPerSec);
        return state.snapshot();
    }

    @PostMapping("/memory-leak")
    public Map<String, Object> memoryLeak(@RequestParam(name = "mbPerSec", defaultValue = "1") int mbPerSec,
                                          @RequestParam(name = "maxMb", defaultValue = "200") int maxMb) {
        state.startMemoryLeak(mbPerSec, maxMb);
        log.warn("CHAOS memory leak injected: {}MB/s up to {}MB", mbPerSec, maxMb);
        return state.snapshot();
    }

    @PostMapping("/reset")
    public Map<String, Object> reset() {
        state.reset();
        log.info("CHAOS reset - all faults cleared");
        return state.snapshot();
    }

    @GetMapping("/status")
    public Map<String, Object> status() {
        return state.snapshot();
    }
}
