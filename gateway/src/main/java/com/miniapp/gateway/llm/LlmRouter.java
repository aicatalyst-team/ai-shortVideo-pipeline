package com.miniapp.gateway.llm;

import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import com.miniapp.gateway.usage.MeasureLlmCall;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import reactor.core.publisher.Mono;

import java.time.Duration;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;

@Component
@Slf4j
public class LlmRouter {

  private final List<LlmProvider> allProviders;
  private final MeterRegistry meterRegistry;

  @Value("${gateway.llm.provider-order:deepseek,qwen,glm}")
  private List<String> providerOrder;

  @Value("${gateway.llm.blacklist.consecutive-failures-threshold:3}")
  private int failThreshold;

  @Value("${gateway.llm.blacklist.ttl-seconds:300}")
  private long blacklistTtlSec;

  private final ConcurrentHashMap<String, AtomicInteger> failCounters = new ConcurrentHashMap<>();
  private Cache<String, Long> blacklist;
  private Counter successCounter;
  private Counter failoverCounter;
  private Counter blacklistCounter;
  private Counter exhaustedCounter;

  @Autowired
  public LlmRouter(List<LlmProvider> allProviders, ObjectProvider<MeterRegistry> meterRegistryProvider) {
    this.allProviders = allProviders;
    this.meterRegistry = meterRegistryProvider.getIfAvailable();
  }

  public LlmRouter(List<LlmProvider> allProviders) {
    this.allProviders = allProviders;
    this.meterRegistry = null;
  }

  @PostConstruct
  void init() {
    blacklist = Caffeine.newBuilder()
      .expireAfterWrite(Duration.ofSeconds(blacklistTtlSec))
      .build();
    if (meterRegistry != null) {
    successCounter = meterRegistry.counter("gateway_llm_router_success_total");
    failoverCounter = meterRegistry.counter("gateway_llm_router_failover_total");
    blacklistCounter = meterRegistry.counter("gateway_llm_router_blacklist_total");
    exhaustedCounter = meterRegistry.counter("gateway_llm_router_exhausted_total");
    }
    log.info("[llm-router] init order={} threshold={} ttl={}s",
      providerOrder, failThreshold, blacklistTtlSec);
  }

  @MeasureLlmCall
  public Mono<RoutingResult> route(LlmChatRequest req) {
    List<FallbackAttempt> chain = Collections.synchronizedList(new ArrayList<>());
    return tryNext(orderedProviders().iterator(), req, chain);
  }

  private List<LlmProvider> orderedProviders() {
    Map<String, LlmProvider> byName = new LinkedHashMap<>();
    for (LlmProvider provider : allProviders) {
    byName.put(provider.name(), provider);
    }

    List<LlmProvider> ordered = new ArrayList<>();
    for (String name : providerOrder) {
    LlmProvider provider = byName.get(name);
    if (provider != null) {
      ordered.add(provider);
    }
    }
    return ordered;
  }

  private Mono<RoutingResult> tryNext(
    java.util.Iterator<LlmProvider> iterator,
    LlmChatRequest req,
    List<FallbackAttempt> chain
  ) {
    if (!iterator.hasNext()) {
    if (exhaustedCounter != null) {
      exhaustedCounter.increment();
    }
    return Mono.error(new AllProvidersFailedException(List.copyOf(chain)));
    }

    LlmProvider provider = iterator.next();
    String providerName = provider.name();
    if (blacklist.getIfPresent(providerName) != null) {
    log.info("[llm-router] skip blacklisted provider={}", providerName);
    chain.add(new FallbackAttempt(providerName, provider.defaultModel(), "blacklisted", 0, 0, ""));
    return tryNext(iterator, req, chain);
    }

    long start = System.currentTimeMillis();
    return provider.chat(req)
      .map(resp -> {
        failCounters.computeIfAbsent(providerName, key -> new AtomicInteger()).set(0);
        chain.add(new FallbackAttempt(
          providerName, resp.getModelName(), "success", 0, resp.getLatencyMs(), ""));
        if (successCounter != null) {
        successCounter.increment();
        }
        return new RoutingResult(resp, List.copyOf(chain));
      })
      .onErrorResume(error -> handleProviderError(iterator, req, chain, provider, error, start));
  }

  private Mono<RoutingResult> handleProviderError(
    java.util.Iterator<LlmProvider> iterator,
    LlmChatRequest req,
    List<FallbackAttempt> chain,
    LlmProvider provider,
    Throwable error,
    long start
  ) {
    String providerName = provider.name();
    long latencyMs = System.currentTimeMillis() - start;

    if (error instanceof LlmProviderException providerError) {
    chain.add(new FallbackAttempt(
        providerName,
        provider.defaultModel(),
        providerError.getErrorType(),
        providerError.getHttpStatus(),
        latencyMs,
        brief(providerError.getMessage())));
    if ("4xx".equals(providerError.getErrorType())) {
      return Mono.error(new BusinessErrorException(providerError, List.copyOf(chain)));
    }
    // 未配 key 不算"上游故障"，不计失败计数 + 不触发黑名单
    // 启动时三个 provider key 都没配也只是 chain 记 config，不会污染失败计数器
    // 配置错误是运维问题，不是 SLO 问题
    if ("config".equals(providerError.getErrorType())) {
      log.debug("[llm-router] skip not-configured provider={}", providerName);
      return tryNext(iterator, req, chain);
    }
    } else {
    chain.add(new FallbackAttempt(
        providerName,
        provider.defaultModel(),
        "exception",
        0,
        latencyMs,
        brief(error.getMessage())));
    }

    if (failoverCounter != null) {
    failoverCounter.increment();
    }
    int failures = failCounters
      .computeIfAbsent(providerName, key -> new AtomicInteger())
      .incrementAndGet();
    if (failures >= failThreshold) {
    blacklist.put(providerName, System.currentTimeMillis());
    if (blacklistCounter != null) {
      blacklistCounter.increment();
    }
    log.warn("[llm-router] blacklist provider={} failures={} ttl={}s",
        providerName, failures, blacklistTtlSec);
    }
    return tryNext(iterator, req, chain);
  }

  private String brief(String message) {
    if (message == null) {
    return "";
    }
    return message.length() > 200 ? message.substring(0, 200) : message;
  }

  public void resetBlacklist() {
    blacklist.invalidateAll();
    failCounters.clear();
  }

  public boolean isBlacklisted(String providerName) {
    return blacklist.getIfPresent(providerName) != null;
  }
}
