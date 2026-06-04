package com.miniapp.gateway.llm;

import lombok.Getter;

@Getter
public class LlmProviderException extends RuntimeException {
  private final String providerName;
  private final int httpStatus;
  private final String errorType;

  public LlmProviderException(String providerName, String errorType, int httpStatus, String message, Throwable cause) {
    super(message, cause);
    this.providerName = providerName;
    this.errorType = errorType;
    this.httpStatus = httpStatus;
  }
}
