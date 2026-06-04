package com.miniapp.gateway.usage;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
@Slf4j
public class BillingAggregator {

  private final JdbcTemplate jdbc;

  @Scheduled(cron = "0 0 2 * * *", zone = "Asia/Shanghai")
  public void aggregateYesterday() {
    runAggregationFor("CURRENT_DATE - INTERVAL '1 day'");
  }

  public int aggregateNow() {
    return runAggregationFor("CURRENT_DATE");
  }

  int runAggregationFor(String dateExpr) {
    log.info("[billing-aggregator] start dt={}", dateExpr);
    String sql = """
      INSERT INTO billing_daily (
        tenant_id, dt,
        total_calls, total_input_tokens, total_output_tokens, total_cost_cny,
        success_calls, fallback_calls, failed_calls,
        by_provider, by_biz_type, aggregated_at
      )
      SELECT
        COALESCE(NULLIF(tenant_id, ''), 'anon') AS tenant_id,
        (created_at AT TIME ZONE 'Asia/Shanghai')::date AS dt,
        COUNT(*) AS total_calls,
        COALESCE(SUM(input_tokens), 0) AS total_input_tokens,
        COALESCE(SUM(output_tokens), 0) AS total_output_tokens,
        COALESCE(SUM(cost_cny), 0) AS total_cost_cny,
        COUNT(*) FILTER (WHERE status = 'success') AS success_calls,
        COUNT(*) FILTER (WHERE status = 'fallback') AS fallback_calls,
        COUNT(*) FILTER (WHERE status = 'failed') AS failed_calls,
        '{}'::jsonb AS by_provider,
        '{}'::jsonb AS by_biz_type,
        NOW()
      FROM llm_calls
      WHERE (created_at AT TIME ZONE 'Asia/Shanghai')::date = (%s)
      GROUP BY COALESCE(NULLIF(tenant_id, ''), 'anon'), (created_at AT TIME ZONE 'Asia/Shanghai')::date
      ON CONFLICT (tenant_id, dt) DO UPDATE SET
        total_calls = EXCLUDED.total_calls,
        total_input_tokens = EXCLUDED.total_input_tokens,
        total_output_tokens = EXCLUDED.total_output_tokens,
        total_cost_cny = EXCLUDED.total_cost_cny,
        success_calls = EXCLUDED.success_calls,
        fallback_calls = EXCLUDED.fallback_calls,
        failed_calls = EXCLUDED.failed_calls,
        by_provider = EXCLUDED.by_provider,
        by_biz_type = EXCLUDED.by_biz_type,
        aggregated_at = NOW()
      """.formatted(dateExpr);
    int affected = jdbc.update(sql);
    log.info("[billing-aggregator] done affected={}", affected);
    return affected;
  }
}
