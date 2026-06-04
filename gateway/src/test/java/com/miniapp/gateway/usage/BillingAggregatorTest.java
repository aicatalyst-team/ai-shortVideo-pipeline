package com.miniapp.gateway.usage;

import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.jdbc.core.JdbcTemplate;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;

class BillingAggregatorTest {

  @Test
  void aggregateNow_callsJdbcUpdate() {
    JdbcTemplate jdbc = Mockito.mock(JdbcTemplate.class);
    Mockito.when(jdbc.update(anyString())).thenReturn(3);

    BillingAggregator aggregator = new BillingAggregator(jdbc);
    int affected = aggregator.aggregateNow();

    assertThat(affected).isEqualTo(3);
    Mockito.verify(jdbc).update(Mockito.contains("INSERT INTO billing_daily"));
    Mockito.verify(jdbc).update(Mockito.contains("CURRENT_DATE"));
  }

  @Test
  void aggregateYesterday_usesCurrentDateMinusOne() {
    JdbcTemplate jdbc = Mockito.mock(JdbcTemplate.class);
    Mockito.when(jdbc.update(anyString())).thenReturn(0);

    BillingAggregator aggregator = new BillingAggregator(jdbc);
    aggregator.aggregateYesterday();

    var captor = org.mockito.ArgumentCaptor.forClass(String.class);
    Mockito.verify(jdbc).update(captor.capture());
    assertThat(captor.getValue()).contains("CURRENT_DATE - INTERVAL '1 day'");
  }
}
