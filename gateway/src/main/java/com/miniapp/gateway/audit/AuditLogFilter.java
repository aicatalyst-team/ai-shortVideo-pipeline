package com.miniapp.gateway.audit;

import com.miniapp.gateway.auth.JwtAuthFilter;
import com.miniapp.gateway.trace.TraceIdFilter;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import org.springframework.web.server.WebFilter;
import org.springframework.web.server.WebFilterChain;
import reactor.core.publisher.Mono;

@Component
@Order(Ordered.LOWEST_PRECEDENCE)
@Slf4j
public class AuditLogFilter implements WebFilter {

  @Override
  public Mono<Void> filter(ServerWebExchange exchange, WebFilterChain chain) {
    long start = System.currentTimeMillis();
    String method = exchange.getRequest().getMethod().name();
    String path = exchange.getRequest().getPath().value();

    return chain.filter(exchange).doFinally(signal -> {
    long latency = System.currentTimeMillis() - start;
    Integer status = exchange.getResponse().getStatusCode() != null
        ? exchange.getResponse().getStatusCode().value()
        : 0;
    String userId = (String) exchange.getAttributes().getOrDefault(JwtAuthFilter.ATTR_USER_ID, "");
    String tenantId = (String) exchange.getAttributes().getOrDefault(JwtAuthFilter.ATTR_TENANT_ID, "");
    String traceId = (String) exchange.getAttributes().getOrDefault(TraceIdFilter.ATTR_TRACE_ID, "");

    log.info("audit method={} path={} status={} latency_ms={} user={} tenant={} trace={}",
        method, path, status, latency, userId, tenantId, traceId);
    });
  }
}
