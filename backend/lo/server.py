"""常驻 LibreOffice 渲染服务：POST /convert 收 .docx，返回 PDF。

soffice 启动一次、保持运行，之后每次转换只需加载文档再导出，不再冷启动。
同一时间只转一份（LibreOffice 的 UNO 接口不是为并发设计的），请求排队。
转换超时或 soffice 挂掉时，杀掉重启，下一次请求自动恢复。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import uno
from com.sun.star.beans import PropertyValue

PORT = int(os.environ.get("LO_PORT", "8090"))
SOFFICE_PORT = int(os.environ.get("SOFFICE_PORT", "2002"))
TIMEOUT = float(os.environ.get("LO_CONVERT_TIMEOUT", "90"))
RESTART_AFTER = int(os.environ.get("LO_RESTART_AFTER", "300"))
MAX_BYTES = 80 * 1024 * 1024

_lock = threading.Lock()
_proc: subprocess.Popen | None = None
_profile: str | None = None
_count = 0


def _prop(name: str, value) -> PropertyValue:
    item = PropertyValue()
    item.Name = name
    item.Value = value
    return item


def _stop() -> None:
    global _proc, _profile
    if _proc is not None:
        try:
            _proc.kill()
            _proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            pass
    _proc = None
    if _profile:
        shutil.rmtree(_profile, ignore_errors=True)
    _profile = None


def _desktop():
    local = uno.getComponentContext()
    resolver = local.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local)
    ctx = resolver.resolve(f"uno:socket,host=127.0.0.1,port={SOFFICE_PORT};urp;StarOffice.ComponentContext")
    return ctx.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)


def _ensure_soffice():
    """soffice 没起来或已退出就重启，等 UNO 端口可连后返回 Desktop。"""
    global _proc, _profile, _count
    if _proc is not None and (_proc.poll() is not None or _count >= RESTART_AFTER):
        _stop()
        _count = 0
    if _proc is None:
        _profile = tempfile.mkdtemp(prefix="lo-profile-")
        _proc = subprocess.Popen(
            [
                "soffice",
                "--headless",
                "--invisible",
                "--nologo",
                "--norestore",
                "--nofirststartwizard",
                f"-env:UserInstallation=file://{_profile}",
                f"--accept=socket,host=127.0.0.1,port={SOFFICE_PORT};urp;",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    last: Exception | None = None
    deadline = time.time() + 40
    while time.time() < deadline:
        if _proc.poll() is not None:
            _stop()
            raise RuntimeError("soffice 启动后立即退出")
        try:
            return _desktop()
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.4)
    _stop()
    raise RuntimeError(f"soffice 40 秒内没有就绪：{last}")


def _convert(data: bytes) -> bytes:
    global _count
    work = tempfile.mkdtemp(prefix="lo-job-")
    src = os.path.join(work, f"{uuid.uuid4().hex}.docx")
    dst = os.path.join(work, "out.pdf")
    result: dict = {}

    def run() -> None:
        global _count
        doc = None
        try:
            desktop = _ensure_soffice()
            with open(src, "wb") as fh:
                fh.write(data)
            doc = desktop.loadComponentFromURL(uno.systemPathToFileUrl(src), "_blank", 0, (_prop("Hidden", True),))
            if doc is None:
                raise RuntimeError("LibreOffice 打不开该文档")
            doc.storeToURL(uno.systemPathToFileUrl(dst), (_prop("FilterName", "writer_pdf_Export"),))
            with open(dst, "rb") as fh:
                result["pdf"] = fh.read()
            _count += 1
        except Exception as exc:  # noqa: BLE001
            result["error"] = exc
        finally:
            if doc is not None:
                try:
                    doc.close(True)
                except Exception:  # noqa: BLE001
                    pass

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(TIMEOUT)
    try:
        if worker.is_alive():
            _stop()  # 卡住了：杀掉 soffice，让下一次请求重新拉起
            raise TimeoutError("转换超时")
        if "error" in result:
            _stop()
            raise result["error"]
        return result["pdf"]
    finally:
        shutil.rmtree(work, ignore_errors=True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: D102 —— 只在出错时打印
        pass

    def _reply(self, status: int, body: bytes, ctype: str = "text/plain; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802, D102
        if self.path == "/health":
            self._reply(200, b"ok")
        else:
            self._reply(404, b"not found")

    def do_POST(self):  # noqa: N802, D102
        if self.path != "/convert":
            self._reply(404, b"not found")
            return
        try:
            size = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            size = 0
        if size <= 0 or size > MAX_BYTES:
            self._reply(400, b"bad size")
            return
        data = self.rfile.read(size)
        started = time.time()
        try:
            with _lock:
                pdf = _convert(data)
        except Exception as exc:  # noqa: BLE001
            print(f"convert failed after {time.time() - started:.1f}s: {exc}", flush=True)
            self._reply(500, str(exc).encode("utf-8", "replace")[:300])
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(pdf)))
        self.send_header("X-Convert-Ms", str(int((time.time() - started) * 1000)))
        self.end_headers()
        self.wfile.write(pdf)


def main() -> None:
    # 启动时先拉起 soffice，第一次请求不用等
    try:
        with _lock:
            _ensure_soffice()
    except Exception as exc:  # noqa: BLE001
        print(f"warm start failed: {exc}", flush=True)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"lo render service on :{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
