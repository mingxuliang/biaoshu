"""全系统只读冒烟：登录后遍历 OpenAPI 里的全部 GET 接口，带上真实项目的 id，报告 4xx/5xx 与超时。

用法（后端已启动）：python e2e_smoke_test.py [BASE_URL] [PROJECT_ID]
只发 GET，不改数据。5xx 视为失败，401/403/404/422 单独列出供人工判断。
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
PROJECT_ID = sys.argv[2] if len(sys.argv) > 2 else "proj-a1c92a9a28b6"
SLOW_SECONDS = 5.0
SKIP = (r"/stream", r"/events", r"/download", r"/export", r"/file$", r"/trace-matrix")


def call(method: str, path: str, token: str = "", body: dict | None = None, timeout: int = 60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, raw, time.time() - started
    except urllib.error.HTTPError as err:
        return err.code, err.read(), time.time() - started
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc).encode(), time.time() - started


def jget(path: str, token: str):
    status, raw, _ = call("GET", path, token)
    try:
        return status, json.loads(raw)
    except Exception:  # noqa: BLE001
        return status, None


def main() -> int:
    status, raw, _ = call("POST", "/api/auth/login", body={"email": "chen@zhibiaoyun.com", "password": "123456"})
    if status != 200:
        print("login failed", status, raw[:200])
        return 2
    token = json.loads(raw)["token"] if "token" in json.loads(raw) else json.loads(raw)["accessToken"]

    ids: dict[str, str] = {"project_id": PROJECT_ID}
    _, drafts = jget(f"/api/projects/{PROJECT_ID}/writer-draft", token)
    if isinstance(drafts, dict) and drafts.get("id"):
        ids["draft_id"] = drafts["id"]
    for key, path in (
        ("document_id", f"/api/projects/{PROJECT_ID}/documents"),
        ("library_id", "/api/product-libraries"),
        ("doc_id", "/api/knowledge-documents"),
    ):
        _, data = jget(path, token)
        if isinstance(data, list) and data and isinstance(data[0], dict):
            ids[key] = str(data[0].get("id") or "")
    spec = json.loads(call("GET", "/openapi.json")[1])

    failures: list[str] = []
    notes: list[str] = []
    slow: list[str] = []
    checked = 0
    for path, item in sorted(spec["paths"].items()):
        if "get" not in item or any(re.search(p, path) for p in SKIP):
            continue
        params = re.findall(r"\{([^}]+)\}", path)
        url = path
        ok = True
        for name in params:
            guess = ids.get(name) or ids.get(name.replace("Id", "_id")) or (ids.get("project_id") if name in ("project_id", "id") else "")
            if not guess:
                ok = False
                break
            url = url.replace("{" + name + "}", guess)
        if not ok:
            continue
        status, body, elapsed = call("GET", url, token)
        checked += 1
        if elapsed > SLOW_SECONDS:
            slow.append(f"{url} {elapsed:.1f}s")
        if status == 0 or status >= 500:
            failures.append(f"{status} {url} {body[:160].decode('utf-8', 'ignore')}")
        elif status >= 400:
            notes.append(f"{status} {url}")
    print(f"checked {checked} GET endpoints, ids={ids}")
    print(f"FAILURES ({len(failures)}):")
    for line in failures:
        print("  ", line)
    print(f"4xx notes ({len(notes)}):")
    for line in notes[:60]:
        print("  ", line)
    print(f"slow ({len(slow)}):", slow)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
