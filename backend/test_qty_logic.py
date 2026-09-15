"""工程量逻辑匹配：清单汇总 + 三条比对（不调大模型）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.engines import e_qty_logic, e3_tech_modules, qty_boq
from app.engines.e_qty_logic import BidQty, QtyHit


def _dims(names: list[str], units: list[str], qtys: list[str]) -> list[dict]:
    return [
        {
            "key": "quantity",
            "items": [
                {
                    "id": "qty-boq",
                    "sections": [
                        {
                            "id": "qb-1",
                            "rows": [
                                {"label": "项目名称", "content": "\n".join(names)},
                                {"label": "计量单位", "content": "\n".join(units)},
                                {"label": "工程数量", "content": "\n".join(qtys)},
                                {"label": "备注", "content": ""},
                            ],
                        }
                    ],
                }
            ],
        }
    ]


def test_boq_agg() -> None:
    dims = _dims(
        ["C30混凝土垫层", "基坑土方开挖", "HRB400钢筋"],
        ["m³", "m³", "t"],
        ["1200", "8000", "85"],
    )
    agg = qty_boq.aggregate(dims)
    assert agg.has_rows
    assert abs(agg.concrete_m3 - 1200) < 1e-6, agg
    assert abs(agg.earth_m3 - 8000) < 1e-6, agg
    assert abs(agg.steel_t - 85) < 1e-6, agg
    print("boq agg ok", agg.concrete_m3, agg.earth_m3, agg.steel_t)


def test_f0609_deviation() -> None:
    dims = _dims(["C30混凝土", "土方开挖"], ["m³", "m³"], ["1000", "5000"])
    bid = BidQty(
        items=[
            QtyHit("concrete", 1600, "m³", excerpt="本工程混凝土总量 1600m³。", source="施组"),
            QtyHit("earth", 5000, "m³", excerpt="土方开挖 5000m³。", source="施组"),
        ]
    )
    findings, module = e_qty_logic.evaluate("", [], dims, extracted=bid)
    rules = [f["rule"] for f in findings]
    assert any("F06.09" in r and "混凝土" in r for r in rules), findings
    assert not any("土方不一致" in r for r in rules), findings
    assert module["key"] == "qty_logic"
    assert module["status"] == "扣分"
    print("F06.09 deviation ok", rules)


def test_no_purchase_plan() -> None:
    dims = _dims(["C30混凝土"], ["m³"], ["1000"])
    bid = BidQty(
        items=[QtyHit("concrete", 1000, "m³", excerpt="混凝土 1000m³。", source="施组")],
        has_material_plan=False,
    )
    findings, _module = e_qty_logic.evaluate("", [], dims, extracted=bid)
    mats = [f for f in findings if "F06.10" in f["rule"]]
    assert mats, findings
    assert mats[0]["severity"] == "建议"
    assert "缺材料计划" in mats[0]["suggestion"]
    assert mats[0]["severity"] != "扣分" or "矛盾" not in mats[0]["suggestion"]
    print("no purchase plan skip ok", mats[0]["suggestion"][:80])


def test_f0611_capacity() -> None:
    dims = _dims(["基坑土方开挖"], ["m³"], ["40000"])
    bid = BidQty(
        items=[
            QtyHit("earth", 40000, "m³", excerpt="土方 40000m³。", source="施组"),
            QtyHit("earth_days", 20, "天", excerpt="土方工期 20 天。", source="进度"),
            QtyHit("excavator_count", 2, "台", excerpt="配备挖掘机 2 台。", source="机械"),
            QtyHit("daily_excavate", 800, "m³", excerpt="日开挖量 800m³。", source="进度"),
        ],
        has_material_plan=False,
    )
    findings, module = e_qty_logic.evaluate(
        "",
        [],
        dims,
        thresholds={"qty_deviation_ok": 5, "qty_material_mismatch": 2, "excavator_m3_per_shift": 400},
        extracted=bid,
    )
    cap = [f for f in findings if "F06.11" in f["rule"]]
    assert cap, findings
    assert any(f["severity"] == "扣分" for f in cap), cap
    assert "假设" in "".join(f["suggestion"] for f in cap) or "默认" in "".join(f["suggestion"] for f in cap)
    assert module["status"] == "扣分"
    print("F06.11 capacity ok", cap[0]["suggestion"][:120])


def test_material_mismatch() -> None:
    dims = _dims(["C30混凝土"], ["m³"], ["1000"])
    bid = BidQty(
        items=[
            QtyHit("concrete", 1000, "m³", excerpt="混凝土浇筑 1000m³。", source="施组"),
            QtyHit("material", 4800, "t", excerpt="采购计划商品砼 4800 吨。", source="材料计划", name="混凝土"),
        ],
        has_material_plan=True,
    )
    findings, _module = e_qty_logic.evaluate("", [], dims, extracted=bid)
    mats = [f for f in findings if "F06.10" in f["rule"] and f["severity"] == "扣分"]
    assert mats, findings
    assert "方案前后矛盾" in mats[0]["suggestion"]
    print("F06.10 material mismatch ok")


def test_switch_off() -> None:
    dims = _dims(["C30混凝土"], ["m³"], ["1000"])
    findings, modules = e3_tech_modules.evaluate(
        "本工程施工组织总纲。混凝土 1000m³。",
        [{"text": "本工程施工组织总纲。混凝土 1000m³。", "style": ""}],
        "某项目",
        tech_keys=set(),
        dimensions=dims,
        thresholds={},
    )
    assert not any(f.get("engine") == "e_qty_logic" for f in findings)
    assert not any(m.get("key") == "qty_logic" for m in modules)
    print("qty_logic switch off ok")


def test_no_boq() -> None:
    bid = BidQty(items=[QtyHit("concrete", 100, "m³", excerpt="混凝土 100m³。", source="施组")])
    findings, module = e_qty_logic.evaluate("混凝土 100m³。", [], [], extracted=bid)
    assert module["status"] == "无法比对"
    assert any("无法比对" in f["suggestion"] for f in findings)
    print("no boq 无法比对 ok")


def main() -> None:
    test_boq_agg()
    test_f0609_deviation()
    test_no_purchase_plan()
    test_f0611_capacity()
    test_material_mismatch()
    test_switch_off()
    test_no_boq()
    print("qty_logic tests ok")


if __name__ == "__main__":
    main()
