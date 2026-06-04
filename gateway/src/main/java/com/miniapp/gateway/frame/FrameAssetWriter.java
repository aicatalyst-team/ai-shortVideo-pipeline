package com.miniapp.gateway.frame;

import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.util.Map;
import java.util.Optional;
import java.util.UUID;

@Component
@RequiredArgsConstructor
@Slf4j
public class FrameAssetWriter {

  private static final ObjectMapper MAPPER = new ObjectMapper();

  private final JdbcTemplate jdbc;

  public Optional<Map<String, Object>> findBySha256(String sha256) {
    var existing = jdbc.queryForList(
      "SELECT id, url, width, height FROM frame_assets WHERE sha256 = ? LIMIT 1",
      sha256);
    if (existing.isEmpty()) {
    return Optional.empty();
    }
    Map<String, Object> found = new java.util.LinkedHashMap<>(existing.get(0));
    found.put("dedup", true);
    return Optional.of(found);
  }

  public Map<String, Object> findOrCreate(
    String sha256,
    String url,
    String kind,
    int width,
    int height,
    String source,
    String tenantId,
    String mimeType,
    String originalFilename) {

    Optional<Map<String, Object>> existing = findBySha256(sha256);
    if (existing.isPresent()) {
    log.info("[frame_asset] dedup hit sha256={}", sha256);
    return existing.get();
    }

    String id = UUID.randomUUID().toString().replace("-", "").substring(0, 16).toUpperCase();
    String metadataJson = metadataJson(tenantId, mimeType, originalFilename);

    jdbc.update(
      "INSERT INTO frame_assets (id, kind, url, sha256, width, height, source, metadata) " +
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?::jsonb)",
      id, kind, url, sha256, width, height, source, metadataJson);
    log.info("[frame_asset] inserted id={} sha256={}", id, sha256);
    return Map.of(
      "id", id,
      "url", url,
      "width", width,
      "height", height,
      "dedup", false
    );
  }

  private String metadataJson(String tenantId, String mimeType, String originalFilename) {
    try {
    return MAPPER.writeValueAsString(Map.of(
        "tenant_id", tenantId == null ? "" : tenantId,
        "mime_type", mimeType == null ? "" : mimeType,
        "original_filename", originalFilename == null ? "" : originalFilename
    ));
    } catch (Exception e) {
    throw new RuntimeException("metadata json failed", e);
    }
  }
}
