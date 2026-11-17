package com.sentinelops.remediation;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;
import org.springframework.context.annotation.Bean;

import java.time.Duration;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

@SpringBootApplication
@ConfigurationPropertiesScan
public class RemediationEngineApplication {

    private static final Logger log = LoggerFactory.getLogger(RemediationEngineApplication.class);

    public static void main(String[] args) {
        SpringApplication.run(RemediationEngineApplication.class, args);
    }

    @Bean(destroyMethod = "shutdownNow")
    ExecutorService remediationExecutor() {
        return Executors.newFixedThreadPool(4, r -> {
            Thread t = new Thread(r, "remediation-worker");
            t.setDaemon(true);
            return t;
        });
    }

    @Bean
    RemediationOrchestrator remediationOrchestrator(SentinelProperties props, HttpServiceGateway gateway,
                                                    ExecutorService remediationExecutor, MeterRegistry registry) {
        DockerClient docker = new DockerClient(props.dockerSocket());
        RemediationOrchestrator.Listener metrics = new RemediationOrchestrator.Listener() {
            @Override
            public void onAction(String service, RemediationPolicy.Action action) {
                Counter.builder("sentinel.remediation.actions")
                        .description("Remediation actions executed")
                        .tag("service", service)
                        .tag("action", action.name())
                        .register(registry)
                        .increment();
            }

            @Override
            public void onFinished(RemediationEvent event) {
                Counter.builder("sentinel.remediation.incidents")
                        .description("Remediation runs by final status")
                        .tag("service", event.getService())
                        .tag("status", event.getStatus().name())
                        .register(registry)
                        .increment();
                if (event.getRecoverySeconds() != null) {
                    Timer.builder("sentinel.remediation.recovery")
                            .description("Time from AI detection to verified recovery")
                            .tag("service", event.getService())
                            .register(registry)
                            .record(Duration.ofMillis(Math.round(event.getRecoverySeconds() * 1000)));
                }
                log.info("Remediation #{} for {} finished: {} {}", event.getId(), event.getService(),
                        event.getStatus(), event.getSteps());
            }
        };
        RemediationOrchestrator orchestrator = new RemediationOrchestrator(
                props.services(), gateway, docker, remediationExecutor, System::currentTimeMillis, metrics,
                props.dryRun(), props.autoRemediation(), props.cooldownSeconds() * 1000L,
                props.recoveryTimeoutSeconds() * 1000L, 2000);
        Gauge.builder("sentinel.remediation.active", orchestrator, RemediationOrchestrator::activeRemediations)
                .description("Remediations currently running")
                .register(registry);
        Gauge.builder("sentinel.remediation.auto.enabled", orchestrator, o -> o.isAutoRemediation() ? 1 : 0)
                .description("1 when autonomous remediation is switched on")
                .register(registry);
        log.info("Remediation engine ready: services={} dryRun={} dockerSocketPresent={}",
                props.services().keySet(), props.dryRun(), docker.isAvailable());
        return orchestrator;
    }
}
