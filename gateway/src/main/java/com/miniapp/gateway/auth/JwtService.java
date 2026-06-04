package com.miniapp.gateway.auth;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.util.Date;

/**
 * HS256 JWT issuer and verifier.
 * Production should move to RS256 plus managed keys.
 */
@Service
@Slf4j
public class JwtService {

  private final SecretKey key;
  private final long expirationSeconds;

  public JwtService(
    @Value("${gateway.auth.jwt-secret}") String secret,
    @Value("${gateway.auth.jwt-expiration-seconds:86400}") long expirationSeconds
  ) {
    byte[] keyBytes = secret.getBytes(StandardCharsets.UTF_8);
    if (keyBytes.length < 32) {
    throw new IllegalStateException(
        "JWT secret must be >= 32 bytes for HS256, got " + keyBytes.length);
    }
    this.key = Keys.hmacShaKeyFor(keyBytes);
    this.expirationSeconds = expirationSeconds;
  }

  public String issue(String userId, String tenantId) {
    long now = System.currentTimeMillis();
    return Jwts.builder()
      .subject(userId)
      .issuedAt(new Date(now))
      .expiration(new Date(now + expirationSeconds * 1000L))
      .claim("tenant_id", tenantId)
      .signWith(key, Jwts.SIG.HS256)
      .compact();
  }

  public Claims parse(String token) {
    return Jwts.parser()
      .verifyWith(key)
      .build()
      .parseSignedClaims(token)
      .getPayload();
  }

  public AuthPrincipal verifyAndExtract(String token) {
    try {
    Claims claims = parse(token);
    String userId = claims.getSubject();
    String tenantId = claims.get("tenant_id", String.class);
    if (userId == null || tenantId == null) {
      return null;
    }
    return new AuthPrincipal(userId, tenantId);
    } catch (Exception e) {
    log.debug("jwt parse failed: {}", e.getMessage());
    return null;
    }
  }

  public record AuthPrincipal(String userId, String tenantId) {}
}
