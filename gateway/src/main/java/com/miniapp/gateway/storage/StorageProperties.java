package com.miniapp.gateway.storage;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

@Component
@ConfigurationProperties(prefix = "gateway.storage.minio")
@Data
public class StorageProperties {
  private String endpoint;
  private String publicEndpoint;
  private String accessKey;
  private String secretKey;
  private String publicBucket;
  private String privateBucket;
  private long uploadMaxBytes = 10 * 1024 * 1024L;
  private int thumbnailMaxSide = 512;
}
