package com.sentinelops.chaos;

import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * Registers the chaos interceptor and publishes the injected-fault values as metrics.
 * The sentinel_chaos_* gauges are ground truth for the dashboard and the experiments only;
 * the AI layer never uses them as model inputs.
 */
@Configuration
public class ChaosWebConfig implements WebMvcConfigurer {

    private final ChaosState state;

    public ChaosWebConfig(ChaosState state, MeterRegistry registry) {
        this.state = state;
        Gauge.builder("sentinel.chaos.latency.ms", state, ChaosState::currentLatencyMs)
                .description("Injected extra latency per request (ms)")
                .register(registry);
        Gauge.builder("sentinel.chaos.error.rate", state, ChaosState::currentErrorRate)
                .description("Injected HTTP 500 probability")
                .register(registry);
        Gauge.builder("sentinel.chaos.leaked.mb", state, ChaosState::leakedMb)
                .description("Heap retained by the memory-leak fault (MB)")
                .register(registry);
    }

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(new ChaosInterceptor(state))
                .excludePathPatterns("/actuator/**", "/chaos/**", "/admin/**", "/error");
    }
}
