"""端到端：审计日志写入 + 全局搜索。"""

import json
import sys
import urllib.error
import urllib.request
from urllib.parse import quote

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://localhost:8000"


def call(method: str, path: str, token: str | None = None, json_body: dict | None = None):
    url = f"{BASE}{path}"
    data = json.dumps(json_body).encode("utf-8") if json_body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if json_body is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def main() -> None:
    status, body = call("POST", "/api/auth/login", json_body={"email": "chen@zhibiaoyun.com", "password": "123456"})
    assert status == 200, f"登录失败: {status} {body}"
    token = json.loads(body)["token"]

    status, body = call("GET", "/api/audit-logs", token=token)
    assert status == 200, f"列出审计日志失败: {status} {body}"
    payload = json.loads(body)
    assert "items" in payload and "weekTotal" in payload and "weekExport" in payload and "aiCount" in payload
    print("list audit-logs ok, total=", payload["total"])

    status, body = call("GET", f"/api/search?q={quote('chen')}", token=token)
    assert status == 200, f"搜索失败: {status} {body}"
    hits = json.loads(body)
    assert any(m["email"] == "chen@zhibiaoyun.com" for m in hits["members"]), "搜索未命中管理员"
    print("search member ok")

    status, body = call("GET", "/api/projects", token=token)
    assert status == 200, f"列出项目失败: {status} {body}"
    projects = json.loads(body)
    assert projects, "需要至少一个项目才能验证引用知识审计"
    project_id = projects[0]["id"]

    status, body = call("GET", f"/api/projects/{project_id}/writer-draft", token=token)
    assert status == 200, f"获取撰写草稿失败: {status} {body}"
    draft = json.loads(body)

    status, body = call(
        "PATCH",
        f"/api/writer-drafts/{draft['id']}",
        token=token,
        json_body={"knowledgeRefs": {"ch-e2e": [{"docId": "kdoc-e2e", "docTitle": "e2e引用", "chapters": [], "mode": "manual"}]}},
    )
    assert status == 200, f"更新知识引用失败: {status} {body}"

    status, body = call("GET", "/api/audit-logs", token=token)
    assert status == 200, f"筛选审计日志失败: {status} {body}"
    filtered = json.loads(body)
    assert any(item["action"] == "引用知识" for item in filtered["items"]), "未写入「引用知识」审计"
    assert filtered["aiCount"] >= 1
    print("audit write 引用知识 ok, aiCount=", filtered["aiCount"])

    status, body = call("GET", f"/api/search?q={quote(projects[0]['code'])}", token=token)
    assert status == 200, f"搜索项目失败: {status} {body}"
    print("search project ok, projects=", len(json.loads(body)["projects"]))
    print("PASS")


if __name__ == "__main__":
    main()
