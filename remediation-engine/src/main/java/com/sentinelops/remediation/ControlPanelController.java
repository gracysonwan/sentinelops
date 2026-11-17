package com.sentinelops.remediation;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;

/**
 * Backend for the control panel (src/main/resources/static/index.html). It aggregates the state of
 * every layer in one call and forwards chaos commands, so the browser only talks to this service.
 */
@RestController
@RequestMapping("/api")
public class ControlPanelController {

    private static final Set<String> CHAOS_TYPES = Set.of("latency", "errors", "memory-leak", "reset");

    private final SentinelProperties props;
    private final HttpServiceGateway gateway;
    private final RemediationOrchestrator orchestrator;

    public ControlPanelController(SentinelProperties props, HttpServiceGateway gateway,
                                  RemediationOrchestrator orchestrator) {
        this.props = props;
        this.gateway = gateway;
        this.orchestrator = orchestrator;
    }

    @GetMapping("/overview")
    public Map<String, Object> overview() {
        Map<String, Object> intelligence = safeGet(props.intelligenceUrl() + "/status");
        Object aiServices = intelligence.get("services");

        Map<String, Object> services = new LinkedHashMap<>();
        for (Map.Entry<String, ManagedService> entry : props.services().entrySet()) {
            String name = entry.getKey();
            ManagedService svc = entry.getValue();
            Map<String, Object> s = new LinkedHashMap<>();
            s.put("health", gateway.health(svc.baseUrl()));
            s.put("chaos", safeGet(svc.baseUrl() + "/chaos/status"));
            s.put("hasStandby", svc.hasStandby());
            if (aiServices instanceof Map<?, ?> ai && ai.get(name) != null) {
                s.put("ai", ai.get(name));
            }
            services.put(name, s);
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("services", services);
        result.put("standby", Map.of("health", gateway.health(props.paymentStandbyUrl())));
        result.put("routing", safeGet(props.orderServiceUrl() + "/admin/routing"));
        result.put("intelligence", Map.of(
                "reachable", !intelligence.isEmpty(),
                "alertsSent", intelligence.getOrDefault("alerts_sent", 0)));
        result.put("autoRemediation", orchestrator.isAutoRemediation());
        result.put("dryRun", orchestrator.isDryRun());
        result.put("links", Map.of("grafana", props.grafanaUrl(), "prometheus", props.prometheusUrl()));
        result.put("events", orchestrator.events(15));
        return result;
    }

    /** POST /api/chaos/{service}/{type}?... forwards to the service's /chaos/{type} endpoint. */
    @PostMapping("/chaos/{service}/{type}")
    public Map<String, Object> chaos(@PathVariable("service") String service,
                                     @PathVariable("type") String type,
                                     @RequestParam Map<String, String> params) {
        ManagedService svc = props.services().get(service);
        if (svc == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "unknown service " + service);
        }
        if (!CHAOS_TYPES.contains(type)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "unknown chaos type " + type);
        }
        StringBuilder url = new StringBuilder(svc.baseUrl()).append("/chaos/").append(type);
        String sep = "?";
        for (Map.Entry<String, String> p : params.entrySet()) {
            if (p.getKey().matches("[A-Za-z]+") && p.getValue().matches("[0-9.]+")) {
                url.append(sep).append(p.getKey()).append('=').append(p.getValue());
                sep = "&";
            }
        }
        try {
            return gateway.postJson(url.toString());
        } catch (Exception e) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "could not reach " + service + ": " + e.getMessage());
        }
    }

    private Map<String, Object> safeGet(String url) {
        try {
            return gateway.getJson(url);
        } catch (Exception e) {
            return Map.of();
        }
    }
}
