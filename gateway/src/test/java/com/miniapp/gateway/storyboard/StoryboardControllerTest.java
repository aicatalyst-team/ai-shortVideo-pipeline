package com.miniapp.gateway.storyboard;

import com.miniapp.gateway.auth.JwtService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.SpringBootTest.WebEnvironment;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.reactive.server.WebTestClient;
import reactor.core.publisher.Mono;

import java.util.Map;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;

@SpringBootTest(webEnvironment = WebEnvironment.RANDOM_PORT)
@TestPropertySource(properties = {
    "gateway.auth.jwt-secret=test-secret-must-be-at-least-32-bytes-long!",
    "gateway.upstream.python-base-url=http://localhost:9999",
    "management.health.db.enabled=false"
})
class StoryboardControllerTest {

  @Autowired
  private WebTestClient webClient;

  @Autowired
  private JwtService jwtService;

  @MockBean
  private PythonClient pythonClient;

  @Test
  void noJwt_returns401() {
    webClient.get().uri("/api/v1/storyboards/PLAN001")
      .exchange()
      .expectStatus().isUnauthorized()
      .expectBody()
      .jsonPath("$.error").isEqualTo("unauthorized");
  }

  @Test
  void invalidJwt_returns401() {
    webClient.get().uri("/api/v1/storyboards/PLAN001")
      .header("Authorization", "Bearer garbage-token")
      .exchange()
      .expectStatus().isUnauthorized();
  }

  @Test
  void validJwt_forwardsToPython() {
    when(pythonClient.getStoryboard(eq("PLAN001"), anyBoolean(), any()))
      .thenReturn(Mono.just(Map.of("plan_id", "PLAN001", "title", "test")));

    String token = jwtService.issue("u1", "t1");

    webClient.get().uri("/api/v1/storyboards/PLAN001")
      .header("Authorization", "Bearer " + token)
      .exchange()
      .expectStatus().isOk()
      .expectBody()
      .jsonPath("$.plan_id").isEqualTo("PLAN001")
      .jsonPath("$.title").isEqualTo("test");
  }

  @Test
  void traceIdHeader_isEchoed() {
    when(pythonClient.getStoryboard(eq("PLAN001"), anyBoolean(), any()))
      .thenReturn(Mono.just(Map.of("plan_id", "PLAN001")));

    String token = jwtService.issue("u1", "t1");

    webClient.get().uri("/api/v1/storyboards/PLAN001")
      .header("Authorization", "Bearer " + token)
      .header("X-Trace-Id", "test-trace-xyz")
      .exchange()
      .expectStatus().isOk()
      .expectHeader().valueEquals("X-Trace-Id", "test-trace-xyz");
  }

  @Test
  void healthEndpoint_isPublicAndNoJwt() {
    webClient.get().uri("/actuator/health")
      .exchange()
      .expectStatus().is2xxSuccessful();
  }
}
