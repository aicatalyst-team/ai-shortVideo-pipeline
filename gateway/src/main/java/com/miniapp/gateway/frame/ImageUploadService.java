package com.miniapp.gateway.frame;

import com.miniapp.gateway.storage.MinioService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import net.coobird.thumbnailator.Thumbnails;
import org.springframework.stereotype.Service;

import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

@Service
@RequiredArgsConstructor
@Slf4j
public class ImageUploadService {

  private static final Set<String> ALLOWED_MIMES = Set.of(
    "image/jpeg", "image/png", "image/webp"
  );
  private static final Set<String> ALLOWED_EXTS = Set.of("jpg", "jpeg", "png", "webp");

  // 生产准备度三件套
  // - 尺寸下限：参考图/首帧 < 256×256 无意义，直接拒
  // - 尺寸上限：> 8192×8192 加载到 BufferedImage 会爆 OOM（256MB+），防 DoS
  // - JPEG EXIF 剥离：路线 B 上公网必须，防泄露 GPS / 拍摄设备 / 时间 EXIF 元数据
  private static final int MIN_DIMENSION = 256;
  private static final int MAX_DIMENSION = 8192;

  private final MinioService minio;
  private final FrameAssetWriter writer;

  public Map<String, Object> uploadBytes(
    byte[] bytes,
    String mime,
    String originalName,
    String tenantId,
    String kind) throws Exception {
    validate(bytes, mime, originalName);

    String normalizedMime = mime.toLowerCase();
    String ext = extractExt(originalName);
    ImageMeta meta = readMeta(bytes, normalizedMime);

    //  改 30%: 尺寸上下限校验（必须在读 meta 之后才知道尺寸）
    validateDimensions(meta);

    //  改 30%: JPEG 必须剥 EXIF（防 GPS / 拍摄设备等隐私泄漏）
    // PNG/WebP 通常不带 EXIF，跳过避免无谓重编码
    byte[] uploadBytes = "image/jpeg".equals(normalizedMime)
      ? stripExifFromJpeg(bytes)
      : bytes;

    // sha256 必须用「上传到 MinIO 的字节」算，否则去重失效
    String sha256 = minio.sha256(uploadBytes);

    String bucket = minio.getPublicBucket();
    String objectName = minio.buildObjectName(tenantId, sha256, ext);
    String thumbObject = objectName.replace("." + ext, "_thumb.jpg");

    Optional<Map<String, Object>> existingAsset = writer.findBySha256(sha256);
    if (existingAsset.isPresent()) {
    Map<String, Object> asset = existingAsset.get();
    log.info("[upload] db dedup hit sha256={}, skip minio put", sha256);
    //  改 30%: 修 bug — dedup 时从 PG 存的旧 url 推算 thumb_url
    // 不能用当前 tenantId 拼路径（跨 tenant 共享同 sha256 时旧 url tenant 不一样）
    String existingUrl = (String) asset.getOrDefault("url", minio.buildPublicUrl(bucket, objectName));
    String dedupThumbUrl = deriveThumbUrl(existingUrl);
    return Map.of(
        "asset_id", asset.get("id"),
        "url", existingUrl,
        "thumb_url", dedupThumbUrl,
        "sha256", sha256,
        "width", asset.getOrDefault("width", meta.getWidth()),
        "height", asset.getOrDefault("height", meta.getHeight()),
        "size_bytes", uploadBytes.length,
        "dedup", true
    );
    }

    boolean originalExists = minio.exists(bucket, objectName);
    if (!originalExists) {
    try (var stream = new ByteArrayInputStream(uploadBytes)) {
      minio.put(bucket, objectName, stream, uploadBytes.length, normalizedMime);
    }
    } else {
    log.info("[upload] dedup skip original put sha256={}", sha256);
    }
    String url = minio.buildPublicUrl(bucket, objectName);

    byte[] thumb = makeThumbnail(uploadBytes, minio.getThumbnailMaxSide());
    if (!minio.exists(bucket, thumbObject)) {
    try (var stream = new ByteArrayInputStream(thumb)) {
      minio.put(bucket, thumbObject, stream, thumb.length, "image/jpeg");
    }
    }
    String thumbUrl = minio.buildPublicUrl(bucket, thumbObject);

    Map<String, Object> asset = writer.findOrCreate(
      sha256,
      url,
      kind == null || kind.isBlank() ? "upload" : kind,
      meta.getWidth(),
      meta.getHeight(),
      "uploaded",
      tenantId,
      normalizedMime,
      originalName);

    return Map.of(
      "asset_id", asset.get("id"),
      "url", asset.getOrDefault("url", url),
      "thumb_url", thumbUrl,
      "sha256", sha256,
      "width", meta.getWidth(),
      "height", meta.getHeight(),
      //  改 30%: size 用 uploadBytes（EXIF 剥离后的体积），不再用原 bytes
      "size_bytes", uploadBytes.length,
      "dedup", Boolean.TRUE.equals(asset.get("dedup")) || originalExists
    );
  }

