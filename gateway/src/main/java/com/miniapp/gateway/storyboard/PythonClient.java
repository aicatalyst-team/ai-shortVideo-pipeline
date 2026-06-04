package com.miniapp.gateway.storyboard;

import lombok.extern.slf4j.Slf4j;
import com.miniapp.gateway.trace.TraceIdFilter;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpStatusCode;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.util.Map;

@Component
@Slf4j
public class PythonClient {

  private final WebClient webClient;

  public PythonClient(@Qualifier("pythonWebClient") WebClient webClient) {
    this.webClient = webClient;
  }

  public Mono<Map<String, Object>> getStoryboard(String planId, boolean includeFrames) {
    return getStoryboard(planId, includeFrames, null);
  }

  public Mono<Map<String, Object>> getStoryboard(String planId, boolean includeFrames, String traceId) {
    log.debug("forwarding GET /api/v1/storyboards/{} include_frames={}", planId, includeFrames);

    return webClient.get()
      .uri(uri -> uri.path("/api/v1/storyboards/{id}")
        .queryParam("include_frames", includeFrames)
        .build(planId))
      .headers(headers -> {
        if (traceId != null && !traceId.isBlank()) {
        headers.set(TraceIdFilter.HEADER_TRACE_ID, traceId);
        }
      })
      .retrieve()
      .onStatus(HttpStatusCode::is4xxClientError, resp ->
        resp.bodyToMono(String.class)
            .flatMap(body -> Mono.error(new UpstreamException(
              resp.statusCode().value(), body))))
      .onStatus(HttpStatusCode::is5xxServerError, resp ->
        resp.bodyToMono(String.class)
            .flatMap(body -> Mono.error(new UpstreamException(
              resp.statusCode().value(), body))))
      .bodyToMono(new ParameterizedTypeReference<Map<String, Object>>() {});
  }

  public static class UpstreamException extends RuntimeException {
    private final int statusCode;

    public UpstreamException(int statusCode, String body) {
    super("upstream " + statusCode + ": " + body);
    this.statusCode = statusCode;
    }

    public int getStatusCode() {
    return statusCode;
    }
  }
}
