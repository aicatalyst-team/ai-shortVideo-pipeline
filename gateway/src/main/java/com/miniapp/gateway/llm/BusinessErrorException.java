package com.miniapp.gateway.llm;

import lombok.Getter;

import java.util.List;

@Getter
public class BusinessErrorException extends RuntimeException {
  private final LlmProviderException providerException;
  private final List<FallbackAttempt> chain;

  public BusinessErrorException(LlmProviderException cause, List<FallbackAttempt> chain) {
    super(cause.getMessage(), cause);
    this.providerException = cause;
    this.chain = chain;
  }
}
