package com.miniapp.gateway.ratelimit;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.miniapp.gateway.auth.JwtAuthFilter;
import com.miniapp.gateway.trace.TraceIdFilter;
import io.github.resilience4j.ratelimiter.RateLimiter;
import io.micrometer.core.instrument.MeterRegistry;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import org.springframework.web.server.WebFilter;
import org.springframework.web.server.WebFilterChain;
import reactor.core.publisher.Mono;

import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 20)
@RequiredArgsConstructor
@Slf4j
public class RateLimitFilter implements WebFilter {

  private static final int RETRY_AFTER_SECONDS = 60;

  private final RateLimitProperties props;
  private final RateLimitRegistry registry;
  private final MeterRegistry meterRegistry;
  private final ObjectMapper objectMapper = new ObjectMapper();

  @Override
  public Mono<Void> filter(ServerWebExchange exchange, WebFilterChain chain) {
    if (!props.isEnabled()) {
    return chain.filter(exchange);
    }

    String path = exchange.getRequest().getPath().value();
    if (registry.isWhitelisted(path)) {
    return chain.filter(exchange);
    }

    Optional<RateLimitProperties.Rule> ruleOpt = registry.matchRule(path);
    if (ruleOpt.isEmpty()) {
    return chain.filter(exchange);
    }
    RateLimitProperties.Rule rule = ruleOpt.get();

    String userId = exchange.getAttribute(JwtAuthFilter.ATTR_USER_ID);
    String tenantId = exchange.getAttribute(JwtAuthFilter.ATTR_TENANT_ID);
    if (userId != null && tenantId != null) {
    String userKey = tenantId + ":" + userId;
    RateLimiter userLimiter = registry.getUserLimiter(userKey, rule);
    if (!userLimiter.acquirePermission()) {
      log.warn("[ratelimit] user limit hit user={} path={} limit={}/min",
        userKey, path, rule.getUserPerMinute());
      markRejected("user", rule.getPath());
      return reject(exchange, "user_rate_limited", rule.getUserPerMinute(),
        userLimiter.getMetrics().getAvailablePermissions());
    }
    }

    RateLimiter globalLimiter = registry.getGlobalLimiter(rule);
    if (!globalLimiter.acquirePermission()) {
    log.warn("[ratelimit] global limit hit path={} limit={}/min", path, rule.getGlobalPerMinute());
    markRejected("global", rule.getPath());
    return reject(exchange, "global_rate_limited", rule.getGlobalPerMinute(),
        globalLimiter.getMetrics().getAvailablePermissions());
    }

    markAllowed(rule.getPath());
    return chain.filter(exchange);
  }

  private Mono<Void> reject(ServerWebExchange exchange, String reason, int limit, int remaining) {
    HttpHeaders headers = exchange.getResponse().getHeaders();
    headers.setContentType(MediaType.APPLICATION_JSON);
    headers.set(HttpHeaders.RETRY_AFTER, String.valueOf(RETRY_AFTER_SECONDS));
    headers.set("X-RateLimit-Limit", String.valueOf(limit));
    headers.set("X-RateLimit-Remaining", String.valueOf(Math.max(0, remaining)));
    exchange.getResponse().setStatusCode(HttpStatus.TOO_MANY_REQUESTS);

    String traceId = exchange.getAttributeOrDefault(TraceIdFilter.ATTR_TRACE_ID, "");
    Map<String, Object> body = new LinkedHashMap<>();
    body.put("error", "rate_limited");
    body.put("reason", reason);
    body.put("retry_after_sec", RETRY_AFTER_SECONDS);
    body.put("trace_id", traceId);

    byte[] bytes;
    try {
    bytes = objectMapper.writeValueAsBytes(body);
    } catch (Exception e) {
    bytes = ("{\"error\":\"rate_limited\",\"reason\":\"" + reason + "\"}")
        .getBytes(StandardCharsets.UTF_8);
    }
    DataBuffer buffer = exchange.getResponse().bufferFactory().wrap(bytes);
    return exchange.getResponse().writeWith(Mono.just(buffer));
  }

  private void markAllowed(String rulePath) {
    meterRegistry.counter("gateway.ratelimiter.allowed", "rule", rulePath).increment();
  }

  private void markRejected(String scope, String rulePath) {
    meterRegistry.counter("gateway.ratelimiter.rejected", "scope", scope, "rule", rulePath).increment();
  }
}
