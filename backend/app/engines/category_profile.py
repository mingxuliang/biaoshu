"""标书类别（工程类 / 软件服务类）的业务差异，集中在这里，供预审、修改闭环、导出共用。

之前预审编排里按类别分流规则表，修改闭环和导出复检各写各的口径，导致软件服务类项目在导出时
读错规则表、工程类的人工核验项在修改闭环里也能被「采纳」。这里统一成一处定义：

- load_rule_bundle：预审与导出复检读同一套规则表；
- classify_fix_mode：判断问题能不能靠改正文解决（text），还是必须去别的文件或证件里核对（manual）；
- rewrite_context：改写提示词里的类别语境；
- default_export_mode：暗标是否启用，只看技术册，并跟随招标文件。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from . import rules_config
from .bid_kind import SCOPE_TECH
from .parse_schema import ENGINEERING_CATEGORY, DEFAULT_CATEGORY, is_engineering_category, normalize_category
from .rules_data import catalog_bundle

MODE_CLEAR = "明标"
MODE_BLIND = "暗标"


def category_label(category: str | None) -> str:
    """给界面和导出记录用的类别名。"""
    return "工程标" if is_engineering_category(category) else "软件服务标"


def category_key(category: str | None) -> str:
    """落库用的规范类别值：工程类 / 软件服务类。"""
    return ENGINEERING_CATEGORY if is_engineering_category(category) else DEFAULT_CATEGORY


@dataclass
class RuleBundle:
    is_engineering: bool
    veto_keys: set[str] = field(default_factory=set)
    biz_keys: set[str] = field(default_factory=set)
    tech_keys: set[str] = field(default_factory=set)
    strategy_keys: set[str] = field(default_factory=set)
    local_items: list = field(default_factory=list)
    word_rules: list = field(default_factory=list)
    thresholds: dict = field(default_factory=dict)
    dup_keys: set[str] = field(default_factory=set)
    anon_keys: set[str] = field(default_factory=set)
    catalog: dict = field(default_factory=dict)


def local_items_for_specialty(items: list[str] | None, specialty: str | None) -> list[str]:
    """扬尘六个 100% 和临边 1.2m 只核房建、市政。水利、公路正文写到这些词也不套这套细则。"""
    rows = [str(item) for item in (items or []) if str(item).strip()]
    if (specialty or "").strip() not in {"水利", "公路"}:
        return rows
    return [item for item in rows if "扬尘" not in item and "临边" not in item]


def _specialize(catalog: dict, specialty: str | None) -> dict:
    """房建市政才保留扬尘和临边细则；水利追加专业规则池里的资格和商务项。"""
    out = dict(catalog)
    name = (specialty or "").strip()
    if name in {"水利", "公路", "房建", "市政"}:
        tech = []
        for item in catalog.get("tech") or []:
            row = dict(item)
            if row.get("key") == "safety" and name not in {"房建", "市政"}:
                row["items"] = [bit for bit in (row.get("items") or []) if "扬尘" not in bit and "临边" not in bit]
                if name == "水利":
                    row["point"] = "安全责任制、危险源清单、专项防护；水利项目另核安全度汛。"
            tech.append(row)
        out["tech"] = tech
    return out


def load_rule_bundle(db: Session, category: str | None, specialty: str | None = None) -> RuleBundle:
    """按类别读规则：工程类读原有四个 load_enabled_*，软件服务类读 sw_ 系列独立表。"""
    engineering = is_engineering_category(category)
    if engineering:
        return RuleBundle(
            is_engineering=True,
            veto_keys=rules_config.load_enabled_veto_keys(db),
            biz_keys=rules_config.load_enabled_catalog_keys(db, "business"),
            tech_keys=rules_config.load_enabled_catalog_keys(db, "tech"),
            strategy_keys=rules_config.load_enabled_catalog_keys(db, "strategy"),
            local_items=local_items_for_specialty(rules_config.load_enabled_package_items(db), specialty),
            word_rules=rules_config.load_enabled_filler_words(db),
            thresholds=rules_config.load_thresholds(db),
            dup_keys=rules_config.load_enabled_catalog_keys(db, "dup_check"),
            anon_keys=rules_config.load_enabled_catalog_keys(db, "anon"),
            catalog=_specialize(catalog_bundle(True), specialty),
        )
    return RuleBundle(
        is_engineering=False,
        veto_keys=rules_config.load_enabled_sw_veto_keys(db),
        biz_keys=rules_config.load_enabled_sw_catalog_keys(db, "business"),
        tech_keys=rules_config.load_enabled_sw_catalog_keys(db, "tech"),
        strategy_keys=rules_config.load_enabled_sw_catalog_keys(db, "strategy"),
        local_items=rules_config.load_sw_local_items(db),
        word_rules=rules_config.load_enabled_sw_filler_words(db),
        thresholds=rules_config.load_sw_thresholds(db),
        dup_keys=rules_config.load_enabled_sw_catalog_keys(db, "dup_check"),
        anon_keys=rules_config.load_enabled_sw_catalog_keys(db, "anon"),
        catalog=catalog_bundle(False),
    )


# ---------------------------------------------------------------------------
# 问题可修性：能不能靠改正文解决
# ---------------------------------------------------------------------------

FIX_TEXT = "text"
FIX_MANUAL = "manual"

# 两类标书共有：证件、人员、联网核验类，改正文没有用。
_COMMON_MANUAL = ("社保", "证书", "资质", "信用", "人工核验", "联网", "扫描件")

# 工程类：数据来自清单、图纸、现场，不在投标书正文里。
_ENGINEERING_MANUAL = (
    "图面",
    "图纸",
    "工程量",
    "清单",
    "造价",
    "踏勘",
    "安全生产许可证",
    "建造师",
    "业绩证明",
)
_ENGINEERING_HINT = "这一项要到工程量清单、图纸或证件原件里核对，不在正文改。请在对应文件中处理后，手动标记已修复。"

# 软件服务类：证书、软著、等保、授权等材料，要换附件。
_SOFTWARE_MANUAL = (
    "软著",
    "软件著作权",
    "等保",
    "等级保护",
    "授权",
    "原厂",
    "验收证明",
    "合同复印件",
)
_SOFTWARE_HINT = "这一项要换证书、软著、等保、授权书或合同附件，不在正文改。请补齐附件后，手动标记已修复。"


def classify_fix_mode(issue: dict, category: str | None) -> tuple[str, str]:
    """返回 (fixMode, fixHint)。manual 表示正文里改不了，修改闭环不给「采纳」。"""
    engineering = is_engineering_category(category)
    rule = str(issue.get("rule") or "")
    location = str(issue.get("location") or "")
    blob = f"{rule}{location}"
    hint = _ENGINEERING_HINT if engineering else _SOFTWARE_HINT
    if str(issue.get("issueClass") or "") == "human_check":
        return FIX_MANUAL, hint
    keys = _COMMON_MANUAL + (_ENGINEERING_MANUAL if engineering else _SOFTWARE_MANUAL)
    if any(k in blob for k in keys):
        return FIX_MANUAL, hint
    return FIX_TEXT, ""


# ---------------------------------------------------------------------------
# 改写提示词里的类别语境
# ---------------------------------------------------------------------------

_ENGINEERING_CONTEXT = (
    "这是工程类投标文件。改写时尽量引用规范条文号（如 GB、JGJ、行业标准编号），"
    "把工期、质量、安全文明施工、环保措施写成可量化的节点、数量、频次，不要编造工程量或业绩。"
)
_SOFTWARE_CONTEXT = (
    "这是软件服务类投标文件。改写时尽量落到功能点、接口、SLA 响应与恢复时限、等保等级、"
    "人天与交付周期，不要编造产品功能、证书编号或客户案例。"
)


def rewrite_context(category: str | None) -> str:
    return _ENGINEERING_CONTEXT if is_engineering_category(category) else _SOFTWARE_CONTEXT


# ---------------------------------------------------------------------------
# 暗标：只对技术册生效，是否启用跟随招标文件
# ---------------------------------------------------------------------------


def tender_requires_anonymity(checklist_params: dict | None) -> bool:
    return bool((checklist_params or {}).get("anonymity_required"))


def default_export_mode(scope: str, checklist_params: dict | None) -> str:
    """技术册且招标要求暗标时默认暗标；商务册永远是明标。"""
    if scope == SCOPE_TECH and tender_requires_anonymity(checklist_params):
        return MODE_BLIND
    return MODE_CLEAR


def effective_export_mode(scope: str, requested: str | None, checklist_params: dict | None) -> str:
    """用户选择为准，但商务册不允许暗标；没选时用招标默认值。"""
    if scope != SCOPE_TECH:
        return MODE_CLEAR
    if requested in (MODE_CLEAR, MODE_BLIND):
        return requested
    return default_export_mode(scope, checklist_params)


__all__ = [
    "FIX_MANUAL",
    "FIX_TEXT",
    "MODE_BLIND",
    "MODE_CLEAR",
    "RuleBundle",
    "category_key",
    "category_label",
    "classify_fix_mode",
    "default_export_mode",
    "effective_export_mode",
    "load_rule_bundle",
    "normalize_category",
    "rewrite_context",
    "tender_requires_anonymity",
]
