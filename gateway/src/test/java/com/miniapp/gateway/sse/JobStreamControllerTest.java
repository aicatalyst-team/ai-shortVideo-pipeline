package com.miniapp.gateway.sse;

import com.miniapp.gateway.auth.JwtService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.MediaType;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.test.annotation.DirtiesContext;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.reactive.server.WebTestClient;

import java.time.Duration;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@DirtiesContext(classMode = DirtiesContext.ClassMode.AFTER_EACH_TEST_METHOD)
@TestPropertySource(properties = {
    "gateway.auth.jwt-secret=test-secret-must-be-at-least-32-bytes-long!!",
    "gateway.upstream.python-base-url=http://localhost:9999",
    "management.health.db.enabled=false"
})
class JobStreamControllerTest {

  @Autowired
  private WebTestClient client;

  @Autowired
  private JwtService jwtService;

  @MockBean
  private JobReader jobReader;

  @BeforeEach
  void resetMocks() {
    Mockito.reset(jobReader);
  }

  private String token() {
    return jwtService.issue("u1", "tenantA");
  }

  private JobSnapshot snapshot(int progress, String status, String stage) {
    return new JobSnapshot("J1", "regenerate_clip", status, progress, stage,
      null, null, "CLIPTEST", System.currentTimeMillis() / 1000);
  }

  @Test
  void open_returnsTextEventStreamContentType() {
    Mockito.when(jobReader.findById(anyString()))
      .thenReturn(Optional.of(snapshot(100, "done", "done")));

    var result = client.get().uri("/api/v1/jobs/J1/stream")
      .header("Authorization", "Bearer " + token())
      .exchange()
      .expectStatus().isOk()
      .expectHeader().contentTypeCompatibleWith(MediaType.TEXT_EVENT_STREAM)
      .returnResult(new ParameterizedTypeReference<ServerSentEvent<String>>() {});

    result.getResponseBody()
      .take(Duration.ofSeconds(2))
      .collectList()
      .block();
  }

  @Test
  void streamsInitialProgressAndTerminal() {
    Mockito.when(jobReader.findById(anyString()))
      .thenReturn(
        Optional.of(snapshot(30, "running", "generating_video")),
        Optional.of(snapshot(30, "running", "generating_video")),
        Optional.of(snapshot(90, "running", "updating_db")),
        Optional.of(snapshot(100, "done", "done"))
      );

    List<ServerSentEvent<String>> events = client.get().uri("/api/v1/jobs/J1/stream")
      .header("Authorization", "Bearer " + token())
      .exchange()
      .expectStatus().isOk()
      .returnResult(new ParameterizedTypeReference<ServerSentEvent<String>>() {})
      .getResponseBody()
      .take(Duration.ofSeconds(5))
      .collectList()
      .block();

    assertThat(events).isNotNull();
    assertThat(events.stream().map(ServerSentEvent::event).toList())
      .contains("stream_opened", "progress", "completed");
  }

  @Test
  void resumesFromLastEventIdSkippingEarlierProgress() {
    Mockito.when(jobReader.findById(anyString()))
      .thenReturn(
        Optional.of(snapshot(30, "running", "generating_video")),
        Optional.of(snapshot(90, "running", "updating_db")),
        Optional.of(snapshot(100, "done", "done"))
      );

    List<ServerSentEvent<String>> events = client.get().uri("/api/v1/jobs/J1/stream")
      .header("Authorization", "Bearer " + token())
      .header("Last-Event-ID", "J1:50")
      .exchange()
      .expectStatus().isOk()
      .returnResult(new ParameterizedTypeReference<ServerSentEvent<String>>() {})
      .getResponseBody()
      .take(Duration.ofSeconds(5))
      .collectList()
      .block();

    assertThat(events).isNotNull();
    assertThat(events.stream()
      .filter(e -> "progress".equals(e.event()))
      .map(ServerSentEvent::id)
      .toList()).doesNotContain("J1:30");
  }

  @Test
  void requiresJwt() {
    client.get().uri("/api/v1/jobs/J1/stream")
      .exchange()
      .expectStatus().isUnauthorized();
  }

  @Test
  void streamAcceptsTokenInQueryParam() {
    Mockito.when(jobReader.findById(anyString()))
      .thenReturn(Optional.of(snapshot(100, "done", "done")));

    var result = client.get().uri("/api/v1/jobs/J1/stream?token=" + token())
      .exchange()
      .expectStatus().isOk()
      .expectHeader().contentTypeCompatibleWith(MediaType.TEXT_EVENT_STREAM)
      .returnResult(new ParameterizedTypeReference<ServerSentEvent<String>>() {});

    result.getResponseBody()
      .take(Duration.ofSeconds(2))
      .collectList()
      .block();
  }

  @Test
  void normalEndpointRejectsTokenInQueryParam() {
    client.get().uri("/api/v1/storyboards/X?token=" + token())
      .exchange()
      .expectStatus().isUnauthorized();
  }

  @Test
  void unknownJobStreamsInitialEventOnlyWithinShortWindow() {
    Mockito.when(jobReader.findById(anyString()))
      .thenReturn(Optional.empty());

    List<ServerSentEvent<String>> events = client.get().uri("/api/v1/jobs/UNKNOWN/stream")
      .header("Authorization", "Bearer " + token())
      .exchange()
      .expectStatus().isOk()
      .returnResult(new ParameterizedTypeReference<ServerSentEvent<String>>() {})
      .getResponseBody()
      .take(Duration.ofSeconds(2))
      .collectList()
      .block();

    assertThat(events).isNotNull();
    assertThat(events.stream().anyMatch(event -> "stream_opened".equals(event.event()))).isTrue();
  }

  @Test
  void terminalCompletesStream() {
    Mockito.when(jobReader.findById(anyString()))
      .thenReturn(Optional.of(snapshot(100, "done", "done")));

    List<ServerSentEvent<String>> events = client.get().uri("/api/v1/jobs/J1/stream")
      .header("Authorization", "Bearer " + token())
      .exchange()
      .expectStatus().isOk()
      .returnResult(new ParameterizedTypeReference<ServerSentEvent<String>>() {})
      .getResponseBody()
      .take(Duration.ofSeconds(3))
      .collectList()
      .block();

    assertThat(events).isNotNull();
    assertThat(events.stream().map(ServerSentEvent::event).toList()).contains("completed");
  }

  @Test
  void rateLimitSkipForSsePath() {
    Mockito.when(jobReader.findById(anyString()))
      .thenReturn(Optional.of(snapshot(100, "done", "done")));

    for (int i = 0; i < 10; i++) {
    var result = client.get().uri("/api/v1/jobs/J1/stream")
        .header("Authorization", "Bearer " + token())
        .exchange()
        .expectStatus().isOk()
        .returnResult(new ParameterizedTypeReference<ServerSentEvent<String>>() {});

    result.getResponseBody()
        .take(Duration.ofSeconds(2))
        .collectList()
        .block();
    }
  }
}
