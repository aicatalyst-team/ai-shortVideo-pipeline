package com.miniapp.gateway.llm;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component
public class DeepSeekProvider extends AbstractOpenAiCompatibleProvider {

  public DeepSeekProvider(
    @Value("${gateway.llm.deepseek.base-url:https://api.deepseek.com/v1}") String baseUrl,
    @Value("${gateway.llm.deepseek.api-key:}") String apiKey,
    @Value("${gateway.llm.deepseek.default-model:deepseek-chat}") String defaultModel,
    @Value("${gateway.llm.timeout-seconds:60}") long timeoutSeconds
  ) {
    super(baseUrl, apiKey, defaultModel, timeoutSeconds, 0.001, 0.002);
  }

  @Override
  public String name() {
    return "deepseek";
  }
}
