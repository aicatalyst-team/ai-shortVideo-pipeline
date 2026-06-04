package com.miniapp.gateway.ratelimit;

import io.github.resilience4j.ratelimiter.RateLimiter;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;

class RateLimitRegistryTest {

  private RateLimitProperties props;
  private RateLimitRegistry registry;

  @BeforeEach
  void setup() {
    props = new RateLimitProperties();
    props.setRules(List.of(
      new RateLimitProperties.Rule("/api/v1/clips/*/regenerate", 5, 30),
      new RateLimitProperties.Rule("/api/v1/frames/upload", 20, 100)
    ));
    props.setDefaultRule(new RateLimitProperties.Rule("**", 30, 200));
    props.setWhitelist(List.of("/actuator/**"));
    registry = new RateLimitRegistry(props);
  }

  @Test
  void matchRule_picksSpecificOverDefault() {
    Optional<RateLimitProperties.Rule> rule = registry.matchRule("/api/v1/clips/C1/regenerate");
    assertThat(rule).isPresent();
    assertThat(rule.get().getUserPerMinute()).isEqualTo(5);
  }

  @Test
  void matchRule_fallsBackToDefault() {
    Optional<RateLimitProperties.Rule> rule = registry.matchRule("/api/v1/unknown/path");
    assertThat(rule).isPresent();
    assertThat(rule.get().getUserPerMinute()).isEqualTo(30);
  }

  @Test
  void isWhitelisted_actuatorMatches() {
    assertThat(registry.isWhitelisted("/actuator/health")).isTrue();
    assertThat(registry.isWhitelisted("/actuator/metrics/jvm")).isTrue();
    assertThat(registry.isWhitelisted("/api/v1/clips/X/regenerate")).isFalse();
  }

  @Test
  void getUserLimiter_sameUserSameRule_returnsSameInstance() {
    RateLimitProperties.Rule rule = props.getRules().get(0);
    RateLimiter first = registry.getUserLimiter("tenantA:user1", rule);
    RateLimiter second = registry.getUserLimiter("tenantA:user1", rule);
    assertThat(first).isSameAs(second);
  }

  @Test
  void getUserLimiter_differentUsers_independentInstances() {
    RateLimitProperties.Rule rule = props.getRules().get(0);
    RateLimiter first = registry.getUserLimiter("tenantA:user1", rule);
    RateLimiter second = registry.getUserLimiter("tenantA:user2", rule);
    assertThat(first).isNotSameAs(second);
  }

  @Test
  void getGlobalLimiter_samePath_returnsSameInstance() {
    RateLimitProperties.Rule rule = props.getRules().get(0);
    RateLimiter first = registry.getGlobalLimiter(rule);
    RateLimiter second = registry.getGlobalLimiter(rule);
    assertThat(first).isSameAs(second);
  }
}
