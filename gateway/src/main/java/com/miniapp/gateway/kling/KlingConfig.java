package com.miniapp.gateway.kling;

import io.netty.channel.ChannelOption;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.netty.http.client.HttpClient;

import java.time.Duration;

@Configuration
public class KlingConfig {

  @Bean(name = "klingWebClient")
  public WebClient klingWebClient(KlingProperties props) {
    HttpClient httpClient = HttpClient.create()
      .responseTimeout(Duration.ofSeconds(props.getTimeoutSeconds()))
      .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, props.getConnectTimeoutMs());

    return WebClient.builder()
      .baseUrl(props.getBaseUrl())
      .clientConnector(new ReactorClientHttpConnector(httpClient))
      .defaultHeader("Content-Type", "application/json")
      .build();
  }
}
