package com.miniapp.gateway.sse;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;

public record JobSnapshot(
    String id,
    String jobType,
    String status,
    int progress,
    String progressStage,
    String resultJson,
    String error,
    String targetId,
    long updatedTs
) {
  private static final Set<String> TERMINAL = Set.of("done", "failed", "cancelled");

  public boolean isTerminal() {
    return status != null && TERMINAL.contains(status);
  }

  public String fingerprint() {
    return status + ":" + progress + ":" + progressStage + ":" + (error == null ? "" : error.hashCode());
  }

  public String eventType() {
    if ("done".equals(status)) {
    return "completed";
    }
    if ("failed".equals(status)) {
    return "failed";
    }
    if ("cancelled".equals(status)) {
    return "cancelled";
    }
    if (progress == 0 && "queued".equals(status)) {
    return "started";
    }
    return "progress";
  }

  public Map<String, Object> toMap(String traceId) {
    Map<String, Object> data = new LinkedHashMap<>();
    data.put("job_id", id);
    data.put("job_type", jobType);
    data.put("status", status);
    data.put("progress", progress);
    data.put("progress_stage", progressStage);
    if (resultJson != null) {
    data.put("result", resultJson);
    }
    if (error != null) {
    data.put("error", error);
    }
    if (targetId != null) {
    data.put("target_id", targetId);
    }
    data.put("updated_ts", updatedTs);
    if (traceId != null && !traceId.isEmpty()) {
    data.put("trace_id", traceId);
    }
    return data;
  }
}
