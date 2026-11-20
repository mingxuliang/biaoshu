FROM debian:bookworm-slim

# 常驻 LibreOffice：把撰写页导出的 .docx 渲染成 PDF，供版式预览。
# 字体全部是可再分发的开源字体，Word 里的中文字体名由 fontconfig 映射过来（见 fonts.conf）。
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice-writer-nogui python3 python3-uno fontconfig \
        fonts-noto-cjk fonts-arphic-ukai fonts-wqy-microhei \
        fonts-liberation2 fonts-crosextra-carlito fonts-crosextra-caladea \
    && rm -rf /var/lib/apt/lists/*

COPY fonts.conf /etc/fonts/conf.d/45-writer-cjk.conf
# 预留：把有授权的字体文件（仿宋、黑体等）放进 fonts/，构建后会优先于映射生效。
COPY fonts/ /usr/local/share/fonts/custom/
RUN fc-cache -f

WORKDIR /app
COPY server.py .

ENV LO_PORT=8090 \
    SOFFICE_PORT=2002 \
    LO_CONVERT_TIMEOUT=90 \
    LO_RESTART_AFTER=300

EXPOSE 8090

RUN useradd -m -u 1001 lo
USER lo

CMD ["python3", "/app/server.py"]
