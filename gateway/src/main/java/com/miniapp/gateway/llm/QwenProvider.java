package com.miniapp.gateway.llm;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component
public class QwenProvider extends AbstractOpenAiCompatibleProvider {

  public QwenProvider(
    @Value("${gateway.llm.qwen.base-url:https://dashscope.aliyuncs.com/compatible-mode/v1}") String baseUrl,
    @Value("${gateway.llm.qwen.api-key:}") String apiKey,
    @Value("${gateway.llm.qwen.default-model:qwen-plus}") String defaultModel,
    @Value("${gateway.llm.timeout-seconds:60}") long timeoutSeconds
  ) {
    super(baseUrl, apiKey, defaultModel, timeoutSeconds, 0.0008, 0.002);
  }

  @Override
  public String name() {
    return "qwen";
  }
}
