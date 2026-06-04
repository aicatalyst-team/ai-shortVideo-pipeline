package com.miniapp.gateway.auth;

import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.slf4j.MDC;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.util.AntPathMatcher;
import org.springframework.web.server.ServerWebExchange;
import org.springframework.web.server.WebFilter;
import org.springframework.web.server.WebFilterChain;
import reactor.core.publisher.Mono;

import java.util.List;
import java.util.Map;
import java.util.Set;

@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 10)
@RequiredArgsConstructor
@Slf4j
public class JwtAuthFilter implements WebFilter {

  public static final String ATTR_USER_ID = "gateway.userId";
  public static final String ATTR_TENANT_ID = "gateway.tenantId";
  private static final AntPathMatcher SSE_PATH_MATCHER = new AntPathMatcher();
  private static final List<String> SSE_QUERY_TOKEN_PATHS = List.of("/api/v1/jobs/*/stream");
  private static final Set<String> BUILTIN_PUBLIC_PATHS = Set.of(
    "/actuator/health",
    "/actuator/info",
    "/actuator/prometheus", // 监控端点（生产应走内部网络）
    "/health",
    "/internal/"      // Python orchestrator -> Java gateway internal calls
  );

  private final JwtService jwtService;
  private final ObjectMapper objectMapper = new ObjectMapper();

  @Value("${gateway.auth.public-paths:}")
  private List<String> publicPaths;

  @Override
  public Mono<Void> filter(ServerWebExchange exchange, WebFilterChain chain) {
    String path = exchange.getRequest().getPath().value();

    if (isPublicPath(path)) {
    return chain.filter(exchange);
    }

    String authHeader = exchange.getRequest().getHeaders().getFirst(HttpHeaders.AUTHORIZATION);
    String token = parseBearerToken(authHeader);

    if ((token == null || token.isEmpty()) && isSseQueryTokenAllowed(path)) {
    token = exchange.getRequest().getQueryParams().getFirst("token");
    if (token != null && !token.isEmpty()) {
      log.debug("[auth] token via query for SSE path={}", path);
    }
    }

    if (token == null || token.isEmpty()) {
    return writeUnauthorized(exchange, "missing or malformed Authorization header");
    }

    JwtService.AuthPrincipal principal = jwtService.verifyAndExtract(token);
    if (principal == null) {
    return writeUnauthorized(exchange, "invalid or expired token");
    }

    exchange.getAttributes().put(ATTR_USER_ID, principal.userId());
    exchange.getAttributes().put(ATTR_TENANT_ID, principal.tenantId());
    MDC.put("tenantId", principal.tenantId());

    return chain.filter(exchange).doFinally(signal -> MDC.remove("tenantId"));
  }

  private boolean isPublicPath(String path) {
    return BUILTIN_PUBLIC_PATHS.stream().anyMatch(pattern -> path.startsWith(pattern))
      || publicPaths != null
      && publicPaths.stream()
      .filter(p -> p != null && !p.isBlank())
      .anyMatch(pattern -> path.startsWith(pattern) || SSE_PATH_MATCHER.match(pattern, path));
  }

  private String parseBearerToken(String authHeader) {
    if (authHeader == null || !authHeader.startsWith("Bearer ")) {
    return null;
    }
    return authHeader.substring("Bearer ".length()).trim();
  }

  private boolean isSseQueryTokenAllowed(String path) {
    return SSE_QUERY_TOKEN_PATHS.stream().anyMatch(pattern -> SSE_PATH_MATCHER.match(pattern, path));
  }

  private Mono<Void> writeUnauthorized(ServerWebExchange exchange, String reason) {
    exchange.getResponse().setStatusCode(HttpStatus.UNAUTHORIZED);
    exchange.getResponse().getHeaders().setContentType(MediaType.APPLICATION_JSON);
    Map<String, Object> body = Map.of(
      "error", "unauthorized",
      "message", reason,
      "trace_id", (String) exchange.getAttributes().getOrDefault("traceId", "")
    );
    try {
    byte[] bytes = objectMapper.writeValueAsBytes(body);
    DataBuffer buf = exchange.getResponse().bufferFactory().wrap(bytes);
    return exchange.getResponse().writeWith(Mono.just(buf));
    } catch (Exception e) {
    log.error("write 401 body failed", e);
    return exchange.getResponse().setComplete();
    }
  }
}
