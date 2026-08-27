"""端到端：撰写助手对话 + 图片上传插入 + 导出 Word 内嵌图片。

不强制调用豆包生图（需 ARK_API_KEY）；若已配置则额外试一次生图。
"""

import base64
import io
import json
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://localhost:8000"

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII="
)


def call(method: str, path: str, token: str | None = None, json_body: dict | None = None):
    url = f"{BASE}{path}"
    data = json.dumps(json_body).encode("utf-8") if json_body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if json_body is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def call_upload(path: str, token: str, filename: str, content: bytes, content_type: str = "image/png"):
    boundary = "----E2EWriterImage"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
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

    status, body = call(
        "POST",
        "/api/projects",
        token=token,
        json_body={"name": "撰写对话验证项目", "code": "E2E-CHAT-001", "type": "工程"},
    )
    assert status == 200, f"新建项目失败: {status} {body}"
    PROJECT_ID = json.loads(body)["id"]

    status, body = call("GET", f"/api/projects/{PROJECT_ID}/writer-draft", token=token)
    assert status == 200, f"获取草稿失败: {status} {body}"
    draft = json.loads(body)
    draft_id = draft["id"]

    status, body = call(
        "POST",
        f"/api/writer-drafts/{draft_id}/chat",
        token=token,
        json_body={"message": "当前项目有哪些评分维度？不要编造证书有效期。", "history": []},
    )
    assert status == 200, f"对话失败: {status} {body}"
    chat = json.loads(body)
    assert chat.get("reply"), "对话未返回内容"
    canned = "机电安装一级资质（有效期至 2027-03）"
    assert canned not in chat["reply"], f"仍在返回罐头资质文案: {chat['reply'][:200]}"
    print("chat ok, hasChecklist=", chat.get("hasChecklist"), "preview=", chat["reply"][:80].replace("\n", " "))

    status, body = call_upload(
        f"/api/projects/{PROJECT_ID}/writer-images/upload",
        token,
        "e2e-dot.png",
        PNG_1X1,
    )
    assert status == 200, f"上传图片失败: {status} {body}"
    uploaded = json.loads(body)
    image_id = uploaded["id"]
    image_url = uploaded["url"]
    print("upload ok:", image_id, image_url)

    status, body = call("GET", image_url, token=token)
    assert status == 200, f"读取图片失败: {status} {body[:200] if isinstance(body, bytes) else body}"
    assert len(body) > 10, "图片文件为空"
    print("file ok, bytes=", len(body))

    status, body = call("GET", f"/api/projects/{PROJECT_ID}/writer-images", token=token)
    assert status == 200, f"图库列表失败: {status} {body}"
    items = json.loads(body)
    assert any(i["id"] == image_id for i in items), "上传的图片未出现在图库"

    outline = [
        {
            "id": "img-ch-1",
            "num": "1",
            "title": "配图导出验证",
            "parentId": None,
            "expanded": True,
            "weight": 0,
            "dimension": None,
            "idea": "",
            "aiIdea": "",
            "optimized": False,
            "status": "已完成",
            "words": 0,
            "aiRounds": 0,
        }
    ]
    status, body = call("PATCH", f"/api/writer-drafts/{draft_id}", token=token, json_body={"outline": outline})
    assert status == 200, f"写入目录失败: {status} {body}"

    content = f"本章插入一张示意图。\n\n![e2e验证图]({image_url})\n"
    status, body = call(
        "PATCH",
        f"/api/writer-drafts/{draft_id}/chapters/img-ch-1",
        token=token,
        json_body={"content": content},
    )
    assert status == 200, f"保存章节失败: {status} {body}"

    status, body = call("GET", f"/api/writer-drafts/{draft_id}/export", token=token)
    assert status == 200, f"导出失败: {status} {body[:200] if isinstance(body, bytes) else body}"

    import docx

    document = docx.Document(io.BytesIO(body))
    inline_shapes = document.inline_shapes
    assert len(inline_shapes) >= 1, "导出的 Word 未嵌入图片"
    print("export with image ok, inline_shapes=", len(inline_shapes))

    status, body = call(
        "POST",
        f"/api/projects/{PROJECT_ID}/writer-images/generate",
        token=token,
        json_body={"prompt": "施工现场安全交底", "mode": "normal"},
    )
    if status == 200:
        gen = json.loads(body)
        print("generate ok:", gen.get("id"), gen.get("url"))
    else:
        print(f"generate skipped/failed ({status}): {body.decode('utf-8', errors='replace')[:200]}")

    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
