package com.miniapp.gateway.ratelimit;

import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import io.github.resilience4j.micrometer.tagged.TaggedRateLimiterMetrics;
import io.github.resilience4j.ratelimiter.RateLimiter;
import io.github.resilience4j.ratelimiter.RateLimiterConfig;
import io.github.resilience4j.ratelimiter.RateLimiterRegistry;
import io.micrometer.core.instrument.MeterRegistry;
import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;
import org.springframework.util.AntPathMatcher;

import java.time.Duration;
import java.util.Optional;

@Component
@Slf4j
public class RateLimitRegistry {

  private final RateLimitProperties props;
  private final RateLimiterRegistry resilienceRegistry = RateLimiterRegistry.ofDefaults();
  private final AntPathMatcher pathMatcher = new AntPathMatcher();
  private final Cache<String, RateLimiter> userLimiters = Caffeine.newBuilder()
    .maximumSize(10_000)
    .expireAfterAccess(Duration.ofMinutes(30))
    .build();

  // 注入 MeterRegistry 暴露 Prometheus 指标
  // Resilience4j 2.2 + spring-boot-3 需要显式绑定 TaggedRateLimiterMetrics
  @Autowired(required = false)
  private MeterRegistry meterRegistry;

  public RateLimitRegistry(RateLimitProperties props) {
    this.props = props;
  }

  @PostConstruct
  void bindMicrometer() {
    if (meterRegistry != null) {
    TaggedRateLimiterMetrics.ofRateLimiterRegistry(resilienceRegistry).bindTo(meterRegistry);
    log.info("[ratelimit] Resilience4j metrics bound to Micrometer (Prometheus 暴露)");
    } else {
    log.warn("[ratelimit] MeterRegistry not present; Resilience4j metrics will NOT be exposed");
    }
  }

  public Optional<RateLimitProperties.Rule> matchRule(String requestPath) {
    for (RateLimitProperties.Rule rule : props.getRules()) {
    if (rule.getPath() != null && pathMatcher.match(rule.getPath(), requestPath)) {
      return Optional.of(rule);
    }
    }
    return Optional.ofNullable(props.getDefaultRule());
  }

  public boolean isWhitelisted(String requestPath) {
    for (String pattern : props.getWhitelist()) {
    if (pattern != null && pathMatcher.match(pattern, requestPath)) {
      return true;
    }
    }
    return false;
  }

  public RateLimiter getUserLimiter(String userKey, RateLimitProperties.Rule rule) {
    String cacheKey = userKey + "@" + rule.getPath();
    return userLimiters.get(cacheKey, key -> buildLimiter("user:" + key, rule.getUserPerMinute()));
  }

  public RateLimiter getGlobalLimiter(RateLimitProperties.Rule rule) {
    String name = "global:" + rule.getPath();
    return resilienceRegistry.rateLimiter(name, () -> r4jConfig(rule.getGlobalPerMinute()));
  }

  private RateLimiter buildLimiter(String name, int perMinute) {
    return resilienceRegistry.rateLimiter(name, () -> r4jConfig(perMinute));
  }

  private RateLimiterConfig r4jConfig(int perMinute) {
    return RateLimiterConfig.custom()
      .limitForPeriod(Math.max(1, perMinute))
      .limitRefreshPeriod(Duration.ofMinutes(1))
      .timeoutDuration(Duration.ZERO)
      .build();
  }
}