  //  改 30%: 从原图 URL 推 thumb_url（同路径替换扩展名为 _thumb.jpg）
  // 配合 dedup 跨 tenant 共享场景：PG 里 url 是 tenantA 的，但 tenantB 上传同图也能拿到对应 thumb
  static String deriveThumbUrl(String url) {
    if (url == null || url.isEmpty()) return "";
    int dot = url.lastIndexOf('.');
    if (dot <= 0 || dot < url.lastIndexOf('/')) return "";
    return url.substring(0, dot) + "_thumb.jpg";
  }

  //  改 30%: 尺寸校验
  private void validateDimensions(ImageMeta meta) {
    if (meta.getWidth() < MIN_DIMENSION || meta.getHeight() < MIN_DIMENSION) {
    throw new IllegalArgumentException(String.format(
        "image too small: %dx%d (min %dx%d)",
        meta.getWidth(), meta.getHeight(), MIN_DIMENSION, MIN_DIMENSION));
    }
    if (meta.getWidth() > MAX_DIMENSION || meta.getHeight() > MAX_DIMENSION) {
    throw new IllegalArgumentException(String.format(
        "image too large: %dx%d (max %dx%d)",
        meta.getWidth(), meta.getHeight(), MAX_DIMENSION, MAX_DIMENSION));
    }
  }

  //  改 30%: JPEG EXIF 剥离
  // 通过 ImageIO 重新编码，自动丢弃所有 EXIF/IPTC/XMP 元数据。
  // 损失 ~5-10% 编码质量（JPEG 二次编码不可避免），但换来用户隐私保护。
  // 对于参考图场景，质量损失肉眼难辨。
  private byte[] stripExifFromJpeg(byte[] jpegBytes) throws Exception {
    BufferedImage img = ImageIO.read(new ByteArrayInputStream(jpegBytes));
    if (img == null) {
    // 解码失败就用原字节（让后续 readMeta 报清楚错误）
    return jpegBytes;
    }
    ByteArrayOutputStream out = new ByteArrayOutputStream();
    // quality 0.92 平衡画质/体积
    Thumbnails.of(img)
      .scale(1.0)
      .outputFormat("jpg")
      .outputQuality(0.92)
      .toOutputStream(out);
    byte[] stripped = out.toByteArray();
    log.info("[exif_strip] {} -> {} bytes ({}% size)",
      jpegBytes.length, stripped.length,
      String.format("%.1f", 100.0 * stripped.length / jpegBytes.length));
    return stripped;
  }

  private void validate(byte[] bytes, String mime, String originalName) {
    if (bytes == null || bytes.length == 0) {
    throw new IllegalArgumentException("file is empty");
    }
    if (bytes.length > minio.getMaxBytes()) {
    throw new IllegalArgumentException("file too large: " + bytes.length + " > " + minio.getMaxBytes());
    }
    if (mime == null || !ALLOWED_MIMES.contains(mime.toLowerCase())) {
    throw new IllegalArgumentException("unsupported mime: " + mime);
    }
    String ext = extractExt(originalName);
    if (!ALLOWED_EXTS.contains(ext)) {
    throw new IllegalArgumentException("unsupported ext: " + ext);
    }
  }

  private ImageMeta readMeta(byte[] bytes, String mime) throws Exception {
    BufferedImage image = ImageIO.read(new ByteArrayInputStream(bytes));
    if (image == null) {
    throw new IllegalArgumentException("cannot decode image");
    }
    return new ImageMeta(image.getWidth(), image.getHeight(), mime);
  }

  private byte[] makeThumbnail(byte[] bytes, int maxSide) throws Exception {
    ByteArrayOutputStream out = new ByteArrayOutputStream();
    Thumbnails.of(new ByteArrayInputStream(bytes))
      .size(maxSide, maxSide)
      .outputFormat("jpg")
      .outputQuality(0.85)
      .toOutputStream(out);
    return out.toByteArray();
  }

  private String extractExt(String filename) {
    if (filename == null) {
    return "";
    }
    int dot = filename.lastIndexOf('.');
    return dot < 0 ? "" : filename.substring(dot + 1).toLowerCase();
  }
}
