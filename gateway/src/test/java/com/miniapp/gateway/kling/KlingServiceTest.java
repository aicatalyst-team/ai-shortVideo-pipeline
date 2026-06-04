package com.miniapp.gateway.kling;

import io.github.resilience4j.circuitbreaker.CallNotPermittedException;
import io.github.resilience4j.circuitbreaker.CircuitBreaker;
import io.github.resilience4j.circuitbreaker.CircuitBreakerConfig;
import io.github.resilience4j.circuitbreaker.CircuitBreakerRegistry;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;

import java.time.Duration;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class KlingServiceTest {

  MockWebServer mockKling;
  KlingService service;
  CircuitBreaker breaker;

  @BeforeEach
  void setup() throws Exception {
    mockKling = new MockWebServer();
    mockKling.start();

    CircuitBreakerConfig config = CircuitBreakerConfig.custom()
      .slidingWindowType(CircuitBreakerConfig.SlidingWindowType.COUNT_BASED)
      .slidingWindowSize(10)
      .minimumNumberOfCalls(5)
      .failureRateThreshold(30f)
      .waitDurationInOpenState(Duration.ofSeconds(2))
      .permittedNumberOfCallsInHalfOpenState(2)
      .automaticTransitionFromOpenToHalfOpenEnabled(true)
      .build();
    CircuitBreakerRegistry registry = CircuitBreakerRegistry.of(config);
    breaker = registry.circuitBreaker("kling-submit");

    KlingProperties props = new KlingProperties();
    props.setBaseUrl("http://localhost:" + mockKling.getPort());
    props.setAccessKey("test-key");
    props.setDefaultMode("std");

    WebClient webClient = WebClient.builder().baseUrl(props.getBaseUrl()).build();
    service = new KlingService(webClient, props, registry);
  }

  @AfterEach
  void tearDown() throws Exception {
    mockKling.shutdown();
  }

  private Map<String, Object> payload() {
    return Map.of("image", "http://x.png", "model", "kling-v2-5-turbo", "duration", 5);
  }

  private MockResponse json(int status, String body) {
    return new MockResponse()
      .setResponseCode(status)
      .setHeader("Content-Type", "application/json")
      .setBody(body);
  }

  @Test
  void firstSuccess_circuitStaysClosed() {
    mockKling.enqueue(json(200, "{\"task_id\":\"t1\"}"));

    StepVerifier.create(service.submitImage2Video(payload()))
      .assertNext(resp -> assertThat(resp).containsKey("task_id"))
      .verifyComplete();
    assertThat(breaker.getState()).isEqualTo(CircuitBreaker.State.CLOSED);
  }

  @Test
  void enough5xx_opensCircuit() {
    for (int i = 0; i < 5; i++) {
    mockKling.enqueue(new MockResponse().setResponseCode(503));
    }

    for (int i = 0; i < 5; i++) {
    service.submitImage2Video(payload())
        .onErrorResume(e -> Mono.empty())
        .block();
    }

    assertThat(breaker.getState()).isEqualTo(CircuitBreaker.State.OPEN);
    assertThat(breaker.getMetrics().getFailureRate()).isGreaterThanOrEqualTo(30f);
  }

  @Test
  void openCircuit_rejectsImmediately() {
    breaker.transitionToOpenState();

    StepVerifier.create(service.submitImage2Video(payload()))
      .expectError(CallNotPermittedException.class)
      .verify();
    assertThat(mockKling.getRequestCount()).isZero();
  }

  @Test
  void halfOpen_allowsLimitedCalls() throws InterruptedException {
    breaker.transitionToOpenState();
    Thread.sleep(2200);
    assertThat(breaker.getState()).isEqualTo(CircuitBreaker.State.HALF_OPEN);

    mockKling.enqueue(json(200, "{\"task_id\":\"probe1\"}"));
    mockKling.enqueue(json(200, "{\"task_id\":\"probe2\"}"));

    service.submitImage2Video(payload()).block();
    service.submitImage2Video(payload()).block();

    assertThat(breaker.getState()).isEqualTo(CircuitBreaker.State.CLOSED);
  }

  @Test
  void halfOpen_failureReopensCircuit() throws InterruptedException {
    breaker.transitionToOpenState();
    Thread.sleep(2200);
    assertThat(breaker.getState()).isEqualTo(CircuitBreaker.State.HALF_OPEN);

    mockKling.enqueue(new MockResponse().setResponseCode(503));
    mockKling.enqueue(new MockResponse().setResponseCode(503));
    service.submitImage2Video(payload()).onErrorResume(e -> Mono.empty()).block();
    service.submitImage2Video(payload()).onErrorResume(e -> Mono.empty()).block();

    assertThat(breaker.getState()).isEqualTo(CircuitBreaker.State.OPEN);
  }

  @Test
  void fourxx_doesNotThrowCallNotPermitted() {
    mockKling.enqueue(json(400, "{\"error\":\"bad request\"}"));

    StepVerifier.create(service.submitImage2Video(payload()))
      .expectErrorMatches(e -> !(e instanceof CallNotPermittedException))
      .verify();
  }

  @Test
  void notConfigured_returnsKlingNotConfigured() {
    KlingProperties props = new KlingProperties();
    props.setAccessKey("");
    KlingService unconfigured = new KlingService(
      WebClient.builder().baseUrl("http://localhost:1").build(),
      props,
      CircuitBreakerRegistry.ofDefaults());

    StepVerifier.create(unconfigured.submitImage2Video(payload()))
      .expectError(KlingNotConfiguredException.class)
      .verify();
  }

  @Test
  void halfOpen_autoDowngradesProToStd() throws InterruptedException {
    breaker.transitionToOpenState();
    Thread.sleep(2200);
    assertThat(breaker.getState()).isEqualTo(CircuitBreaker.State.HALF_OPEN);

    mockKling.enqueue(json(200, "{\"task_id\":\"t\"}"));
    service.submitImage2Video(Map.of("image", "x", "mode", "pro")).block();

    String body = mockKling.takeRequest().getBody().readUtf8();
    assertThat(body).contains("\"mode\":\"std\"");
    assertThat(body).contains("\"_downgraded_from\":\"pro\"");
  }
}
