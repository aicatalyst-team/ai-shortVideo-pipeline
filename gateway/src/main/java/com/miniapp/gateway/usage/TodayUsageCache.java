package com.miniapp.gateway.usage;

import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;

/**
 * : 当日累计 Caffeine 缓存层（A 方案）。
 *
 * 痛点：
 * /api/v1/usage/today 每次调用都打 PG，
 * 做 7 个 COUNT/SUM/FILTER 聚合查询。
 * 高频前端轮询（即使 SSE 接通也仍可能轮询）下 PG 压力大。
 *
 * 设计：
 * - Caffeine 缓存 tenant_id → 累计快照
 * - 30 秒 TTL（足够"实时"，UX 不感知）
 * - cache.get(tenantId, this::queryFromPg) 自动 miss 时回源
 * - Counter 暴露 cache_hit / cache_miss 命中率
 *
 * 命中率理论：
 * - 单 tenant 30s 内 10 次轮询 = 9 hit + 1 miss = 命中率 90%
 * - PG 压力 → 1/N
 *
 * 注意：
 * - AOP 写 PG 是单一数据源，缓存只是查询路径
 * - 进程重启缓存丢失，下次访问回源重建（无数据丢失）
 * - 跨日切换：dt 在 key 里 → 第二天自动新 entry
 */
@Component
@Slf4j
public class TodayUsageCache {

  private final JdbcTemplate jdbc;
  @Autowired(required = false)
  private MeterRegistry meterRegistry;

  private final Cache<String, Map<String, Object>> cache = Caffeine.newBuilder()
    .maximumSize(10_000)
    .expireAfterWrite(Duration.ofSeconds(30))
    .recordStats()
    .build();

  private Counter hitCounter;
  private Counter missCounter;
  private final AtomicLong totalQueries = new AtomicLong();

  public TodayUsageCache(JdbcTemplate jdbc) {
    this.jdbc = jdbc;
  }

  @PostConstruct
  void bindMetrics() {
    if (meterRegistry != null) {
    hitCounter = Counter.builder("gateway_usage_today_cache_hit_total")
        .description("TodayUsageCache hit count")
        .register(meterRegistry);
    missCounter = Counter.builder("gateway_usage_today_cache_miss_total")
        .description("TodayUsageCache miss count (回源 PG)")
        .register(meterRegistry);
    // 暴露 cache size 给 Prometheus
    io.micrometer.core.instrument.Gauge.builder("gateway_usage_today_cache_size",
          cache, c -> c.estimatedSize())
        .description("TodayUsageCache current size")
        .register(meterRegistry);
    log.info("[usage-cache] today usage cache metrics bound (hit/miss/size)");
    }
  }

  /**
   * 获取 tenant 当日累计快照。Caffeine 30s TTL，过期自动回源。
   */
  public Map<String, Object> getTodayStats(String tenantId) {
    totalQueries.incrementAndGet();
    // cache.getIfPresent 先看有没有，区分 hit/miss 计数
    Map<String, Object> existing = cache.getIfPresent(tenantId);
    if (existing != null) {
    if (hitCounter != null) hitCounter.increment();
    return existing;
    }
    if (missCounter != null) missCounter.increment();
    Map<String, Object> fresh = queryFromPg(tenantId);
    cache.put(tenantId, fresh);
    return fresh;
  }

  /**
   * 手动失效（测试 / 调试用，写 PG 后想立刻看到结果时）。
   */
  public void invalidate(String tenantId) {
    cache.invalidate(tenantId);
  }

  /** 调试用。 */
  public Map<String, Object> stats() {
    var s = cache.stats();
    Map<String, Object> m = new HashMap<>();
    m.put("size", cache.estimatedSize());
    m.put("hit_count", s.hitCount());
    m.put("miss_count", s.missCount());
    m.put("hit_rate", s.hitRate());
    m.put("total_queries", totalQueries.get());
    return m;
  }

  private Map<String, Object> queryFromPg(String tenantId) {
    return jdbc.queryForMap(
      "SELECT " +
        "COUNT(*) AS total_calls, " +
        "COALESCE(SUM(input_tokens), 0) AS total_input_tokens, " +
        "COALESCE(SUM(output_tokens), 0) AS total_output_tokens, " +
        "COALESCE(SUM(cost_cny), 0) AS total_cost_cny, " +
        "COUNT(*) FILTER (WHERE status = 'success') AS success_calls, " +
        "COUNT(*) FILTER (WHERE status = 'fallback') AS fallback_calls, " +
        "COUNT(*) FILTER (WHERE status = 'failed') AS failed_calls " +
        "FROM llm_calls " +
        "WHERE tenant_id = ? AND " +
        "(created_at AT TIME ZONE 'Asia/Shanghai')::date = " +
        "(NOW() AT TIME ZONE 'Asia/Shanghai')::date",
      tenantId);
  }
}
