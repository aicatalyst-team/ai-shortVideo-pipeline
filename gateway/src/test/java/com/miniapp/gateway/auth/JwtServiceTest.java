package com.miniapp.gateway.auth;

import io.jsonwebtoken.Claims;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class JwtServiceTest {

  private JwtService jwtService;

  @BeforeEach
  void setUp() {
    jwtService = new JwtService("test-secret-must-be-at-least-32-bytes-long!", 3600L);
  }

  @Test
  void issueAndParse_returnsClaims() {
    String token = jwtService.issue("user-1", "tenant-a");
    assertThat(token).isNotBlank();

    Claims claims = jwtService.parse(token);
    assertThat(claims.getSubject()).isEqualTo("user-1");
    assertThat(claims.get("tenant_id", String.class)).isEqualTo("tenant-a");
  }

  @Test
  void verifyAndExtract_returnsNullForInvalidToken() {
    JwtService.AuthPrincipal p = jwtService.verifyAndExtract("not-a-jwt");
    assertThat(p).isNull();
  }

  @Test
  void verifyAndExtract_returnsPrincipal_forValidToken() {
    String token = jwtService.issue("u1", "t1");
    JwtService.AuthPrincipal p = jwtService.verifyAndExtract(token);

    assertThat(p).isNotNull();
    assertThat(p.userId()).isEqualTo("u1");
    assertThat(p.tenantId()).isEqualTo("t1");
  }

  @Test
  void shortSecret_throws() {
    assertThatThrownBy(() -> new JwtService("short", 3600L))
      .isInstanceOf(IllegalStateException.class)
      .hasMessageContaining(">= 32 bytes");
  }

  @Test
  void expiredToken_returnsNull() throws InterruptedException {
    JwtService shortLived = new JwtService("test-secret-must-be-at-least-32-bytes-long!", 0L);
    String token = shortLived.issue("u1", "t1");
    Thread.sleep(1100);

    JwtService.AuthPrincipal p = shortLived.verifyAndExtract(token);

    assertThat(p).isNull();
  }
}
