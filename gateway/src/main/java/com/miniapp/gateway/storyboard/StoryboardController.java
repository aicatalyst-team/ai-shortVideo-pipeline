package com.miniapp.gateway.storyboard;

import com.miniapp.gateway.trace.TraceIdFilter;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.util.Map;

@RestController
@RequestMapping("/api/v1/storyboards")
@RequiredArgsConstructor
@Slf4j
public class StoryboardController {

  private final PythonClient pythonClient;

  @GetMapping("/{planId}")
  public Mono<ResponseEntity<Map<String, Object>>> getStoryboard(
    @PathVariable String planId,
    @RequestParam(value = "include_frames", defaultValue = "false") boolean includeFrames,
    ServerWebExchange exchange
  ) {
    String traceId = exchange.getAttribute(TraceIdFilter.ATTR_TRACE_ID);
    return pythonClient.getStoryboard(planId, includeFrames, traceId)
      .map(ResponseEntity::ok)
      .onErrorResume(PythonClient.UpstreamException.class, e -> {
        HttpStatus status = HttpStatus.resolve(e.getStatusCode());
        if (status == null) {
        status = HttpStatus.BAD_GATEWAY;
        }
        log.warn("upstream returned {}: {}", e.getStatusCode(), e.getMessage());
        return Mono.just(ResponseEntity.status(status).body(
          Map.of("error", "upstream_error", "status", e.getStatusCode())));
      })
      .onErrorResume(Exception.class, e -> {
        log.error("storyboard forward failed", e);
        return Mono.just(ResponseEntity.status(HttpStatus.BAD_GATEWAY).body(
          Map.of("error", "gateway_error", "message", e.getMessage())));
      });
  }
}
