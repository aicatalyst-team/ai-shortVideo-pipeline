package com.miniapp.gateway.ratelimit;

import com.miniapp.gateway.auth.JwtService;
import com.miniapp.gateway.frame.ImageUploadService;
import com.miniapp.gateway.storyboard.PythonClient;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.HttpHeaders;
import org.springframework.test.annotation.DirtiesContext;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.reactive.server.WebTestClient;
import reactor.core.publisher.Mono;

import java.util.Map;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyString;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@DirtiesContext(classMode = DirtiesContext.ClassMode.AFTER_EACH_TEST_METHOD)
@TestPropertySource(properties = {
    "gateway.auth.jwt-secret=test-secret-must-be-at-least-32-bytes-long-xx",
    "gateway.upstream.python-base-url=http://localhost:9999",
    "gateway.ratelimit.rules[0].path=/api/v1/storyboards/*",
    "gateway.ratelimit.rules[0].user-per-minute=3",
    "gateway.ratelimit.rules[0].global-per-minute=10",
    "gateway.ratelimit.default-rule.path=**",
    "gateway.ratelimit.default-rule.user-per-minute=100",
    "gateway.ratelimit.default-rule.global-per-minute=1000",
    "management.health.db.enabled=false"
})
class RateLimitFilterTest {

  @Autowired
  private WebTestClient client;

  @Autowired
  private JwtService jwtService;

  @MockBean
  private PythonClient pythonClient;

  @MockBean
  private ImageUploadService uploadService;

  @BeforeEach
  void mockPython() {
    Mockito.when(pythonClient.getStoryboard(anyString(), anyBoolean(), any()))
      .thenReturn(Mono.just(Map.of("plan_id", "P1", "status", "ok")));
  }

  private String tokenForUser(String userId, String tenantId) {
    return jwtService.issue(userId, tenantId);
  }

  @Test
  void underLimit_returns200() {
    String token = tokenForUser("u1", "tenantA");
    for (int i = 0; i < 3; i++) {
    client.get().uri("/api/v1/storyboards/SB1")
        .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
        .exchange()
        .expectStatus().is2xxSuccessful();
    }
  }

  @Test
  void overUserLimit_returns429WithHeaders() {
    String token = tokenForUser("u2", "tenantA");
    for (int i = 0; i < 3; i++) {
    client.get().uri("/api/v1/storyboards/SB2")
        .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
        .exchange()
        .expectStatus().is2xxSuccessful();
    }

    client.get().uri("/api/v1/storyboards/SB2")
      .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
      .exchange()
      .expectStatus().isEqualTo(429)
      .expectHeader().valueEquals(HttpHeaders.RETRY_AFTER, "60")
      .expectHeader().valueEquals("X-RateLimit-Limit", "3")
      .expectBody()
      .jsonPath("$.error").isEqualTo("rate_limited")
      .jsonPath("$.reason").isEqualTo("user_rate_limited")
      .jsonPath("$.retry_after_sec").isEqualTo(60);
  }

  @Test
  void differentUsers_haveIndependentLimits() {
    String tokenU3 = tokenForUser("u3", "tenantA");
    String tokenU4 = tokenForUser("u4", "tenantA");

    for (int i = 0; i < 3; i++) {
    client.get().uri("/api/v1/storyboards/SB3")
        .header(HttpHeaders.AUTHORIZATION, "Bearer " + tokenU3)
        .exchange()
        .expectStatus().is2xxSuccessful();
    client.get().uri("/api/v1/storyboards/SB3")
        .header(HttpHeaders.AUTHORIZATION, "Bearer " + tokenU4)
        .exchange()
        .expectStatus().is2xxSuccessful();
    }

    client.get().uri("/api/v1/storyboards/SB3")
      .header(HttpHeaders.AUTHORIZATION, "Bearer " + tokenU3)
      .exchange()
      .expectStatus().isEqualTo(429);
    client.get().uri("/api/v1/storyboards/SB3")
      .header(HttpHeaders.AUTHORIZATION, "Bearer " + tokenU4)
      .exchange()
      .expectStatus().isEqualTo(429);
  }

  @Test
  void healthEndpoint_isWhitelisted() {
    for (int i = 0; i < 100; i++) {
    client.get().uri("/actuator/health")
        .exchange()
        .expectStatus().isOk();
    }
  }

  @Test
  void rateLimited_responseBodyHasTraceId() {
    String token = tokenForUser("u5", "tenantA");
    for (int i = 0; i < 3; i++) {
    client.get().uri("/api/v1/storyboards/SB5")
        .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
        .exchange();
    }

    client.get().uri("/api/v1/storyboards/SB5")
      .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
      .header("X-Trace-Id", "trace-test-001")
      .exchange()
      .expectStatus().isEqualTo(429)
      .expectBody()
      .jsonPath("$.trace_id").isEqualTo("trace-test-001");
  }

  @Test
  void globalLimitHit_independentOfUser() {
    for (int i = 0; i < 10; i++) {
    String token = tokenForUser("global_u" + i, "tenantG");
    client.get().uri("/api/v1/storyboards/GLB")
        .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
        .exchange()
        .expectStatus().is2xxSuccessful();
    }

    String token = tokenForUser("global_u11", "tenantG");
    client.get().uri("/api/v1/storyboards/GLB")
      .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
      .exchange()
      .expectStatus().isEqualTo(429)
      .expectBody()
      .jsonPath("$.reason").isEqualTo("global_rate_limited");
  }
}
