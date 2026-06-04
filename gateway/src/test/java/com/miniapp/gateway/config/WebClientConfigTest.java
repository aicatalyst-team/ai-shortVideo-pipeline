package com.miniapp.gateway.config;

import com.miniapp.gateway.trace.TraceIdFilter;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.RecordedRequest;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.slf4j.MDC;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientResponseException;

import java.io.IOException;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 *  测试：验证 WebClient 容错配置
 * - 5xx 自动重试 N 次
 * - 4xx 不重试
 * - TraceId 自动透传到下游请求头
 */
@SpringBootTest
class WebClientConfigTest {

  static MockWebServer mockServer;

  @Autowired
  @Qualifier("pythonWebClient")
  WebClient webClient;

  int requestCountBefore;

  @BeforeEach
  void startMock() throws IOException {
    if (mockServer == null) {
    mockServer = new MockWebServer();
    mockServer.start();
    }
    requestCountBefore = mockServer.getRequestCount();
  }

  @AfterEach
  void tearDown() {
    MDC.clear();
  }

  @DynamicPropertySource
  static void overrideProps(DynamicPropertyRegistry registry) throws IOException {
    if (mockServer == null) {
    mockServer = new MockWebServer();
    mockServer.start();
    }
    registry.add("gateway.upstream.python-base-url",
      () -> "http://localhost:" + mockServer.getPort());
    registry.add("gateway.auth.jwt-secret",
      () -> "test-secret-must-be-at-least-32-bytes-long!");
    registry.add("gateway.upstream.retry-max-attempts", () -> "2");
    registry.add("gateway.upstream.retry-initial-backoff-ms", () -> "10");
    registry.add("gateway.upstream.timeout-seconds", () -> "5");
    registry.add("gateway.upstream.connect-timeout-ms", () -> "2000");
  }

  @Test
  void retries_5xx_thenSucceeds() throws InterruptedException {
    mockServer.enqueue(new MockResponse().setResponseCode(503));
    mockServer.enqueue(new MockResponse().setResponseCode(503));
    mockServer.enqueue(new MockResponse().setResponseCode(200)
      .setBody("{\"ok\":true}")
      .setHeader("Content-Type", "application/json"));

    String body = webClient.get().uri("/test")
      .retrieve().bodyToMono(String.class)
      .block();

    assertThat(body).contains("ok");
    // 总共 3 次请求（1 初始 + 2 重试）
    assertThat(mockServer.getRequestCount() - requestCountBefore).isEqualTo(3);
  }

  @Test
  void retries_exhausted_throwsException() {
    // 永远 503，重试 2 次后仍失败
    for (int i = 0; i < 3; i++) {
    mockServer.enqueue(new MockResponse().setResponseCode(503));
    }

    assertThatThrownBy(() -> webClient.get().uri("/test")
      .retrieve().bodyToMono(String.class)
      .block())
      .isInstanceOf(Exception.class);
  }

  @Test
  void doesNotRetry_4xx() throws InterruptedException {
    mockServer.enqueue(new MockResponse().setResponseCode(404));

    assertThatThrownBy(() -> webClient.get().uri("/test")
      .retrieve().bodyToMono(String.class)
      .block())
      .isInstanceOf(WebClientResponseException.NotFound.class);

    // 只有 1 次请求（4xx 不重试）
    assertThat(mockServer.getRequestCount() - requestCountBefore).isEqualTo(1);
  }

  @Test
  void traceId_propagatedToDownstream() throws InterruptedException {
    MDC.put(TraceIdFilter.ATTR_TRACE_ID, "test-trace-xyz-001");
    mockServer.enqueue(new MockResponse().setResponseCode(200).setBody("{}"));

    webClient.get().uri("/test").retrieve().bodyToMono(String.class).block();

    RecordedRequest req = mockServer.takeRequest(2, TimeUnit.SECONDS);
    assertThat(req).isNotNull();
    assertThat(req.getHeader(TraceIdFilter.HEADER_TRACE_ID)).isEqualTo("test-trace-xyz-001");
  }

  @Test
  void noTraceId_doesNotAddHeader() throws InterruptedException {
    // MDC 为空
    MDC.clear();
    mockServer.enqueue(new MockResponse().setResponseCode(200).setBody("{}"));

    webClient.get().uri("/test").retrieve().bodyToMono(String.class).block();

    RecordedRequest req = mockServer.takeRequest(2, TimeUnit.SECONDS);
    assertThat(req.getHeader(TraceIdFilter.HEADER_TRACE_ID)).isNull();
  }
}
