package com.miniapp.gateway.usage;

import com.miniapp.gateway.auth.JwtService;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.reactive.server.WebTestClient;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@TestPropertySource(properties = {
    "gateway.auth.jwt-secret=test-secret-must-be-at-least-32-bytes-long!"
})
class UsageControllerTest {

  @Autowired
  WebTestClient client;

  @Autowired
  JwtService jwtService;

  @MockBean
  JdbcTemplate jdbc;

  @MockBean
  BillingAggregator aggregator;

  @Test
  void today_returnsRealtimeStats() {
    Mockito.when(jdbc.queryForMap(anyString(), any())).thenReturn(Map.of(
      "total_calls", 5L,
      "total_input_tokens", 100L,
      "total_output_tokens", 200L,
      "total_cost_cny", new BigDecimal("0.0050"),
      "success_calls", 4L,
      "fallback_calls", 1L,
      "failed_calls", 0L
    ));

    client.get().uri("/api/v1/usage/today?tenant_id=tA")
      .header("Authorization", "Bearer " + token())
      .exchange()
      .expectStatus().isOk()
      .expectBody()
      .jsonPath("$.total_calls").isEqualTo(5)
      .jsonPath("$.tenant_id").isEqualTo("tA")
      .jsonPath("$.source").isEqualTo("realtime_pg");
  }

  @Test
  void billing_returnsDailyRows() {
    Mockito.when(jdbc.queryForList(anyString(), anyString(), any())).thenReturn(List.of(
      Map.of(
        "dt", "2026-05-27",
        "total_calls", 10,
        "total_cost_cny", new BigDecimal("0.05"),
        "total_input_tokens", 100,
        "total_output_tokens", 200,
        "success_calls", 9,
        "fallback_calls", 1,
        "failed_calls", 0
      ),
      Map.of(
        "dt", "2026-05-26",
        "total_calls", 5,
        "total_cost_cny", new BigDecimal("0.02"),
        "total_input_tokens", 50,
        "total_output_tokens", 100,
        "success_calls", 5,
        "fallback_calls", 0,
        "failed_calls", 0
      )
    ));

    client.get().uri("/api/v1/usage/billing/tA?days=30")
      .header("Authorization", "Bearer " + token())
      .exchange()
      .expectStatus().isOk()
      .expectBody()
      .jsonPath("$.tenant_id").isEqualTo("tA")
      .jsonPath("$.daily.length()").isEqualTo(2)
      .jsonPath("$.summary.total_calls").isEqualTo(15);
  }

  @Test
  void aggregate_triggersManually() {
    Mockito.when(aggregator.aggregateNow()).thenReturn(7);

    client.post().uri("/api/v1/usage/aggregate")
      .header("Authorization", "Bearer " + token())
      .exchange()
      .expectStatus().isOk()
      .expectBody()
      .jsonPath("$.aggregated_rows").isEqualTo(7);
  }

  private String token() {
    return jwtService.issue("u1", "tA");
  }
}
