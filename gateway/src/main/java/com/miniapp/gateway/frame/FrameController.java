package com.miniapp.gateway.frame;

import com.miniapp.gateway.auth.JwtAuthFilter;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.io.buffer.DataBufferUtils;
import org.springframework.http.ResponseEntity;
import org.springframework.http.codec.multipart.FilePart;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestPart;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

import java.util.Map;

@RestController
@RequestMapping("/api/v1/frames")
@RequiredArgsConstructor
@Slf4j
public class FrameController {

  private final ImageUploadService uploadService;

  @PostMapping(value = "/upload", consumes = "multipart/form-data")
  public Mono<ResponseEntity<?>> upload(
    @RequestPart("file") Mono<FilePart> filePartMono,
    @RequestPart(value = "kind", required = false) Mono<String> kindMono,
    ServerWebExchange exchange) {

    String tenantId = (String) exchange.getAttributes()
      .getOrDefault(JwtAuthFilter.ATTR_TENANT_ID, "anon");

    return filePartMono.flatMap(filePart ->
      DataBufferUtils.join(filePart.content())
        .flatMap(buffer -> {
          byte[] bytes = new byte[buffer.readableByteCount()];
          buffer.read(bytes);
          DataBufferUtils.release(buffer);
          return kindMono.defaultIfEmpty("upload")
            .flatMap(kind -> Mono.fromCallable(() -> {
                String contentType = filePart.headers().getContentType() == null
                    ? null
                    : filePart.headers().getContentType().toString();
                log.info("[frame_upload] tenant={} kind={} filename={} size={}",
                    tenantId, kind, filePart.filename(), bytes.length);
                return uploadService.uploadBytes(
                    bytes,
                    contentType,
                    filePart.filename(),
                    tenantId,
                    kind);
                })
                .subscribeOn(Schedulers.boundedElastic())
                .map(result -> ResponseEntity.ok().body((Object) result))
                .onErrorResume(IllegalArgumentException.class, e -> {
                log.warn("[frame_upload] reject: {}", e.getMessage());
                return Mono.just(ResponseEntity.badRequest().body((Object) Map.of(
                    "error", "upload_rejected",
                    "message", e.getMessage()
                )));
                })
                .onErrorResume(Exception.class, e -> {
                log.error("[frame_upload] failed", e);
                return Mono.just(ResponseEntity.internalServerError().body((Object) Map.of(
                    "error", "upload_failed",
                    "message", e.getMessage()
                )));
                }));
        }));
  }
}
