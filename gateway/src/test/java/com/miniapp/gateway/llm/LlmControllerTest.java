package com.miniapp.gateway.llm;

import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.reactive.server.WebTestClient;
import reactor.core.publisher.Mono;

import java.util.List;
import java.util.Map;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@TestPropertySource(properties = {
    "gateway.auth.jwt-secret=test-secret-must-be-at-least-32-bytes-long!",
    "gateway.auth.public-paths[0]=/internal/**",
    "gateway.ratelimit.whitelist[0]=/internal/**",
    "gateway.llm.deepseek.api-key=",
    "gateway.llm.qwen.api-key=",
    "gateway.llm.glm.api-key="
})
class LlmControllerTest {

  @Autowired
  WebTestClient client;

  @MockBean
  LlmRouter router;

  @MockBean
  LlmCallWriter writer;

  @Test
  void chat_returns200OnSuccess() {
    var response = LlmChatResponse.builder()
      .content("hello world")
      .providerName("deepseek")
      .modelName("deepseek-chat")
      .inputTokens(10)
      .outputTokens(20)
      .costCny(0.001)
      .latencyMs(50)
      .build();
    var chain = List.of(new FallbackAttempt("deepseek", "deepseek-chat", "success", 0, 50, ""));
    Mockito.when(router.route(Mockito.any()))
      .thenReturn(Mono.just(new RoutingResult(response, chain)));

    client.post().uri("/internal/llm/chat")
      .bodyValue(Map.of("messages", List.of(Map.of("role", "user", "content", "hi"))))
      .exchange()
      .expectStatus().isOk()
      .expectBody()
      .jsonPath("$.content").isEqualTo("hello world")
      .jsonPath("$.provider").isEqualTo("deepseek")
      .jsonPath("$.fallback_chain[0].status").isEqualTo("success");
  }

  @Test
  void chat_returns503OnAllProvidersFailed() {
    var chain = List.of(
      new FallbackAttempt("deepseek", "x", "5xx", 503, 100, "err1"),
      new FallbackAttempt("qwen", "x", "timeout", 0, 100, "err2"),
      new FallbackAttempt("glm", "x", "5xx", 502, 100, "err3"));
    Mockito.when(router.route(Mockito.any()))
      .thenReturn(Mono.error(new AllProvidersFailedException(chain)));

    client.post().uri("/internal/llm/chat")
      .bodyValue(Map.of("messages", List.of(Map.of("role", "user", "content", "hi"))))
      .exchange()
      .expectStatus().isEqualTo(503)
      .expectBody()
      .jsonPath("$.error").isEqualTo("all_providers_failed")
      .jsonPath("$.fallback_chain[0].provider").isEqualTo("deepseek")
      .jsonPath("$.fallback_chain[2].provider").isEqualTo("glm");
  }
}
