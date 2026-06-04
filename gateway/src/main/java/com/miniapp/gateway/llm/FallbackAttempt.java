package com.miniapp.gateway.llm;

import lombok.AllArgsConstructor;
import lombok.Data;

import java.util.LinkedHashMap;
import java.util.Map;

@Data
@AllArgsConstructor
public class FallbackAttempt {
  private String provider;
  private String model;
  private String status;
  private int httpStatus;
  private long latencyMs;
  private String errorBrief;

  public Map<String, Object> toMap() {
    Map<String, Object> data = new LinkedHashMap<>();
    data.put("provider", provider);
    data.put("model", model);
    data.put("status", status);
    if (httpStatus > 0) {
    data.put("http_status", httpStatus);
    }
    data.put("latency_ms", latencyMs);
    if (errorBrief != null && !errorBrief.isEmpty()) {
    data.put("error", errorBrief);
    }
    return data;
  }
}
