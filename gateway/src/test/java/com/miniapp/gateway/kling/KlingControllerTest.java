package com.miniapp.gateway.kling;

import io.github.resilience4j.circuitbreaker.CallNotPermittedException;
import io.github.resilience4j.circuitbreaker.CircuitBreaker;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.reactive.server.WebTestClient;
import reactor.core.publisher.Mono;

import java.util.Map;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@TestPropertySource(properties = {
    "gateway.auth.jwt-secret=test-secret-must-be-at-least-32-bytes-long!",
    "gateway.auth.public-paths[0]=/internal/**",
    "gateway.ratelimit.whitelist[0]=/internal/**"
})
class KlingControllerTest {

  @Autowired
  WebTestClient client;

  @MockBean
  KlingService klingService;

  @Test
  void submit_returns200OnSuccess() {
    Mockito.when(klingService.submitImage2Video(Mockito.any()))
      .thenReturn(Mono.just(Map.of("task_id", "TASK1", "status", "submitted")));

    client.post().uri("/internal/kling/submit/image2video")
      .bodyValue(Map.of("image", "x"))
      .exchange()
      .expectStatus().isOk()
      .expectBody()
      .jsonPath("$.task_id").isEqualTo("TASK1");
  }

  @Test
  void submit_returns503OnCircuitOpen() {
    Mockito.when(klingService.submitImage2Video(Mockito.any()))
      .thenReturn(Mono.error(CallNotPermittedException.createCallNotPermittedException(
        CircuitBreaker.ofDefaults("kling-submit"))));
    Mockito.when(klingService.currentMetrics())
      .thenReturn(Map.of("state", "OPEN", "failure_rate", 50.0));

    client.post().uri("/internal/kling/submit/image2video")
      .bodyValue(Map.of("image", "x"))
      .exchange()
      .expectStatus().isEqualTo(503)
      .expectBody()
      .jsonPath("$.error").isEqualTo("kling_circuit_open")
      .jsonPath("$.retry_after_sec").isEqualTo(60)
      .jsonPath("$.circuit_metrics.state").isEqualTo("OPEN");
  }

  @Test
  void submit_returns503OnNotConfigured() {
    Mockito.when(klingService.submitImage2Video(Mockito.any()))
      .thenReturn(Mono.error(new KlingNotConfiguredException("kling access_key not configured")));

    client.post().uri("/internal/kling/submit/image2video")
      .bodyValue(Map.of("image", "x"))
      .exchange()
      .expectStatus().isEqualTo(503)
      .expectBody()
      .jsonPath("$.error").isEqualTo("kling_not_configured");
  }

  @Test
  void circuitStatus_endpoint_returnsCurrentMetrics() {
    Mockito.when(klingService.currentMetrics())
      .thenReturn(Map.of("state", "CLOSED", "failure_rate", 0.0));

    client.get().uri("/internal/kling/circuit")
      .exchange()
      .expectStatus().isOk()
      .expectBody()
      .jsonPath("$.state").isEqualTo("CLOSED");
  }
}
