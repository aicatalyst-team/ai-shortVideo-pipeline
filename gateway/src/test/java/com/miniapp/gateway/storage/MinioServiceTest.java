package com.miniapp.gateway.storage;

import io.minio.MinioClient;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;

import static org.assertj.core.api.Assertions.assertThat;

class MinioServiceTest {

  private MinioService service;

  @BeforeEach
  void setUp() {
    MinioClient client = Mockito.mock(MinioClient.class);
    StorageProperties props = new StorageProperties();
    props.setEndpoint("http://minio:9000");
    props.setPublicEndpoint("https://cdn.example.com");
    props.setPublicBucket("ai-platform-public");
    props.setPrivateBucket("ai-platform-private");
    service = new MinioService(client, props);
  }

  @Test
  void sha256_isStable() {
    String h1 = service.sha256("hello".getBytes());
    String h2 = service.sha256("hello".getBytes());

    assertThat(h1).isEqualTo(h2);
    assertThat(h1).hasSize(64);
  }

  @Test
  void buildObjectName_formatCorrect() {
    String name = service.buildObjectName("tenantA", "abc1234567890def", "png");

    assertThat(name).startsWith("tenantA/");
    assertThat(name).contains("/ab/");
    assertThat(name).endsWith(".png");
  }

  @Test
  void buildObjectName_anonWhenTenantBlank() {
    String name = service.buildObjectName(null, "abc1234567890def", "jpg");

    assertThat(name).startsWith("anon/");
  }

  @Test
  void buildObjectName_extFallback() {
    String name = service.buildObjectName("t1", "abc1234567890def", null);

    assertThat(name).endsWith(".bin");
  }

  @Test
  void buildPublicUrl_combinesEndpointAndPath() {
    String url = service.buildPublicUrl(
      "ai-platform-public",
      "tenant/2026/05/24/ab/abc.png");

    assertThat(url).isEqualTo(
      "https://cdn.example.com/ai-platform-public/tenant/2026/05/24/ab/abc.png");
  }
}
