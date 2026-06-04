package com.miniapp.gateway.llm;

import lombok.Getter;

import java.util.List;

@Getter
public class AllProvidersFailedException extends RuntimeException {
  private final List<FallbackAttempt> chain;

  public AllProvidersFailedException(List<FallbackAttempt> chain) {
    super("all llm providers failed");
    this.chain = chain;
  }
}
