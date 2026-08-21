"""青天大模型规则数据的 Python 常量化落地。

数值来源：
- 《青天大模型AI评审规则 v1.1》：五维默认权重、查重阈值、财务阈值
- 《青天大模型AI识别虚词表 v1.0》：六类虚词清单、高危句式

本阶段（P3 最小闭环）先以常量形式内置，尚未接入 rules/page.tsx 的后端 CRUD，
后续对接规则包管理时，这里的常量应改为从数据库按项目/属地读取。
"""

FILLER_WORD_CATEGORIES = [
    {
        "category": "一类：万能动词",
        "level": "高危",
        "words": ["加强", "确保", "狠抓", "严抓", "重视", "高度重视", "强化", "落实"],
    },
    {
        "category": "二类：空洞形容词",
        "level": "高危",
        "words": [
            "科学安排",
            "合理调配",
            "完善体系",
            "充分准备",
            "先进工艺",
            "优质服务",
            "一流水平",
            "领先地位",
        ],
    },
    {
        "category": "三类：承诺套话",
        "level": "高危",
        "words": [
            "优质服务",
            "高效团队",
            "保质保量",
            "万无一失",
            "绝无差错",
            "全力以赴",
            "精心组织",
            "严格把关",
            "层层审核",
        ],
    },
    {
        "category": "四类：无量化副词",
        "level": "中危",
        "words": ["大力", "高度", "切实", "深入", "全面", "积极", "主动", "及时", "充分", "严格"],
    },
    {
        "category": "五类：连接废话与模板句",
        "level": "中危",
        "words": ["综上所述", "总而言之", "众所周知", "毋庸置疑", "随着", "为了积极响应"],
    },
    {
        "category": "六类：口号标语类",
        "level": "高危",
        "words": [
            "安全第一，预防为主",
            "质量是企业的生命",
            "用户至上，诚信为本",
            "绿色施工，保护环境",
        ],
    },
]

HIGH_RISK_SENTENCE_PATTERNS = [
    r"加强\S{0,6}管理[，,].{0,6}确保\S{0,6}(安全|质量)",
    r"高度重视\S{0,6}工作[，,].{0,6}全面加强\S{0,6}建设",
    r"科学安排施工进度[，,]合理组织劳动力",
    r"严格按照国家规范和相关标准施工",
    r"根据工程实际情况[，,]采取有效措施",
    r"建立健全\S{0,6}体系[，,]完善\S{0,6}制度",
    r"采用先进施工工艺[，,]保证工程质量",
]

DEFAULT_WEIGHTS = {
    "completeness": 30,
    "relevance": 25,
    "compliance": 20,
    "feasibility": 15,
    "standardization": 10,
}

DIMENSION_LABELS = {
    "completeness": "完整性",
    "relevance": "针对性",
    "compliance": "合规性",
    "feasibility": "可落地性",
    "standardization": "规范性",
}

THRESHOLDS = {
    "full_text_similarity_safe": 30,
    "full_text_similarity_risk": 42,
    "key_section_similarity_safe": 20,
    "key_section_similarity_risk": 40,
    "filler_density_safe": 5,
    "asset_liability_ratio_max": 85,
}

SEVERITY_PENALTY = {
    "废标": 40,
    "降档": 15,
    "扣分": 8,
    "建议": 3,
}
