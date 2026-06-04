package com.miniapp.gateway.config;

import com.miniapp.gateway.trace.TraceIdFilter;
import io.netty.channel.ChannelOption;
import lombok.extern.slf4j.Slf4j;
import org.slf4j.MDC;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;
import org.springframework.web.reactive.function.client.ClientRequest;
import org.springframework.web.reactive.function.client.ExchangeFilterFunction;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientResponseException;
import reactor.core.publisher.Mono;
import reactor.netty.http.client.HttpClient;
import reactor.util.retry.Retry;

import java.time.Duration;

/**
 * WebClient 用于转发请求到 Python orchestrator。
 *
 * :
 * - connect timeout 5s（防连不上 hang 死）
 * - response timeout 默认 30s（application.yml 可调）
 * - 5xx 自动重试 2 次（指数退避 100ms → 200ms + 50ms jitter）
 * - TraceId 透传（X-Trace-Id 从 MDC 注入到下游 Python 调用）
 *
 * 这是  Resilience4j 熔断/重试包装的"前置基础"。
 * 当前用 Reactor 原生 retryWhen，迁移到 Resilience4j 时只换 filter。
 */
@Configuration
@Slf4j
public class WebClientConfig {

  @Value("${gateway.upstream.python-base-url}")
  private String pythonBaseUrl;

  @Value("${gateway.upstream.timeout-seconds:30}")
  private long timeoutSeconds;

  @Value("${gateway.upstream.connect-timeout-ms:5000}")
  private int connectTimeoutMs;

  @Value("${gateway.upstream.retry-max-attempts:2}")
  private long retryMaxAttempts;

  @Value("${gateway.upstream.retry-initial-backoff-ms:100}")
  private long retryInitialBackoffMs;

  @Bean(name = "pythonWebClient")
  public WebClient pythonWebClient() {
    HttpClient httpClient = HttpClient.create()
      .responseTimeout(Duration.ofSeconds(timeoutSeconds))
      .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, connectTimeoutMs);

    log.info("[python-webclient] base={} timeout={}s connect={}ms retries={}",
      pythonBaseUrl, timeoutSeconds, connectTimeoutMs, retryMaxAttempts);

    return WebClient.builder()
      .baseUrl(pythonBaseUrl)
      .clientConnector(new ReactorClientHttpConnector(httpClient))
      .filter(traceIdPropagator())
      .filter(retryOn5xx())
      .build();
  }

  /** 把当前请求的 X-Trace-Id 从 MDC 透传到下游 Python。 */
  private ExchangeFilterFunction traceIdPropagator() {
    return ExchangeFilterFunction.ofRequestProcessor(request -> {
    String traceId = MDC.get(TraceIdFilter.ATTR_TRACE_ID);
    if (traceId == null || traceId.isBlank()) {
      return Mono.just(request);
    }
    ClientRequest withTrace = ClientRequest.from(request)
        .header(TraceIdFilter.HEADER_TRACE_ID, traceId)
        .build();
    return Mono.just(withTrace);
    });
  }

  /**
   * 5xx 自动重试。
   * - 重试次数：retryMaxAttempts
   * - 退避：指数 + jitter，初始 retryInitialBackoffMs
   * - 4xx 不重试（业务错误重试无意义）
   * - 重试耗尽后抛 RetryExhaustedException
   */
  private ExchangeFilterFunction retryOn5xx() {
    return (request, next) -> next.exchange(request)
      .flatMap(response -> {
        HttpStatusCode status = response.statusCode();
        if (status.is5xxServerError()) {
        // 抛异常触发 retryWhen，外层重试。先 release body 避免泄漏
        return response.releaseBody()
            .then(Mono.error(new WebClientResponseException(
              "upstream " + status.value(),
              status.value(),
              status.toString(),
              response.headers().asHttpHeaders(),
              new byte[0],
              null)));
        }
        return Mono.just(response);
      })
      .retryWhen(
        Retry.backoff(retryMaxAttempts, Duration.ofMillis(retryInitialBackoffMs))
            .jitter(0.5)
            .filter(ex -> ex instanceof WebClientResponseException wre
              && wre.getStatusCode().is5xxServerError())
            .doBeforeRetry(sig -> log.warn(
              "[python-webclient] retry #{} after 5xx: {}",
              sig.totalRetries() + 1, sig.failure().getMessage()))
      );
  }
}
