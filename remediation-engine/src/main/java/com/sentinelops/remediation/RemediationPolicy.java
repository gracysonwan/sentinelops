package com.sentinelops.remediation;

import java.util.ArrayList;
import java.util.List;

/**
 * Decides which recovery actions to run for an anomaly, based on the root cause reported by the
 * AI layer and on what the affected service supports.
 *
 *  - Services with a standby instance (payment) are first REROUTED so users are not affected,
 *    then RESTARTED, verified, and finally FAILED BACK to the healed primary.
 *  - Other services are RESTARTED and verified.
 *  - A memory leak can only be cleared by a restart, so it is always restarted.
 */
public class RemediationPolicy {

    public enum Action {
        REROUTE_TO_STANDBY,
        RESTART_CONTAINER,
        VERIFY_HEALTH,
        FAILBACK_TO_PRIMARY
    }

    public List<Action> plan(boolean hasStandby) {
        List<Action> actions = new ArrayList<>();
        if (hasStandby) {
            actions.add(Action.REROUTE_TO_STANDBY);
        }
        actions.add(Action.RESTART_CONTAINER);
        actions.add(Action.VERIFY_HEALTH);
        if (hasStandby) {
            actions.add(Action.FAILBACK_TO_PRIMARY);
        }
        return actions;
    }

    /** Human-readable explanation stored with each remediation event. */
    public String explain(String rootCause, boolean hasStandby) {
        String cause = rootCause == null ? "unknown" : rootCause;
        String base = switch (cause) {
            case "memory" -> "Heap is filling up (likely leak) - only a restart releases it";
            case "latency" -> "Response times are climbing - restart clears the degraded instance";
            case "errors" -> "Error rate is rising - restart replaces the failing instance";
            case "cpu" -> "CPU saturation - restart resets the runaway workload";
            case "unavailable" -> "Service stopped responding - restart required";
            default -> "Anomalous behaviour detected - restart the instance";
        };
        return hasStandby ? base + "; traffic moved to standby during recovery" : base;
    }
}
