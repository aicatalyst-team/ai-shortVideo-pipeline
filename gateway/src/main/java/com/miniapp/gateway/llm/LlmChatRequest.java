package com.miniapp.gateway.llm;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

/**
 * LLM chat request DTO.
 *
 * : snake_case ↔ camelCase 映射
 * Python orchestrator 传 snake_case payload（tenant_id / biz_type / project_id / max_tokens）
 * Java 字段是 camelCase。早期实现漏映射，导致 tenant_id 默认 anon 写入 llm_calls。
 * 用 @JsonNaming 单独配置（不全局 SNAKE_CASE 避免影响其他 DTO）。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public class LlmChatRequest {
  private List<Message> messages;
  private String model;
  private Double temperature;
  private Integer maxTokens;
  private String bizType;
  private String tenantId;
  private String projectId;
  private String nodeId;

  @Data
  @NoArgsConstructor
  @AllArgsConstructor
  public static class Message {
    private String role;
    private String content;
  }
}
