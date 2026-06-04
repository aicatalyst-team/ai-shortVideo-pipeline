package com.miniapp.gateway.llm;

import reactor.core.publisher.Mono;

public interface LlmProvider {
  String name();

  String defaultModel();

  Mono<LlmChatResponse> chat(LlmChatRequest request);
}
