package com.sentinelops.remediation;

import com.sentinelops.remediation.RemediationOrchestrator.SubmitResult;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * POST /api/remediate              - called by the AI layer when an anomaly is confirmed
 * POST /api/remediate/{service}    - manual remediation from the control panel
 * GET  /api/events                 - remediation history (newest first)
 * GET  /api/settings, POST /api/settings?autoRemediation=true|false
 */
@RestController
@RequestMapping("/api")
public class RemediationController {

    private static final Logger log = LoggerFactory.getLogger(RemediationController.class);

    private final RemediationOrchestrator orchestrator;

    public RemediationController(RemediationOrchestrator orchestrator) {
        this.orchestrator = orchestrator;
    }

    @PostMapping("/remediate")
    public ResponseEntity<Map<String, Object>> fromAi(@RequestBody AnomalyAlert alert) {
        log.warn("Anomaly alert received: service={} cause={} score={} reason={}",
                alert.service(), alert.rootCause(), alert.score(), alert.reason());
        return respond(orchestrator.submit(alert, false));
    }

    @PostMapping("/remediate/{service}")
    public ResponseEntity<Map<String, Object>> manual(@PathVariable("service") String service) {
        AnomalyAlert alert = new AnomalyAlert(service, 0.0, "manual", "Manual remediation from control panel",
                null, Map.of(), "MANUAL");
        return respond(orchestrator.submit(alert, true));
    }

    @GetMapping("/events")
    public List<RemediationEvent> events(@RequestParam(name = "limit", defaultValue = "50") int limit) {
        return orchestrator.events(Math.max(1, Math.min(limit, 200)));
    }

    @GetMapping("/settings")
    public Map<String, Object> settings() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("autoRemediation", orchestrator.isAutoRemediation());
        m.put("dryRun", orchestrator.isDryRun());
        m.put("activeRemediations", orchestrator.activeRemediations());
        m.put("services", orchestrator.services());
        return m;
    }

    @PostMapping("/settings")
    public Map<String, Object> updateSettings(@RequestParam("autoRemediation") boolean autoRemediation) {
        orchestrator.setAutoRemediation(autoRemediation);
        log.info("Auto-remediation switched {}", autoRemediation ? "ON" : "OFF");
        return settings();
    }

    private static ResponseEntity<Map<String, Object>> respond(SubmitResult result) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("accepted", result.accepted());
        body.put("message", result.message());
        if (result.event() != null) {
            body.put("eventId", result.event().getId());
        }
        HttpStatus status = result.accepted() ? HttpStatus.ACCEPTED : HttpStatus.CONFLICT;
        return ResponseEntity.status(status).body(body);
    }
}
