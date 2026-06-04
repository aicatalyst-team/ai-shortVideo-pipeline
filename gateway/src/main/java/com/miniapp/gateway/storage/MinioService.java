package com.miniapp.gateway.storage;

import io.minio.GetPresignedObjectUrlArgs;
import io.minio.MinioClient;
import io.minio.PutObjectArgs;
import io.minio.StatObjectArgs;
import io.minio.errors.ErrorResponseException;
import io.minio.http.Method;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.io.InputStream;
import java.security.MessageDigest;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.HexFormat;
import java.util.concurrent.TimeUnit;

@Service
@RequiredArgsConstructor
@Slf4j
public class MinioService {

  private static final DateTimeFormatter DATE_FMT =
    DateTimeFormatter.ofPattern("yyyy/MM/dd").withZone(ZoneOffset.UTC);

  private final MinioClient client;
  private final StorageProperties props;

  public String buildObjectName(String tenantId, String sha256, String ext) {
    if (sha256 == null || sha256.length() < 2) {
    throw new IllegalArgumentException("sha256 must contain at least 2 chars");
    }
    String date = DATE_FMT.format(Instant.now());
    String shaPrefix = sha256.substring(0, 2);
    String safeTenant = sanitizeTenant(tenantId);
    String safeExt = sanitizeExt(ext);
    return String.format("%s/%s/%s/%s.%s", safeTenant, date, shaPrefix, sha256, safeExt);
  }

  public String sha256(byte[] data) {
    try {
    MessageDigest md = MessageDigest.getInstance("SHA-256");
    return HexFormat.of().formatHex(md.digest(data));
    } catch (Exception e) {
    throw new RuntimeException("sha256 failed", e);
    }
  }

  public boolean exists(String bucket, String objectName) {
    try {
    client.statObject(StatObjectArgs.builder()
        .bucket(bucket)
        .object(objectName)
        .build());
    return true;
    } catch (ErrorResponseException e) {
    return false;
    } catch (Exception e) {
    log.warn("[minio] stat error bucket={} object={}: {}", bucket, objectName, e.getMessage());
    return false;
    }
  }

  public void put(String bucket, String objectName, InputStream stream, long size, String contentType) {
    try {
    client.putObject(PutObjectArgs.builder()
        .bucket(bucket)
        .object(objectName)
        .stream(stream, size, -1)
        .contentType(contentType == null || contentType.isBlank()
          ? "application/octet-stream"
          : contentType)
        .build());
    log.info("[minio] put bucket={} object={} size={}", bucket, objectName, size);
    } catch (Exception e) {
    throw new RuntimeException("minio put failed: " + e.getMessage(), e);
    }
  }

  public String buildPublicUrl(String bucket, String objectName) {
    return String.format("%s/%s/%s",
      props.getPublicEndpoint().replaceAll("/$", ""),
      bucket,
      objectName);
  }

  public String presignGet(String bucket, String objectName, int expirySeconds) {
    try {
    return client.getPresignedObjectUrl(GetPresignedObjectUrlArgs.builder()
        .method(Method.GET)
        .bucket(bucket)
        .object(objectName)
        .expiry(expirySeconds, TimeUnit.SECONDS)
        .build());
    } catch (Exception e) {
    throw new RuntimeException("presign failed: " + e.getMessage(), e);
    }
  }

  public String getPublicBucket() {
    return props.getPublicBucket();
  }

  public String getPrivateBucket() {
    return props.getPrivateBucket();
  }

  public long getMaxBytes() {
    return props.getUploadMaxBytes();
  }

  public int getThumbnailMaxSide() {
    return props.getThumbnailMaxSide();
  }

  private String sanitizeTenant(String tenantId) {
    if (tenantId == null || tenantId.isBlank()) {
    return "anon";
    }
    String cleaned = tenantId.replaceAll("[^a-zA-Z0-9_-]", "_");
    return cleaned.isBlank() ? "anon" : cleaned;
  }

  private String sanitizeExt(String ext) {
    if (ext == null || ext.isBlank()) {
    return "bin";
    }
    String cleaned = ext.toLowerCase().replaceAll("[^a-z0-9]", "");
    return cleaned.isBlank() ? "bin" : cleaned;
  }
}
