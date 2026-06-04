package com.miniapp.gateway.frame;

import lombok.AllArgsConstructor;
import lombok.Data;

@Data
@AllArgsConstructor
public class ImageMeta {
  private int width;
  private int height;
  private String mimeType;
}
