package com.miniapp.gateway.llm;

import org.junit.jupiter.api.Test;
import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;

import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;

class LlmRouterTest {

  private LlmRouter router;

  private LlmProvider stubProvider(String name, ProviderBehavior behavior) {
    return new LlmProvider() {
    private final AtomicInteger calls = new AtomicInteger();

    @Override
    public String name() {
      return name;
    }

    @Override
    public String defaultModel() {
      return name + "-model";
    }

    @Override
    public Mono<LlmChatResponse> chat(LlmChatRequest request) {
      return behavior.respond(calls.incrementAndGet(), name);
    }
    };
  }

  @FunctionalInterface
  interface ProviderBehavior {
    Mono<LlmChatResponse> respond(int callNum, String providerName);
  }

  private LlmChatRequest req() {
    return LlmChatRequest.builder()
      .messages(List.of(new LlmChatRequest.Message("user", "hi")))
      .bizType("test")
      .tenantId("tA")
      .build();
  }

  private LlmChatResponse okResp(String provider) {
    return LlmChatResponse.builder()
      .content("ok from " + provider)
      .inputTokens(10)
      .outputTokens(20)
      .costCny(0.001)
      .providerName(provider)
      .modelName(provider + "-model")
      .latencyMs(50)
      .build();
  }

  private void setupRouter(List<LlmProvider> providers, List<String> order) {
    router = new LlmRouter(providers);
    try {
    var orderField = LlmRouter.class.getDeclaredField("providerOrder");
    orderField.setAccessible(true);
    orderField.set(router, order);

    var thresholdField = LlmRouter.class.getDeclaredField("failThreshold");
    thresholdField.setAccessible(true);
    thresholdField.setInt(router, 3);

    var ttlField = LlmRouter.class.getDeclaredField("blacklistTtlSec");
    ttlField.setAccessible(true);
    ttlField.setLong(router, 300L);
    } catch (Exception e) {
    throw new RuntimeException(e);
    }
    router.init();
  }

  @Test
  void firstProvider_success_noFallover() {
    setupRouter(
      List.of(stubProvider("p1", (n, name) -> Mono.just(okResp(name)))),
      List.of("p1"));

    StepVerifier.create(router.route(req()))
      .assertNext(result -> {
        assertThat(result.getResponse().getProviderName()).isEqualTo("p1");
        assertThat(result.getChain()).hasSize(1);
        assertThat(result.getChain().get(0).getStatus()).isEqualTo("success");
      })
      .verifyComplete();
  }

  @Test
  void firstProvider_5xx_switchesToSecond() {
    setupRouter(
      List.of(
        stubProvider("p1", (n, name) -> Mono.error(
            new LlmProviderException(name, "5xx", 503, "down", null))),
        stubProvider("p2", (n, name) -> Mono.just(okResp(name)))
      ),
      List.of("p1", "p2"));

    StepVerifier.create(router.route(req()))
      .assertNext(result -> {
        assertThat(result.getResponse().getProviderName()).isEqualTo("p2");
        assertThat(result.getChain()).hasSize(2);
        assertThat(result.getChain().get(0).getStatus()).isEqualTo("5xx");
        assertThat(result.getChain().get(1).getStatus()).isEqualTo("success");
      })
      .verifyComplete();
  }

  @Test
  void allFail_throwsAllProvidersFailed() {
    setupRouter(
      List.of(
        stubProvider("p1", (n, name) -> Mono.error(
            new LlmProviderException(name, "5xx", 503, "x", null))),
        stubProvider("p2", (n, name) -> Mono.error(
            new LlmProviderException(name, "timeout", 0, "x", null))),
        stubProvider("p3", (n, name) -> Mono.error(
            new LlmProviderException(name, "5xx", 502, "x", null)))
      ),
      List.of("p1", "p2", "p3"));

    StepVerifier.create(router.route(req()))
      .expectErrorSatisfies(e -> {
        assertThat(e).isInstanceOf(AllProvidersFailedException.class);
        var chain = ((AllProvidersFailedException) e).getChain();
        assertThat(chain).hasSize(3);
        assertThat(chain).noneMatch(attempt -> "success".equals(attempt.getStatus()));
      })
      .verify();
  }

  @Test
  void fourxx_propagatesAsBusinessError_noFallover() {
    AtomicInteger p2Called = new AtomicInteger();
    setupRouter(
      List.of(
        stubProvider("p1", (n, name) -> Mono.error(
            new LlmProviderException(name, "4xx", 400, "bad request", null))),
        stubProvider("p2", (n, name) -> {
          p2Called.incrementAndGet();
          return Mono.just(okResp(name));
        })
      ),
      List.of("p1", "p2"));

    StepVerifier.create(router.route(req()))
      .expectError(BusinessErrorException.class)
      .verify();
    assertThat(p2Called).hasValue(0);
  }

  @Test
  void blacklistAfter3Failures_skipsProvider() {
    setupRouter(
      List.of(
        stubProvider("p1", (n, name) -> Mono.error(
            new LlmProviderException(name, "5xx", 503, "down", null))),
        stubProvider("p2", (n, name) -> Mono.just(okResp(name)))
      ),
      List.of("p1", "p2"));

    router.route(req()).block();
    router.route(req()).block();
    router.route(req()).block();
    assertThat(router.isBlacklisted("p1")).isTrue();

    var result = router.route(req()).block();
    assertThat(result).isNotNull();
    assertThat(result.getResponse().getProviderName()).isEqualTo("p2");
    assertThat(result.getChain().get(0).getStatus()).isEqualTo("blacklisted");
  }

  @Test
  void successAfterFailure_resetsCounter() {
    setupRouter(
      List.of(stubProvider("p1", (n, name) -> {
        if (n <= 2) {
        return Mono.error(new LlmProviderException(name, "5xx", 503, "x", null));
        }
        return Mono.just(okResp(name));
      })),
      List.of("p1"));

    router.route(req()).onErrorResume(e -> Mono.empty()).block();
    router.route(req()).onErrorResume(e -> Mono.empty()).block();
    router.route(req()).block();

    assertThat(router.isBlacklisted("p1")).isFalse();
  }
}
