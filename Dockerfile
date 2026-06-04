FROM docker.m.daocloud.io/library/python:3.11-slim

# 换国内镜像源（腾讯云）
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources

RUN apt-get update -o Acquire::Retries=5 && apt-get install -y --no-install-recommends \
    ffmpeg fonts-wqy-zenhei fonts-wqy-microhei curl \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -fv

WORKDIR /app

COPY requirements.txt .

# D41-B: torch — 走清华 PyPI（pytorch.org CDN 国内严重不稳，networkx 等小包 4KB/s 卡死）
# 代价：清华 PyPI 上的 torch 是 CUDA bundled 版本，镜像会 +1-2GB
# 收益：build 稳定可重复，CDN 不抽风。如果磁盘紧张需切回 CPU 版，恢复 --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir --timeout 300 --retries 10 \
    -i https://pypi.tuna.tsinghua.edu.cn/simple/ \
    --trusted-host pypi.tuna.tsinghua.edu.cn \
    'torch>=2.0,<3'

# 清华 PyPI 镜像 + timeout/retries（生产实战：腾讯云镜像偶发慢/超时导致 build 中断）
RUN pip install --no-cache-dir --timeout 120 --retries 5 \
    -i https://pypi.tuna.tsinghua.edu.cn/simple/ \
    --trusted-host pypi.tuna.tsinghua.edu.cn \
    -r requirements.txt

COPY . .

CMD ["uvicorn", "main_v2:app", "--host", "0.0.0.0", "--port", "8000"]
