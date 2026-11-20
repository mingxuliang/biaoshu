"""资质证照库按材料类型的结构化字段。抽取、前端编辑、商务标取材共用同一份定义。"""

from __future__ import annotations

import re

PROJECT_KINDS = ("contract", "achievement")

# 每种类型的字段：键 → 中文标签。展示和提示词都按这个顺序。
KIND_FIELDS: dict[str, dict[str, str]] = {
    "cert": {
        "certName": "证书名称",
        "issuer": "发证机构",
        "number": "证书编号",
        "level": "等级",
        "validFrom": "发证日期",
        "validUntil": "有效期至",
    },
    "people": {
        "name": "姓名",
        "role": "拟任角色",
        "title": "职称",
        "certificates": "持有证书",
        "education": "学历",
        "years": "从业年限",
    },
    "contract": {
        "projectName": "项目名称",
        "client": "客户",
        "contractNo": "合同编号",
        "amount": "合同金额",
        "signDate": "签订日期",
        "startDate": "开始日期",
        "endDate": "结束日期",
        "category": "项目类型",
        "scope": "建设内容",
        "contact": "客户联系人",
    },
    "financial": {"year": "年度", "docType": "材料种类"},
    "credit": {"docType": "材料种类", "issuer": "出具机构", "issueDate": "出具日期"},
    "equipment": {"model": "型号", "quantity": "数量"},
}
KIND_FIELDS["achievement"] = KIND_FIELDS["contract"]

KIND_LABEL = {
    "cert": "资质证照",
    "people": "人员",
    "contract": "合同",
    "achievement": "业绩",
    "financial": "财务",
    "credit": "信用",
    "equipment": "设备",
}

# 字段标签、表头词和说明性词语，不能当材料名称
LABEL_WORDS = {
    "职务", "职称", "姓名", "性别", "年龄", "学历", "专业", "序号", "备注", "说明", "项目方", "项目名称",
    "项目所在地", "项目覆盖人员规模", "合同金额", "合同名称", "合同内容", "客户名称", "起始日期", "联系人及电话",
    "保密说明", "名称", "类型", "数量", "单位", "金额", "日期", "时间", "内容", "编号", "证书编号", "有效期",
    "人员资质要求", "项目经理", "工作经历", "联系人", "联系电话", "功能名称", "功能说明",
}
# 报价、评分索引、服务单价这类商务表格，不是资质材料
NOT_QUAL_TITLE = re.compile(
    r"索引表|评审索引|收费表|服务单价|人月|报价|偏离表|评分|报价一览|开标一览|功能说明|功能名称|目录$"
)


def allowed_fields(kind: str) -> dict[str, str]:
    return KIND_FIELDS.get(kind, KIND_FIELDS["cert"])


def clean_attrs(kind: str, raw) -> dict[str, str]:
    """只留该类型允许的字段，值转字符串并裁长。"""
    if not isinstance(raw, dict):
        return {}
    fields = allowed_fields(kind)
    out: dict[str, str] = {}
    for key in fields:
        value = raw.get(key)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            value = "、".join(str(v) for v in value if str(v).strip())
        text = str(value).strip()
        if text and text not in ("无", "未知", "null", "None", "-", "—"):
            out[key] = text[:200]
    return out


def is_fragment_name(name: str, min_len: int = 3) -> bool:
    """判断一个名称是不是表格碎片：空、过短、纯数字、字段标签、以冒号结尾。"""
    text = re.sub(r"\s+", "", name or "")
    if len(text) < min_len:
        return True
    if re.fullmatch(r"[\d.、，,）)（(\-—_]+", text):
        return True
    if text.rstrip("：:") in LABEL_WORDS or text.endswith(("：", ":")):
        return True
    return False


def describe(kind: str, attrs: dict, number: str = "", owner: str = "", valid_until: str = "") -> str:
    """把结构化字段整理成一段可直接粘贴的文字，值只来自库内字段。"""
    values = dict(attrs or {})
    if number and "number" in allowed_fields(kind) and not values.get("number"):
        values["number"] = number
    if owner and kind == "people" and not values.get("name"):
        values["name"] = owner
    if valid_until and valid_until != "长期" and "validUntil" in allowed_fields(kind):
        values.setdefault("validUntil", valid_until)
    parts = [f"{label}：{values[key]}" for key, label in allowed_fields(kind).items() if values.get(key)]
    return "；".join(parts)


def looks_like_person_name(name: str) -> bool:
    text = re.sub(r"\s+", "", name or "")
    if text in LABEL_WORDS:
        return False
    return bool(re.fullmatch(r"[\u4e00-\u9fa5·]{2,5}|[A-Za-z.·]{3,30}", text))
