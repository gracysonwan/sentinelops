package com.sentinelops.remediation;

import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;

import java.util.Collections;
import java.util.Map;

/** Talks to the microservices over HTTP with short timeouts. */
@Component
public class HttpServiceGateway implements ServiceGateway {

    private static final ParameterizedTypeReference<Map<String, Object>> JSON_MAP =
            new ParameterizedTypeReference<>() {
            };

    private final RestClient http;
    private final String orderServiceUrl;

    public HttpServiceGateway(SentinelProperties properties) {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(800);
        factory.setReadTimeout(2500);
        this.http = RestClient.builder().requestFactory(factory).build();
        this.orderServiceUrl = properties.orderServiceUrl();
    }

    @Override
    public String health(String baseUrl) {
        try {
            Map<String, Object> body = getJson(baseUrl + "/actuator/health");
            Object status = body.get("status");
            return status == null ? "UNKNOWN" : status.toString();
        } catch (RestClientResponseException e) {
            // Spring returns 503 with {"status":"DOWN"} when a health indicator is down
            return "DOWN";
        } catch (Exception e) {
            return "UNREACHABLE";
        }
    }

    @Override
    public void routePayment(String target) {
        http.post().uri(orderServiceUrl + "/admin/routing/payment?target=" + target).retrieve().toBodilessEntity();
    }

    @Override
    public void resetChaos(String baseUrl) {
        http.post().uri(baseUrl + "/chaos/reset").retrieve().toBodilessEntity();
    }

    /** GET a JSON object; returns an empty map if the body is empty. */
    public Map<String, Object> getJson(String url) {
        Map<String, Object> body = http.get().uri(url).retrieve().body(JSON_MAP);
        return body == null ? Collections.emptyMap() : body;
    }

    /** POST without a body and return the JSON answer. */
    public Map<String, Object> postJson(String url) {
        Map<String, Object> body = http.post().uri(url).retrieve().body(JSON_MAP);
        return body == null ? Collections.emptyMap() : body;
    }
}
