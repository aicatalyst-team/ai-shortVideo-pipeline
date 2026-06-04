package com.miniapp.gateway.llm;

import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class LlmChatResponse {
  private String content;
  private int inputTokens;
  private int outputTokens;
  private double costCny;
  private String providerName;
  private String modelName;
  private long latencyMs;
}
