"""端到端：团队邀请/停用 + 资质证照录入。"""

import json
import sys
import urllib.error
import urllib.request

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


def call_form(path: str, token: str, fields: dict[str, str]):
    boundary = "----E2EQual"
    parts = []
    for name, value in fields.items():
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode("utf-8")
        )
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(parts)
    req = urllib.request.Request(f"{BASE}{path}", data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
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

    status, body = call("GET", "/api/users", token=token)
    assert status == 200, f"列出用户失败: {status} {body}"
    users = json.loads(body)
    assert any(u["email"] == "chen@zhibiaoyun.com" for u in users), "默认管理员不在列表中"
    assert "disabled" in users[0] and "projectCount" in users[0]
    print("list users ok, count=", len(users))

    email = "e2e-member@zby.ai"
    existing = next((u for u in users if u["email"] == email), None)
    if existing:
        member_id = existing["id"]
        call("PATCH", f"/api/users/{member_id}", token=token, json_body={"disabled": False})
    else:
        status, body = call(
            "POST",
            "/api/users",
            token=token,
            json_body={"name": "E2E成员", "email": email, "phone": "13900000000", "role": "撰写专家"},
        )
        assert status == 200, f"邀请失败: {status} {body}"
        created = json.loads(body)
        assert created["initialPassword"] == "123456"
        member_id = created["id"]
        print("invite ok:", member_id)

    status, body = call("POST", "/api/auth/login", json_body={"email": email, "password": "123456"})
    assert status == 200, f"新账号登录失败: {status} {body}"
    member_token = json.loads(body)["token"]
    status, body = call(
        "POST",
        "/api/users",
        token=member_token,
        json_body={"name": "越权用户", "email": "should-fail@zby.ai", "role": "撰写专家"},
    )
    assert status == 403, f"撰写专家不应能邀请成员: {status} {body}"
    print("writer role cannot invite ok")

    status, body = call("PATCH", f"/api/users/{member_id}", token=token, json_body={"disabled": True})
    assert status == 200, f"停用失败: {status} {body}"
    status, body = call("POST", "/api/auth/login", json_body={"email": email, "password": "123456"})
    assert status == 401, f"停用后仍能登录: {status} {body}"
    print("disable blocks login ok")

    call("PATCH", f"/api/users/{member_id}", token=token, json_body={"disabled": False})

    status, body = call("GET", "/api/qualifications", token=token)
    assert status == 200, f"证照列表失败: {status} {body}"
    quals = json.loads(body)
    print("list qualifications ok, count=", len(quals))

    status, body = call_form(
        "/api/qualifications",
        token,
        {
            "kind": "cert",
            "name": "E2E测试证书",
            "level": "一级",
            "number": "E2E-001",
            "valid_until": "长期",
            "owner": "",
            "detail": "端到端录入",
        },
    )
    assert status == 200, f"录入证照失败: {status} {body}"
    created_q = json.loads(body)
    assert created_q["status"] == "有效"
    print("create qualification ok:", created_q["id"])

    status, body = call("DELETE", f"/api/qualifications/{created_q['id']}", token=token)
    assert status == 200, f"删除证照失败: {status} {body}"
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
