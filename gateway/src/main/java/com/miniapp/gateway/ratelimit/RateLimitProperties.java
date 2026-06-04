package com.miniapp.gateway.ratelimit;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;

@Component
@ConfigurationProperties(prefix = "gateway.ratelimit")
@Data
public class RateLimitProperties {

  private boolean enabled = true;
  private List<Rule> rules = new ArrayList<>();
  private Rule defaultRule = new Rule("**", 30, 200);
  private List<String> whitelist = List.of("/actuator/**", "/health");

  @Data
  public static class Rule {
    private String path;
    private int userPerMinute;
    private int globalPerMinute;

    public Rule() {
    }

    public Rule(String path, int userPerMinute, int globalPerMinute) {
    this.path = path;
    this.userPerMinute = userPerMinute;
    this.globalPerMinute = globalPerMinute;
    }
  }
}
