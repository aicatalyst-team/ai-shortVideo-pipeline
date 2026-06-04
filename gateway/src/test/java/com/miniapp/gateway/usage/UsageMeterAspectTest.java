package com.miniapp.gateway.usage;

import com.miniapp.gateway.llm.AllProvidersFailedException;
import com.miniapp.gateway.llm.FallbackAttempt;
import com.miniapp.gateway.llm.LlmCallWriter;
import com.miniapp.gateway.llm.LlmChatRequest;
import com.miniapp.gateway.llm.LlmChatResponse;
import com.miniapp.gateway.llm.RoutingResult;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.EnableAspectJAutoProxy;
import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;

import java.util.List;

import static org.mockito.ArgumentMatchers.any;

@SpringBootTest(classes = UsageMeterAspectTest.TestConfig.class)
@Import(UsageMeterAspect.class)
class UsageMeterAspectTest {

  @MockBean
  LlmCallWriter writer;

  @Autowired
  TestLlmService testService;

  @Configuration
  @EnableAspectJAutoProxy(proxyTargetClass = true)
  static class TestConfig {
    @Bean
    TestLlmService testLlmService() {
    return new TestLlmService();
    }
  }

  static class TestLlmService {
    @MeasureLlmCall
    public Mono<RoutingResult> route(LlmChatRequest req) {
    return Mono.just(new RoutingResult(
        LlmChatResponse.builder()
          .content("ok")
          .providerName("deepseek")
          .modelName("deepseek-chat")
          .inputTokens(10)
          .outputTokens(20)
          .costCny(0.001)
          .latencyMs(50)
          .build(),
        List.of(new FallbackAttempt("deepseek", "deepseek-chat", "success", 0, 50, ""))
    ));
    }

    @MeasureLlmCall
    public Mono<RoutingResult> routeError(LlmChatRequest req) {
    List<FallbackAttempt> chain =
        List.of(new FallbackAttempt("deepseek", "x", "5xx", 503, 100, "err"));
    return Mono.error(new AllProvidersFailedException(chain));
    }
  }

  private LlmChatRequest req() {
    return LlmChatRequest.builder()
      .messages(List.of(new LlmChatRequest.Message("user", "hi")))
      .tenantId("tA")
      .bizType("test")
      .build();
  }

  @Test
  void measure_success_callsRecordCall() {
    StepVerifier.create(testService.route(req()))
      .expectNextCount(1)
      .verifyComplete();

    Mockito.verify(writer).recordCall(any(LlmChatRequest.class), any(RoutingResult.class), any());
    Mockito.verify(writer, Mockito.never()).recordFailure(any(), any(), any());
  }

  @Test
  void measure_allProvidersFailed_callsRecordFailure() {
    StepVerifier.create(testService.routeError(req()))
      .expectError(AllProvidersFailedException.class)
      .verify();

    Mockito.verify(writer).recordFailure(any(LlmChatRequest.class), any(List.class), any());
    Mockito.verify(writer, Mockito.never()).recordCall(any(), any(), any());
  }
}
