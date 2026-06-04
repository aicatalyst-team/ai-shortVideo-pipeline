package com.miniapp.gateway.sse;

import com.miniapp.gateway.trace.TraceIdFilter;
import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

import java.time.Duration;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

@RestController
@RequestMapping("/api/v1/jobs")
@Slf4j
public class JobStreamController {

  private static final Duration POLL_INTERVAL = Duration.ofMillis(500);
  private static final Duration HEARTBEAT_INTERVAL = Duration.ofSeconds(15);
  private static final Duration STREAM_LIFETIME = Duration.ofMinutes(5);

  private final JobReader jobReader;

  // 暴露当前活跃 SSE 连接数到 Prometheus
  // 生产监控必备：几千连接撑爆 Netty worker 时能定位
  // 指标名 gateway_sse_active_connections（Micrometer gauge）
  private final AtomicInteger activeConnections = new AtomicInteger(0);

  @Autowired(required = false)
  private MeterRegistry meterRegistry;

  public JobStreamController(JobReader jobReader) {
    this.jobReader = jobReader;
  }

  @PostConstruct
  void bindMicrometer() {
    if (meterRegistry != null) {
    Gauge.builder("gateway_sse_active_connections", activeConnections, AtomicInteger::get)
        .description("Currently open SSE streams to /api/v1/jobs/{id}/stream")
        .register(meterRegistry);
    log.info("[sse] active connections gauge bound to Prometheus");
    }
  }

  @GetMapping(value = "/{jobId}/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
  public Flux<ServerSentEvent<Map<String, Object>>> stream(
    @PathVariable String jobId,
    @RequestHeader(value = "Last-Event-ID", required = false) String lastEventId,
    ServerWebExchange exchange
  ) {
    int resumeProgress = parseLastEventId(lastEventId);
    boolean isResume = lastEventId != null && !lastEventId.isBlank();
    String traceId = exchange.getAttributeOrDefault(TraceIdFilter.ATTR_TRACE_ID, "");

    log.info("[sse] open job={} resume={} trace={}", jobId, resumeProgress, traceId);

    Flux<ServerSentEvent<Map<String, Object>>> initialFlux = Flux.defer(() -> {
    Map<String, Object> data = new HashMap<>();
    data.put("job_id", jobId);
    data.put("status", "stream_opened");
    data.put("resume_from", resumeProgress);
    data.put("trace_id", traceId);
    return Flux.just(ServerSentEvent.<Map<String, Object>>builder()
        .event("stream_opened")
        .id(jobId + ":" + resumeProgress)
        .data(data)
        .build());
    });

    Flux<ServerSentEvent<Map<String, Object>>> stateFlux = Flux.interval(POLL_INTERVAL)
      .flatMap(tick -> Mono.fromCallable(() -> jobReader.findById(jobId))
        .subscribeOn(Schedulers.boundedElastic()))
      .filter(optional -> optional.isPresent())
      .map(optional -> optional.get())
      .distinctUntilChanged(JobSnapshot::fingerprint)
      .filter(snapshot -> isResume
        ? snapshot.progress() > resumeProgress
        : snapshot.progress() >= resumeProgress)
      .map(snapshot -> ServerSentEvent.<Map<String, Object>>builder()
        .id(jobId + ":" + snapshot.progress())
        .event(snapshot.eventType())
        .data(snapshot.toMap(traceId))
        .build());

    Flux<ServerSentEvent<Map<String, Object>>> heartbeatFlux = Flux.interval(HEARTBEAT_INTERVAL)
      .map(tick -> ServerSentEvent.<Map<String, Object>>builder()
        .comment("heartbeat " + System.currentTimeMillis())
        .build());

    return Flux.concat(initialFlux, Flux.merge(stateFlux, heartbeatFlux))
      .takeUntil(event -> isTerminalEvent(event.event()))
      .take(STREAM_LIFETIME)
      // 连接计数器 ±1（Prometheus 监控)
      // Subscribe 时 +1，任何终止路径（cancel/error/complete）都 -1
      // doFinally 是统一兜底入口，覆盖客户端断开 / 服务端 timeout / takeUntil 终止
      .doOnSubscribe(subscription -> {
        int now = activeConnections.incrementAndGet();
        log.info("[sse] open job={} active={}", jobId, now);
      })
      .doOnCancel(() -> log.info("[sse] cancel (client disconnected) job={}", jobId))
      .doOnError(e -> log.warn("[sse] error job={}: {}", jobId, e.getMessage()))
      .doOnComplete(() -> log.info("[sse] complete job={}", jobId))
      .doFinally(signalType -> {
        int now = activeConnections.decrementAndGet();
        log.debug("[sse] released job={} signal={} active={}", jobId, signalType, now);
      });
  }

  /** 用于测试断言当前活跃连接数。 */
  public int currentActiveConnections() {
    return activeConnections.get();
  }

  private int parseLastEventId(String header) {
    if (header == null || header.isBlank()) {
    return 0;
    }
    int colon = header.lastIndexOf(':');
    if (colon < 0) {
    return 0;
    }
    try {
    return Integer.parseInt(header.substring(colon + 1));
    } catch (NumberFormatException e) {
    return 0;
    }
  }

  private boolean isTerminalEvent(String eventType) {
    return "completed".equals(eventType)
      || "failed".equals(eventType)
      || "cancelled".equals(eventType);
  }
}
