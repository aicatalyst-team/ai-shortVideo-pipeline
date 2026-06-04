package com.miniapp.gateway.llm;

import com.miniapp.gateway.trace.TraceIdFilter;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.util.LinkedHashMap;
import java.util.Map;

@RestController
@RequestMapping("/internal/llm")
@RequiredArgsConstructor
@Slf4j
public class LlmController {

  private final LlmRouter router;

  @PostMapping("/chat")
  public Mono<ResponseEntity<Map<String, Object>>> chat(
    @RequestBody LlmChatRequest req,
    ServerWebExchange exchange
  ) {
    String traceId = (String) exchange.getAttributes()
      .getOrDefault(TraceIdFilter.ATTR_TRACE_ID, "");
    log.info("[llm-controller] biz={} tenant={} trace={} messages={}",
      req.getBizType(), req.getTenantId(), traceId,
      req.getMessages() == null ? 0 : req.getMessages().size());

    return router.route(req)
      .map(result -> {
        Map<String, Object> body = result.toMap();
        body.put("trace_id", traceId);
        return ResponseEntity.ok(body);
      })
      .onErrorResume(BusinessErrorException.class, e -> {
        LlmProviderException providerError = e.getProviderException();
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("error", "llm_business_error");
        body.put("message", e.getMessage());
        body.put("provider", providerError.getProviderName());
        body.put("http_status", providerError.getHttpStatus());
        body.put("fallback_chain", e.getChain().stream().map(FallbackAttempt::toMap).toList());
        body.put("trace_id", traceId);
        return Mono.just(ResponseEntity.status(HttpStatus.BAD_REQUEST).body(body));
      })
      .onErrorResume(AllProvidersFailedException.class, e -> {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("error", "all_providers_failed");
        body.put("message", "all LLM providers exhausted");
        body.put("fallback_chain", e.getChain().stream().map(FallbackAttempt::toMap).toList());
        body.put("trace_id", traceId);
        log.error("[llm-controller] all providers exhausted chain={}", e.getChain());
        return Mono.just(ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).body(body));
      });
  }
}
