package com.miniapp.gateway.trace;

import org.junit.jupiter.api.Test;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;
import org.springframework.mock.web.server.MockServerWebExchange;
import reactor.core.publisher.Mono;

import static org.assertj.core.api.Assertions.assertThat;

class TraceIdFilterTest {

  private final TraceIdFilter filter = new TraceIdFilter();

  @Test
  void incomingHeader_isPropagated() {
    MockServerHttpRequest req = MockServerHttpRequest.get("/api/v1/storyboards/X")
      .header(TraceIdFilter.HEADER_TRACE_ID, "abc-123")
      .build();
    MockServerWebExchange ex = MockServerWebExchange.from(req);

    filter.filter(ex, chain -> Mono.empty()).block();

    String traceId = ex.getAttribute(TraceIdFilter.ATTR_TRACE_ID);
    assertThat(traceId).isEqualTo("abc-123");
    assertThat(ex.getResponse().getHeaders().getFirst(TraceIdFilter.HEADER_TRACE_ID))
      .isEqualTo("abc-123");
  }

  @Test
  void noIncomingHeader_generatesNewId() {
    MockServerHttpRequest req = MockServerHttpRequest.get("/api/v1/storyboards/X").build();
    MockServerWebExchange ex = MockServerWebExchange.from(req);

    filter.filter(ex, chain -> Mono.empty()).block();

    String generated = ex.getAttribute(TraceIdFilter.ATTR_TRACE_ID);
    assertThat(generated).isNotBlank();
    assertThat(generated).hasSize(32);
  }
}
