package com.miniapp.gateway.llm;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component
public class GlmProvider extends AbstractOpenAiCompatibleProvider {

  public GlmProvider(
    @Value("${gateway.llm.glm.base-url:https://open.bigmodel.cn/api/paas/v4}") String baseUrl,
    @Value("${gateway.llm.glm.api-key:}") String apiKey,
    @Value("${gateway.llm.glm.default-model:glm-4-plus}") String defaultModel,
    @Value("${gateway.llm.timeout-seconds:60}") long timeoutSeconds
  ) {
    super(baseUrl, apiKey, defaultModel, timeoutSeconds, 0.05, 0.05);
  }

  @Override
  public String name() {
    return "glm";
  }
}
