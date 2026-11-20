"""出站地址校验：防止把模型接入地址配成内网服务或云主机元数据地址（SSRF）。"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from fastapi import HTTPException

# 云厂商元数据地址，任何情况下都不允许
METADATA_NETS = [ipaddress.ip_network("169.254.0.0/16"), ipaddress.ip_network("fd00:ec2::/32")]


def _resolve(host: str) -> list[ipaddress._BaseAddress]:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return []
    out = []
    for info in infos:
        try:
            out.append(ipaddress.ip_address(info[4][0]))
        except ValueError:
            continue
    return out


def _is_private(addr: ipaddress._BaseAddress) -> bool:
    return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast


def validate_base_url(url: str, *, allow_private: bool = False) -> str:
    """返回规范化后的地址；不合法时抛 400。

    allow_private=True 时允许内网和本机（本地 Ollama、自建网关），但元数据地址始终拒绝。
    """
    text = (url or "").strip().rstrip("/")
    if not text:
        return text
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(400, "接口地址只支持 http / https")
    host = parsed.hostname or ""
    if not host:
        raise HTTPException(400, "接口地址缺少主机名")
    if parsed.username or parsed.password:
        raise HTTPException(400, "接口地址不能内嵌账号密码，请把秘钥填在 API Key 栏")
    addrs = _resolve(host)
    if not addrs:
        try:
            addrs = [ipaddress.ip_address(host)]
        except ValueError:
            # 解析不到的域名放行：保存时可能离线，调用时自然失败，不构成内网访问
            return text
    for addr in addrs:
        if any(addr in net for net in METADATA_NETS):
            raise HTTPException(400, "接口地址指向云主机元数据服务，已拒绝")
        if not allow_private and _is_private(addr):
            raise HTTPException(
                400,
                "接口地址指向内网或本机。本地模型请选「本地模型」类型，或由运维开启 LLM_ALLOW_PRIVATE_BASE_URL",
            )
    return text
