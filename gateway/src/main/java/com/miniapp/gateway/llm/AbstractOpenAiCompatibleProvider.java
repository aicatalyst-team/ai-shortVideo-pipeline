package com.miniapp.gateway.llm;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.netty.channel.ChannelOption;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.MediaType;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientResponseException;
import reactor.core.publisher.Mono;
import reactor.netty.http.client.HttpClient;

import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.TimeoutException;

@Slf4j
abstract class AbstractOpenAiCompatibleProvider implements LlmProvider {

  private final WebClient client;
  private final String apiKey;
  private final String defaultModel;
  private final double inputPricePerThousand;
  private final double outputPricePerThousand;
  private final ObjectMapper mapper = new ObjectMapper();

  protected AbstractOpenAiCompatibleProvider(
    String baseUrl,
    String apiKey,
    String defaultModel,
    long timeoutSeconds,
    double inputPricePerThousand,
    double outputPricePerThousand
  ) {
    this.apiKey = apiKey;
    this.defaultModel = defaultModel;
    this.inputPricePerThousand = inputPricePerThousand;
    this.outputPricePerThousand = outputPricePerThousand;

    HttpClient http = HttpClient.create()
      .responseTimeout(Duration.ofSeconds(timeoutSeconds))
      .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, 10_000);

    this.client = WebClient.builder()
      .baseUrl(baseUrl)
      .clientConnector(new ReactorClientHttpConnector(http))
      .defaultHeader("Authorization", "Bearer " + apiKey)
      .defaultHeader("Content-Type", "application/json")
      .build();
  }

  @Override
  public String defaultModel() {
    return defaultModel;
  }

  @Override
  public Mono<LlmChatResponse> chat(LlmChatRequest request) {
    if (apiKey == null || apiKey.isBlank()) {
    return Mono.error(new LlmProviderException(name(), "config", 0,
        name() + " api key not configured", null));
    }

    long start = System.currentTimeMillis();
    return client.post()
      .uri("/chat/completions")
      .accept(MediaType.APPLICATION_JSON)
      .bodyValue(buildPayload(request))
      .retrieve()
      .bodyToMono(String.class)
      .map(raw -> parseResponse(raw, request, start))
      .onErrorMap(this::mapError);
  }

  private Map<String, Object> buildPayload(LlmChatRequest request) {
    Map<String, Object> body = new LinkedHashMap<>();
    body.put("model", modelName(request));
    body.put("messages", request.getMessages());
    if (request.getTemperature() != null) {
    body.put("temperature", request.getTemperature());
    }
    if (request.getMaxTokens() != null) {
    body.put("max_tokens", request.getMaxTokens());
    }
    body.put("stream", false);
    return body;
  }

  private LlmChatResponse parseResponse(String raw, LlmChatRequest request, long start) {
    try {
    JsonNode root = mapper.readTree(raw);
    JsonNode choices = root.path("choices");
    String content = choices.isArray() && !choices.isEmpty()
        ? choices.get(0).path("message").path("content").asText("")
        : "";
    int input = root.path("usage").path("prompt_tokens").asInt(0);
    int output = root.path("usage").path("completion_tokens").asInt(0);
    double cost = input * inputPricePerThousand / 1000.0 + output * outputPricePerThousand / 1000.0;
    return LlmChatResponse.builder()
        .content(content)
        .inputTokens(input)
        .outputTokens(output)
        .costCny(cost)
        .providerName(name())
        .modelName(modelName(request))
        .latencyMs(System.currentTimeMillis() - start)
        .build();
    } catch (Exception e) {
    throw new LlmProviderException(name(), "parse", 0,
        "parse " + name() + " response failed", e);
    }
  }

  private String modelName(LlmChatRequest request) {
    return request.getModel() != null && !request.getModel().isBlank()
      ? request.getModel()
      : defaultModel;
  }

  private Throwable mapError(Throwable error) {
    if (error instanceof LlmProviderException) {
    return error;
    }
    if (error instanceof WebClientResponseException responseError) {
    int status = responseError.getStatusCode().value();
    String type = status == 429 ? "429" : status >= 500 ? "5xx" : "4xx";
    return new LlmProviderException(name(), type, status,
        name() + " http " + status + ": " + brief(responseError.getResponseBodyAsString()), error);
    }
    if (error instanceof TimeoutException || error.getCause() instanceof TimeoutException) {
    return new LlmProviderException(name(), "timeout", 0, name() + " timeout", error);
    }
    return new LlmProviderException(name(), "network", 0,
      name() + " network error: " + brief(error.getMessage()), error);
  }

  protected String brief(String value) {
    if (value == null) {
    return "";
    }
    return value.length() > 200 ? value.substring(0, 200) : value;
  }
}
