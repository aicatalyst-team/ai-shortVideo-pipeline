package com.miniapp.gateway.llm;

import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.UUID;

@Component
@RequiredArgsConstructor
@Slf4j
public class LlmCallWriter {

  private final JdbcTemplate jdbc;
  private final ObjectMapper mapper = new ObjectMapper();

  public void recordCall(LlmChatRequest req, RoutingResult result, String traceId) {
    try {
    LlmChatResponse resp = result.getResponse();
    String chainJson = mapper.writeValueAsString(
        result.getChain().stream().map(FallbackAttempt::toMap).toList());
    jdbc.update(
        "INSERT INTO llm_calls (id, tenant_id, project_id, node_id, biz_type, " +
          "provider, model, input_tokens, output_tokens, cost_cny, latency_ms, " +
          "status, trace_id, fallback_chain) " +
          "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::jsonb)",
        UUID.randomUUID().toString(),
        defaultTenant(req),
        req.getProjectId(),
        req.getNodeId(),
        req.getBizType() == null ? "" : req.getBizType(),
        resp.getProviderName(),
        resp.getModelName(),
        resp.getInputTokens(),
        resp.getOutputTokens(),
        resp.getCostCny(),
        resp.getLatencyMs(),
        result.getChain().size() > 1 ? "fallback" : "success",
        traceId,
        chainJson
    );
    log.info("[llm-call] recorded provider={} cost={} chain_len={}",
        resp.getProviderName(), resp.getCostCny(), result.getChain().size());
    } catch (Exception e) {
    log.error("[llm-call] failed to record: {}", e.getMessage());
    }
  }

  public void recordFailure(LlmChatRequest req, List<FallbackAttempt> chain, String traceId) {
    try {
    String chainJson = mapper.writeValueAsString(
        chain.stream().map(FallbackAttempt::toMap).toList());
    jdbc.update(
        "INSERT INTO llm_calls (id, tenant_id, project_id, node_id, biz_type, " +
          "provider, model, input_tokens, output_tokens, cost_cny, latency_ms, " +
          "status, trace_id, fallback_chain) " +
          "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::jsonb)",
        UUID.randomUUID().toString(),
        defaultTenant(req),
        req.getProjectId(),
        req.getNodeId(),
        req.getBizType() == null ? "" : req.getBizType(),
        "",
        "",
        0,
        0,
        0.0,
        0,
        "failed",
        traceId,
        chainJson
    );
    log.info("[llm-call] recorded failure chain_len={}", chain.size());
    } catch (Exception e) {
    log.error("[llm-call] failed to record failure: {}", e.getMessage());
    }
  }

  private String defaultTenant(LlmChatRequest req) {
    return req.getTenantId() == null || req.getTenantId().isBlank()
      ? "anon"
      : req.getTenantId();
  }
}
