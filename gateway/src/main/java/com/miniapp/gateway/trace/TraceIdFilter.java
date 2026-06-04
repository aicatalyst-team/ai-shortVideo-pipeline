package com.miniapp.gateway.trace;

import org.slf4j.MDC;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import org.springframework.web.server.WebFilter;
import org.springframework.web.server.WebFilterChain;
import reactor.core.publisher.Mono;

import java.util.UUID;

@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class TraceIdFilter implements WebFilter {

  public static final String HEADER_TRACE_ID = "X-Trace-Id";
  public static final String ATTR_TRACE_ID = "traceId";

  @Override
  public Mono<Void> filter(ServerWebExchange exchange, WebFilterChain chain) {
    String incoming = exchange.getRequest().getHeaders().getFirst(HEADER_TRACE_ID);
    String traceId = incoming != null && !incoming.isBlank()
      ? incoming
      : UUID.randomUUID().toString().replace("-", "");

    exchange.getAttributes().put(ATTR_TRACE_ID, traceId);
    exchange.getResponse().getHeaders().set(HEADER_TRACE_ID, traceId);
    MDC.put(ATTR_TRACE_ID, traceId);

    return chain.filter(exchange).doFinally(signal -> MDC.remove(ATTR_TRACE_ID));
  }
}
