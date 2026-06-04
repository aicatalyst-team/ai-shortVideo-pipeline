package com.miniapp.gateway.llm;

import lombok.AllArgsConstructor;
import lombok.Data;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Data
@AllArgsConstructor
public class RoutingResult {
  private LlmChatResponse response;
  private List<FallbackAttempt> chain;

  public Map<String, Object> toMap() {
    Map<String, Object> data = new LinkedHashMap<>();
    data.put("content", response.getContent());
    data.put("provider", response.getProviderName());
    data.put("model", response.getModelName());
    data.put("input_tokens", response.getInputTokens());
    data.put("output_tokens", response.getOutputTokens());
    data.put("cost_cny", response.getCostCny());
    data.put("latency_ms", response.getLatencyMs());
    data.put("fallback_chain", chain.stream().map(FallbackAttempt::toMap).toList());
    return data;
  }
}
