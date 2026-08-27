"""只读校验：青天 v1.1 规则已落入规则 API，引擎按阈值/虚词表判定。"""

import json
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://localhost:8000"

EXPECTED_THRESHOLD_KEYS = {
    "filler_density_safe",
    "full_text_similarity_safe",
    "full_text_similarity_risk",
    "key_section_similarity_safe",
    "key_section_similarity_risk",
    "cross_bidder_paragraph_risk",
    "cross_bidder_whole_risk",
    "asset_liability_ratio_max",
    "price_deviation_ok",
    "price_deviation_warn",
}

EXPECTED_WORDS = ["贯彻", "周密部署", "精心施工，铸造精品", "为了积极响应", "在百忙之中"]


def call(method: str, path: str, token: str | None = None, json_body: dict | None = None):
    url = f"{BASE}{path}"
    body = json.dumps(json_body).encode("utf-8") if json_body is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    if json_body is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def main() -> None:
    status, body = call("POST", "/api/auth/login", json_body={"email": "chen@zhibiaoyun.com", "password": "123456"})
    assert status == 200, f"登录失败: {status} {body}"
    token = json.loads(body)["token"]

    status, body = call("GET", "/api/rules/word-rules", token=token)
    assert status == 200, body
    words = json.loads(body)
    names = {w["word"] for w in words}
    assert len(words) >= 70, f"虚词数量不足: {len(words)}"
    for w in EXPECTED_WORDS:
        assert w in names, f"缺少虚词: {w}"
    with_rewrite = sum(1 for w in words if (w.get("rewrite") or "").strip())
    assert with_rewrite >= 60, f"改写建议过少: {with_rewrite}"
    print(f"word-rules ok count={len(words)} rewrite={with_rewrite}")

    status, body = call("GET", "/api/rules/thresholds", token=token)
    assert status == 200, body
    thresholds = json.loads(body)
    keys = {t["key"] for t in thresholds}
    missing = EXPECTED_THRESHOLD_KEYS - keys
    assert not missing, f"缺少阈值: {missing}"
    print(f"thresholds ok keys={sorted(keys)}")

    status, body = call("GET", "/api/rules/packages", token=token)
    assert status == 200, body
    packages = json.loads(body)
    all_items = [it for p in packages for it in (p.get("items") or [])]
    assert any("扫地杆" in it for it in all_items), "临边包应含扫地杆距地 ≤20cm"
    assert any("扬尘" in p["name"] or any("100%" in it for it in p.get("items") or []) for p in packages)
    print(f"packages ok count={len(packages)}")

    status, body = call("GET", "/api/rules/veto-points", token=token)
    assert status == 200, body
    veto_points = json.loads(body)
    assert len(veto_points) >= 8, f"一票否决清单不足: {len(veto_points)}"
    categories = {item["category"] for item in veto_points}
    assert "星号条款" in categories, f"缺少星号条款: {categories}"
    assert "人员核查" in categories, f"缺少人员核查: {categories}"
    print(f"veto-points ok count={len(veto_points)} categories={sorted(categories)}")

    status, body = call("GET", "/api/rules/catalog", token=token)
    assert status == 200, body
    catalog = json.loads(body)
    by_kind = {}
    for item in catalog:
        by_kind.setdefault(item["kind"], []).append(item)
    assert len(by_kind.get("business", [])) >= 7, f"商务自查不足: {len(by_kind.get('business', []))}"
    assert len(by_kind.get("tech", [])) >= 8, f"技术评分不足: {len(by_kind.get('tech', []))}"
    assert len(by_kind.get("dup_check", [])) >= 8, f"专项检查不足: {len(by_kind.get('dup_check', []))}"
    assert len(by_kind.get("strategy", [])) >= 10, f"高分策略不足: {len(by_kind.get('strategy', []))}"
    business_cats = {i["category"] for i in by_kind["business"]}
    tech_cats = {i["category"] for i in by_kind["tech"]}
    dup_cats = {i["category"] for i in by_kind["dup_check"]}
    strategy_cats = {i["category"] for i in by_kind["strategy"]}
    assert "企业类似业绩" in business_cats, business_cats
    assert "施工组织总纲" in tech_cats, tech_cats
    assert "虚词密度" in dup_cats, dup_cats
    assert "清单化对标响应" in strategy_cats, strategy_cats
    print(
        "catalog ok "
        f"business={len(by_kind['business'])} tech={len(by_kind['tech'])} "
        f"dup={len(by_kind['dup_check'])} strategy={len(by_kind['strategy'])}"
    )

    from app.engines import e4_duplicate_filler, e1_veto

    paras = [
        {"index": 0, "text": "在项目实施过程中，我方将加强现场管理，确保工程质量和安全，高度重视文明施工，全力以赴按期完成本项目建设任务。", "style": ""},
        {"index": 1, "text": "本工程重难点分析：科学安排施工进度，合理组织劳动力，严格按照国家规范和相关标准施工。", "style": ""},
        {"index": 2, "text": "投标报价 -12 万元，投标有效期 30 天。", "style": ""},
    ]
    e4 = e4_duplicate_filler.run(paras)
    assert any("F10.02" in f["rule"] or "F06.05" in f["rule"] for f in e4), f"E4 应命中虚词或查重: {e4}"
    e1 = e1_veto.run(paras, {"budget_cap_wan": 100, "validity_days_required": 90}, [{"clause": "必须提交安全生产许可证原件扫描件", "original": "投标人须知", "type": "星号条款"}])
    assert any(f["severity"] == "废标" for f in e1), f"E1 应对负数报价或星号未响应给出废标: {e1}"
    print(f"engine self-check ok e4={len(e4)} e1={len(e1)}")

    print("qingtian rules v1.1 imported ok")


if __name__ == "__main__":
    main()
