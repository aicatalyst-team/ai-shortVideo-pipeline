package com.miniapp.gateway.kling;

import com.miniapp.gateway.trace.TraceIdFilter;
import io.github.resilience4j.circuitbreaker.CallNotPermittedException;
import io.github.resilience4j.circuitbreaker.CircuitBreaker;
import io.github.resilience4j.circuitbreaker.CircuitBreakerRegistry;
import io.github.resilience4j.micrometer.tagged.TaggedCircuitBreakerMetrics;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.reactive.function.client.WebClientResponseException;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.util.LinkedHashMap;
import java.util.Map;

@RestController
@RequestMapping("/internal/kling")
@Slf4j
public class KlingController {

  private final KlingService klingService;
  private final CircuitBreakerRegistry breakerRegistry;
  private final MeterRegistry meterRegistry;

  public KlingController(
    KlingService klingService,
    CircuitBreakerRegistry breakerRegistry,
    ObjectProvider<MeterRegistry> meterRegistryProvider
  ) {
    this.klingService = klingService;
    this.breakerRegistry = breakerRegistry;
    this.meterRegistry = meterRegistryProvider.getIfAvailable();
  }

  @PostConstruct
  void bindMetrics() {
    if (meterRegistry != null) {
    TaggedCircuitBreakerMetrics.ofCircuitBreakerRegistry(breakerRegistry).bindTo(meterRegistry);
    log.info("[kling] CircuitBreaker metrics bound to Micrometer/Prometheus");
    }
    // 监听 state transition 事件
    // - state 转换打 ERROR/WARN 日志（运维告警接 ELK / Grafana）
    // - 用 Counter 暴露 gateway_kling_circuit_state_transition_total{from, to}
    // - Resilience4j 最佳实践（区别于被动 gauge：用主动事件监听）
    CircuitBreaker cb = breakerRegistry.circuitBreaker("kling-submit");
    cb.getEventPublisher()
      .onStateTransition(event -> {
        String from = event.getStateTransition().getFromState().name();
        String to = event.getStateTransition().getToState().name();
        // CLOSED → OPEN 是严重信号（可灵开始爆 5xx），ERROR 级触发告警
        // OPEN → HALF_OPEN 是恢复探测（运维关心但不紧急），WARN
        // HALF_OPEN → CLOSED 是完全恢复，INFO
        // HALF_OPEN → OPEN 是探测失败重新熔断，WARN
        if ("CLOSED".equals(from) && "OPEN".equals(to)) {
        log.error("[kling-circuit] ⚠️ TRANSITION {} -> {} ⚠️ "
            + "上游故障率超阈值，熔断 60s. metrics={}",
            from, to, klingService.currentMetrics());
        } else if ("OPEN".equals(from)) {
        log.warn("[kling-circuit] TRANSITION {} -> {} 开始探测/重新熔断", from, to);
        } else if ("HALF_OPEN".equals(from) && "CLOSED".equals(to)) {
        log.info("[kling-circuit] ✓ TRANSITION {} -> {} 上游已恢复", from, to);
        } else {
        log.info("[kling-circuit] TRANSITION {} -> {}", from, to);
        }
        if (meterRegistry != null) {
        Counter.builder("gateway_kling_circuit_state_transition_total")
            .tag("from", from)
            .tag("to", to)
            .description("Kling CircuitBreaker state transitions")
            .register(meterRegistry)
            .increment();
        }
      })
      .onCallNotPermitted(event -> {
        // 熔断中每次被拒都打一条 WARN，方便看"用户被拦了多少"
        if (meterRegistry != null) {
        Counter.builder("gateway_kling_circuit_rejected_total")
            .description("Calls rejected by Kling CircuitBreaker while OPEN")
            .register(meterRegistry)
            .increment();
        }
      });
    log.info("[kling] CircuitBreaker EventPublisher registered (state transition + rejection)");
  }

  @PostMapping("/submit/image2video")
  public Mono<ResponseEntity<Map<String, Object>>> submitImage2Video(
    @RequestBody Map<String, Object> body,
    ServerWebExchange exchange
  ) {
    String traceId = (String) exchange.getAttributes()
      .getOrDefault(TraceIdFilter.ATTR_TRACE_ID, "");

    return klingService.submitImage2Video(body)
      .map(resp -> {
        Map<String, Object> result = new LinkedHashMap<>(resp);
        result.put("trace_id", traceId);
        return ResponseEntity.ok(result);
      })
      .onErrorResume(CallNotPermittedException.class, e -> {
        Map<String, Object> err = new LinkedHashMap<>();
        err.put("error", "kling_circuit_open");
        err.put("message", "kling upstream is being protected; circuit is open");
        err.put("retry_after_sec", 60);
        err.put("fallback_action", "queue_or_retry_after_60s");
        err.put("circuit_metrics", klingService.currentMetrics());
        err.put("trace_id", traceId);
        log.warn("[kling] circuit open, reject submit; trace={}", traceId);
        return Mono.just(ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).body(err));
      })
      .onErrorResume(WebClientResponseException.class, e -> {
        Map<String, Object> err = new LinkedHashMap<>();
        err.put("error", "kling_upstream_error");
        err.put("status", e.getStatusCode().value());
        err.put("message", brief(e.getResponseBodyAsString()));
        err.put("trace_id", traceId);
        return Mono.just(ResponseEntity.status(e.getStatusCode()).body(err));
      })
      .onErrorResume(KlingNotConfiguredException.class, e -> {
        Map<String, Object> err = new LinkedHashMap<>();
        err.put("error", "kling_not_configured");
        err.put("message", e.getMessage());
        err.put("trace_id", traceId);
        return Mono.just(ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).body(err));
      })
      .onErrorResume(Throwable.class, e -> {
        Map<String, Object> err = new LinkedHashMap<>();
        err.put("error", "kling_internal_error");
        err.put("message", brief(e.getMessage()));
        err.put("trace_id", traceId);
        log.error("[kling] unexpected error: {}", e.getMessage(), e);
        return Mono.just(ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body(err));
      });
  }

  @GetMapping("/status/{taskId}")
  public Mono<ResponseEntity<Map<String, Object>>> status(@PathVariable String taskId) {
    return klingService.queryTaskStatus(taskId)
      .map(ResponseEntity::ok)
      .onErrorResume(KlingNotConfiguredException.class, e ->
        Mono.just(ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
            .body(Map.of("error", "kling_not_configured"))));
  }

  @GetMapping("/circuit")
  public ResponseEntity<Map<String, Object>> circuitStatus() {
    return ResponseEntity.ok(klingService.currentMetrics());
  }

  private String brief(String message) {
    if (message == null) {
    return "";
    }
    return message.length() > 300 ? message.substring(0, 300) : message;
  }
}
