package com.miniapp.gateway.frame;

import com.miniapp.gateway.auth.JwtService;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.client.MultipartBodyBuilder;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.reactive.server.WebTestClient;

import java.util.Map;

import static org.mockito.ArgumentMatchers.anyString;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@TestPropertySource(properties = {
    "gateway.auth.jwt-secret=test-secret-must-be-at-least-32-bytes-long-xxx",
    "gateway.upstream.python-base-url=http://localhost:9999",
    "gateway.storage.minio.endpoint=http://localhost:9999",
    "gateway.storage.minio.public-endpoint=http://localhost:9999"
})
class FrameControllerTest {

  @Autowired
  private WebTestClient client;

  @Autowired
  private JwtService jwtService;

  @MockBean
  private ImageUploadService uploadService;

  private String validToken() {
    return jwtService.issue("u1", "tenantA");
  }

  @Test
  void upload_returns200OnSuccess() throws Exception {
    Mockito.when(uploadService.uploadBytes(
        Mockito.any(byte[].class),
        anyString(),
        anyString(),
        anyString(),
        anyString()))
      .thenReturn(Map.of(
        "asset_id", "ASSET01",
        "url", "http://localhost:9999/ai-platform-public/x.png",
        "thumb_url", "http://localhost:9999/ai-platform-public/x_thumb.jpg",
        "sha256", "abc",
        "width", 1024,
        "height", 768,
        "size_bytes", 1234,
        "dedup", false
      ));

    client.post().uri("/api/v1/frames/upload")
      .header(HttpHeaders.AUTHORIZATION, "Bearer " + validToken())
      .contentType(MediaType.MULTIPART_FORM_DATA)
      .bodyValue(uploadBody("test.png", "fakepng".getBytes(), true))
      .exchange()
      .expectStatus().isOk()
      .expectBody()
      .jsonPath("$.asset_id").isEqualTo("ASSET01");
  }

  @Test
  void upload_rejects400WhenServiceThrows() throws Exception {
    Mockito.when(uploadService.uploadBytes(
        Mockito.any(byte[].class),
        anyString(),
        anyString(),
        anyString(),
        anyString()))
      .thenThrow(new IllegalArgumentException("file too large"));

    client.post().uri("/api/v1/frames/upload")
      .header(HttpHeaders.AUTHORIZATION, "Bearer " + validToken())
      .contentType(MediaType.MULTIPART_FORM_DATA)
      .bodyValue(uploadBody("test.png", "x".getBytes(), false))
      .exchange()
      .expectStatus().isBadRequest()
      .expectBody()
      .jsonPath("$.error").isEqualTo("upload_rejected");
  }

  @Test
  void upload_rejects401WithoutJwt() {
    client.post().uri("/api/v1/frames/upload")
      .contentType(MediaType.MULTIPART_FORM_DATA)
      .bodyValue(uploadBody("test.png", "x".getBytes(), false))
      .exchange()
      .expectStatus().isUnauthorized();
  }

  @Test
  void upload_extractsTenantIdFromJwt() throws Exception {
    Mockito.when(uploadService.uploadBytes(
        Mockito.any(byte[].class),
        anyString(),
        anyString(),
        anyString(),
        anyString()))
      .thenReturn(Map.of("asset_id", "X"));

    client.post().uri("/api/v1/frames/upload")
      .header(HttpHeaders.AUTHORIZATION, "Bearer " + validToken())
      .contentType(MediaType.MULTIPART_FORM_DATA)
      .bodyValue(uploadBody("tenant.png", "x".getBytes(), false))
      .exchange()
      .expectStatus().isOk();

    Mockito.verify(uploadService).uploadBytes(
      Mockito.any(byte[].class),
      anyString(),
      anyString(),
      Mockito.eq("tenantA"),
      anyString());
  }

  private org.springframework.util.MultiValueMap<String, org.springframework.http.HttpEntity<?>> uploadBody(
    String filename,
    byte[] content,
    boolean includeKind) {
    MultipartBodyBuilder builder = new MultipartBodyBuilder();
    builder.part("file", new ByteArrayResource(content) {
    @Override
    public String getFilename() {
      return filename;
    }
    }).contentType(MediaType.IMAGE_PNG);
    if (includeKind) {
    builder.part("kind", "upload");
    }
    return builder.build();
  }
}
