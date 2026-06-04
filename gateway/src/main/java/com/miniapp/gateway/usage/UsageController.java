package com.miniapp.gateway.usage;

import com.miniapp.gateway.trace.TraceIdFilter;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ServerWebExchange;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/v1/usage")
@RequiredArgsConstructor
@Slf4j
public class UsageController {

  private final JdbcTemplate jdbc;
  private final BillingAggregator aggregator;
  private final TodayUsageCache todayCache;

  @GetMapping("/today")
  public ResponseEntity<Map<String, Object>> today(
    @RequestParam(value = "tenant_id", required = false) String tenantId,
    @RequestParam(value = "no_cache", required = false, defaultValue = "false") boolean noCache,
    ServerWebExchange exchange
  ) {
    String tid = tenantId == null || tenantId.isBlank() ? "anon" : tenantId;
    // （A）: Caffeine 30s TTL 缓存
    // noCache=true 强制回源（调试用）
    if (noCache) {
    todayCache.invalidate(tid);
    }
    Map<String, Object> stats = todayCache.getTodayStats(tid);
    Map<String, Object> body = new LinkedHashMap<>(stats);
    body.put("tenant_id", tid);
    body.put("dt", LocalDate.now().toString());
    body.put("source", noCache ? "realtime_pg_no_cache" : "caffeine_30s");
    body.put("trace_id", exchange.getAttributes().getOrDefault(TraceIdFilter.ATTR_TRACE_ID, ""));
    return ResponseEntity.ok(body);
  }

  /** : 缓存调试 endpoint。 */
  @GetMapping("/today/cache-stats")
  public ResponseEntity<Map<String, Object>> cacheStats() {
    return ResponseEntity.ok(todayCache.stats());
  }

  @GetMapping("/billing/{tenantId}")
  public ResponseEntity<Map<String, Object>> billing(
    @PathVariable String tenantId,
    @RequestParam(defaultValue = "30") int days
  ) {
    int boundedDays = Math.max(1, Math.min(days, 365));
    List<Map<String, Object>> rows = jdbc.queryForList(
      "SELECT dt, total_calls, total_input_tokens, total_output_tokens, " +
        "total_cost_cny, success_calls, fallback_calls, failed_calls " +
        "FROM billing_daily " +
        "WHERE tenant_id = ? AND dt >= CURRENT_DATE - (? * INTERVAL '1 day') " +
        "ORDER BY dt DESC",
      tenantId,
      boundedDays);

    BigDecimal totalCost = BigDecimal.ZERO;
    long totalCalls = 0;
    for (Map<String, Object> row : rows) {
    Object cost = row.get("total_cost_cny");
    if (cost instanceof BigDecimal bd) {
      totalCost = totalCost.add(bd);
    } else if (cost instanceof Number n) {
      totalCost = totalCost.add(BigDecimal.valueOf(n.doubleValue()));
    }
    Object calls = row.get("total_calls");
    if (calls instanceof Number n) {
      totalCalls += n.longValue();
    }
    }

    Map<String, Object> body = new LinkedHashMap<>();
    body.put("tenant_id", tenantId);
    body.put("days", boundedDays);
    body.put("daily", rows);
    body.put("summary", Map.of(
      "total_calls", totalCalls,
      "total_cost_cny", totalCost
    ));
    return ResponseEntity.ok(body);
  }

  @PostMapping("/aggregate")
  public ResponseEntity<Map<String, Object>> aggregateNow() {
    return ResponseEntity.ok(Map.of("aggregated_rows", aggregator.aggregateNow()));
  }
}
