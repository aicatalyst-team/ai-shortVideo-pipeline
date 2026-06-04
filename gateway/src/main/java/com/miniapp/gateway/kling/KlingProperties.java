package com.miniapp.gateway.kling;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

@Component
@ConfigurationProperties(prefix = "gateway.kling")
@Data
public class KlingProperties {
  private String baseUrl = "https://api-beijing.klingai.com";
  private String accessKey = "";
  private String secretKey = "";
  private String defaultModel = "kling-v2-5-turbo";
  private String defaultMode = "std";
  private long timeoutSeconds = 30;
  private int connectTimeoutMs = 10_000;
}
