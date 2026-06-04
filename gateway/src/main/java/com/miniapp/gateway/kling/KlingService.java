package com.miniapp.gateway.kling;

import io.github.resilience4j.circuitbreaker.CircuitBreaker;
import io.github.resilience4j.circuitbreaker.CircuitBreakerRegistry;
import io.github.resilience4j.reactor.circuitbreaker.operator.CircuitBreakerOperator;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.util.HashMap;
import java.util.Map;

@Service
@Slf4j
public class KlingService {

  private static final ParameterizedTypeReference<Map<String, Object>> MAP_TYPE =
    new ParameterizedTypeReference<>() {
    };

  private final WebClient client;
  private final KlingProperties props;
  private final CircuitBreaker breaker;

  public KlingService(
    @Qualifier("klingWebClient") WebClient client,
    KlingProperties props,
    CircuitBreakerRegistry registry
  ) {
    this.client = client;
    this.props = props;
    this.breaker = registry.circuitBreaker("kling-submit");
  }

  public Mono<Map<String, Object>> submitImage2Video(Map<String, Object> body) {
    if (props.getAccessKey() == null || props.getAccessKey().isBlank()) {
    return Mono.error(new KlingNotConfiguredException("kling access_key not configured"));
    }

    Map<String, Object> normalizedBody = applyDowngrade(body);
    return client.post()
      .uri("/v1/videos/image2video")
      .header("Authorization", "Bearer " + signJwt())
      .accept(MediaType.APPLICATION_JSON)
      .bodyValue(normalizedBody)
      .retrieve()
      .bodyToMono(MAP_TYPE)
      .transformDeferred(CircuitBreakerOperator.of(breaker));
  }

  public Mono<Map<String, Object>> queryTaskStatus(String taskId) {
    if (props.getAccessKey() == null || props.getAccessKey().isBlank()) {
    return Mono.error(new KlingNotConfiguredException("kling access_key not configured"));
    }

    return client.get()
      .uri("/v1/videos/image2video/{taskId}", taskId)
      .header("Authorization", "Bearer " + signJwt())
      .accept(MediaType.APPLICATION_JSON)
      .retrieve()
      .bodyToMono(MAP_TYPE);
  }

  Map<String, Object> applyDowngrade(Map<String, Object> body) {
    if (breaker.getState() == CircuitBreaker.State.HALF_OPEN) {
    String currentMode = String.valueOf(body.getOrDefault("mode", props.getDefaultMode()));
    if (!"std".equals(currentMode)) {
      log.warn("[kling] half-open detected, downgrade mode {} -> std", currentMode);
      Map<String, Object> downgraded = new HashMap<>(body);
      downgraded.put("mode", "std");
      downgraded.put("_downgraded_from", currentMode);
      return downgraded;
    }
    }
    return body;
  }

  private String signJwt() {
    return props.getAccessKey();
  }

  public CircuitBreaker.State currentState() {
    return breaker.getState();
  }

  public Map<String, Object> currentMetrics() {
    CircuitBreaker.Metrics metrics = breaker.getMetrics();
    return Map.of(
      "state", breaker.getState().name(),
      "failure_rate", metrics.getFailureRate(),
      "slow_call_rate", metrics.getSlowCallRate(),
      "buffered_calls", metrics.getNumberOfBufferedCalls(),
      "failed_calls", metrics.getNumberOfFailedCalls(),
      "slow_calls", metrics.getNumberOfSlowCalls(),
      "not_permitted_calls", metrics.getNumberOfNotPermittedCalls()
    );
  }
}
