"""青天大模型规则目录。

数值与清单来源：
- 《青天大模型AI评审规则 v1.1》：五维权重、查重红线、一票否决要点、商务自查、技术标评分模块、高分十条
- 《青天大模型AI识别虚词表 v1.0》：六类虚词、高危句式、改写对照、虚词自查五规则

跨投标人围串标比对不在本投标方系统范围内。跨项目阈值用于本企业历史标书 / 知识库查重，不伪造其他投标人比对结果。
"""

FILLER_WORDS = [
    # 一类：万能动词
    {"category": "一类：万能动词", "level": "高危", "word": "加强", "rewrite": "改为「增加X人」「配置X设备」「每周X次检查」"},
    {"category": "一类：万能动词", "level": "高危", "word": "确保", "rewrite": "改为「验收合格率≥98%」「实测实量X项」"},
    {"category": "一类：万能动词", "level": "高危", "word": "狠抓", "rewrite": "直接删除，写具体管控动作"},
    {"category": "一类：万能动词", "level": "高危", "word": "严抓", "rewrite": "直接删除，写具体管控动作"},
    {"category": "一类：万能动词", "level": "高危", "word": "重视", "rewrite": "删除，写「落实三级交底」「每周专项检查」"},
    {"category": "一类：万能动词", "level": "高危", "word": "高度重视", "rewrite": "删除，写「落实三级交底」「每周专项检查」"},
    {"category": "一类：万能动词", "level": "高危", "word": "强化", "rewrite": "改为「由X人专职负责」「每日X次巡检」"},
    {"category": "一类：万能动词", "level": "中危", "word": "落实", "rewrite": "写「由XX部牵头，X月X日前完成」"},
    {"category": "一类：万能动词", "level": "中危", "word": "贯彻", "rewrite": "删除或写具体执行动作"},
    {"category": "一类：万能动词", "level": "中危", "word": "推进", "rewrite": "写「X月底完成XX」「分X阶段实施」"},
    {"category": "一类：万能动词", "level": "中危", "word": "深化", "rewrite": "写「X月底完成XX」「分X阶段实施」"},
    {"category": "一类：万能动词", "level": "中危", "word": "提升", "rewrite": "写「较上季度提升X%」「优化后节省X天」"},
    {"category": "一类：万能动词", "level": "中危", "word": "优化", "rewrite": "写「较上季度提升X%」「优化后节省X天」"},
    {"category": "一类：万能动词", "level": "中危", "word": "完善", "rewrite": "写「补充X项制度」「增加X个控制点」"},
    # 二类：空洞形容词
    {"category": "二类：空洞形容词", "level": "高危", "word": "科学安排", "rewrite": "写「分段流水施工，节拍7天，6天/层」"},
    {"category": "二类：空洞形容词", "level": "高危", "word": "科学管理", "rewrite": "写「分段流水施工，节拍7天，6天/层」"},
    {"category": "二类：空洞形容词", "level": "高危", "word": "合理调配", "rewrite": "写「高峰期300人，宿舍≥600㎡」"},
    {"category": "二类：空洞形容词", "level": "高危", "word": "合理布局", "rewrite": "写「高峰期300人，宿舍≥600㎡」"},
    {"category": "二类：空洞形容词", "level": "高危", "word": "完善体系", "rewrite": "列出制度名称、责任人、运行频次"},
    {"category": "二类：空洞形容词", "level": "高危", "word": "完善制度", "rewrite": "列出制度名称、责任人、运行频次"},
    {"category": "二类：空洞形容词", "level": "高危", "word": "充分准备", "rewrite": "写「提前X天备料，储备X%余量」"},
    {"category": "二类：空洞形容词", "level": "高危", "word": "充分考虑", "rewrite": "写「提前X天备料，储备X%余量」"},
    {"category": "二类：空洞形容词", "level": "中危", "word": "先进工艺", "rewrite": "写「采用铝合金模板+爬架工艺」"},
    {"category": "二类：空洞形容词", "level": "中危", "word": "先进技术", "rewrite": "写「采用铝合金模板+爬架工艺」"},
    {"category": "二类：空洞形容词", "level": "中危", "word": "优质服务", "rewrite": "写「2小时到场、24小时修复」"},
    {"category": "二类：空洞形容词", "level": "中危", "word": "优质材料", "rewrite": "写「2小时到场、24小时修复」"},
    {"category": "二类：空洞形容词", "level": "中危", "word": "良好信誉", "rewrite": "附信用评级、获奖证书、业绩数据"},
    {"category": "二类：空洞形容词", "level": "中危", "word": "良好状态", "rewrite": "附信用评级、获奖证书、业绩数据"},
    {"category": "二类：空洞形容词", "level": "中危", "word": "全面检查", "rewrite": "写「覆盖X个分项、X个检验批」"},
    {"category": "二类：空洞形容词", "level": "中危", "word": "全面覆盖", "rewrite": "写「覆盖X个分项、X个检验批」"},
    {"category": "二类：空洞形容词", "level": "中危", "word": "系统管理", "rewrite": "列出模块、频次、考核方式"},
    {"category": "二类：空洞形容词", "level": "中危", "word": "系统培训", "rewrite": "列出模块、频次、考核方式"},
    {"category": "二类：空洞形容词", "level": "中危", "word": "有效管控", "rewrite": "写「整改率100%，复检合格率≥99%」"},
    {"category": "二类：空洞形容词", "level": "中危", "word": "有效处理", "rewrite": "写「整改率100%，复检合格率≥99%」"},
    {"category": "二类：空洞形容词", "level": "中危", "word": "深入调研", "rewrite": "写「排查X项风险源，形成X份台账」"},
    {"category": "二类：空洞形容词", "level": "中危", "word": "深入排查", "rewrite": "写「排查X项风险源，形成X份台账」"},
    {"category": "二类：空洞形容词", "level": "中危", "word": "显著提升", "rewrite": "写「工期缩短X天，成本降低X%」"},
    {"category": "二类：空洞形容词", "level": "中危", "word": "显著改善", "rewrite": "写「工期缩短X天，成本降低X%」"},
    # 三类：承诺套话
    {"category": "三类：承诺套话", "level": "高危", "word": "高效团队", "rewrite": "写「配X名售后工程师，X小时响应」"},
    {"category": "三类：承诺套话", "level": "高危", "word": "保质保量", "rewrite": "写「X年X月X日前竣工，一次验收合格」"},
    {"category": "三类：承诺套话", "level": "高危", "word": "保质保量按时完成", "rewrite": "写「X年X月X日前竣工，一次验收合格」"},
    {"category": "三类：承诺套话", "level": "高危", "word": "万无一失", "rewrite": "写「设置X道复核工序，双人复核」"},
    {"category": "三类：承诺套话", "level": "高危", "word": "绝无差错", "rewrite": "写「设置X道复核工序，双人复核」"},
    {"category": "三类：承诺套话", "level": "高危", "word": "全力以赴", "rewrite": "写「投入X个班组共X人，倒排工期」"},
    {"category": "三类：承诺套话", "level": "高危", "word": "精心组织", "rewrite": "写「投入X个班组共X人，倒排工期」"},
    {"category": "三类：承诺套话", "level": "高危", "word": "周密部署", "rewrite": "写「分X阶段实施，X月X日节点控制」"},
    {"category": "三类：承诺套话", "level": "中危", "word": "严格把关", "rewrite": "写「三级审核：编制→技术负责人→项目经理」"},
    {"category": "三类：承诺套话", "level": "中危", "word": "层层审核", "rewrite": "写「三级审核：编制→技术负责人→项目经理」"},
    {"category": "三类：承诺套话", "level": "中危", "word": "常抓不懈", "rewrite": "写「每周一安全例会，每月X次专项检查」"},
    {"category": "三类：承诺套话", "level": "中危", "word": "持之以恒", "rewrite": "写「每周一安全例会，每月X次专项检查」"},
    {"category": "三类：承诺套话", "level": "中危", "word": "切实抓好", "rewrite": "写「由安全总监牵头，每日班前教育」"},
    {"category": "三类：承诺套话", "level": "中危", "word": "认真落实", "rewrite": "写「由安全总监牵头，每日班前教育」"},
    {"category": "三类：承诺套话", "level": "中危", "word": "以人为本", "rewrite": "写「夏季调整作业时间，配防暑物资X项」"},
    {"category": "三类：承诺套话", "level": "中危", "word": "顾客至上", "rewrite": "写「夏季调整作业时间，配防暑物资X项」"},
    {"category": "三类：承诺套话", "level": "中危", "word": "时间就是生命", "rewrite": "删除，替换为具体制度和数据"},
    {"category": "三类：承诺套话", "level": "中危", "word": "安全第一", "rewrite": "删除，替换为具体制度和数据"},
    # 四类：无量化副词
    {"category": "四类：无量化副词", "level": "高危", "word": "大力", "rewrite": "删除，写「投入X万元」「新增X台设备」"},
    {"category": "四类：无量化副词", "level": "高危", "word": "高度", "rewrite": "删除，写具体措施"},
    {"category": "四类：无量化副词", "level": "高危", "word": "切实", "rewrite": "删除，写「X月X日前完成」"},
    {"category": "四类：无量化副词", "level": "中危", "word": "深入", "rewrite": "写「排查X项」「走访X次」"},
    {"category": "四类：无量化副词", "level": "中危", "word": "全面", "rewrite": "写「覆盖X个点位」"},
    {"category": "四类：无量化副词", "level": "中危", "word": "积极", "rewrite": "删除，写具体动作"},
    {"category": "四类：无量化副词", "level": "中危", "word": "主动", "rewrite": "写「提前X天介入」「X小时内响应」"},
    {"category": "四类：无量化副词", "level": "中危", "word": "及时", "rewrite": "写「X小时内处理」「当日内回复」"},
    {"category": "四类：无量化副词", "level": "中危", "word": "充分", "rewrite": "写「储备X%」「准备X项」"},
    {"category": "四类：无量化副词", "level": "中危", "word": "严格", "rewrite": "写「按GB50204-2015第X.X.X条执行」"},
    # 五类：连接废话与模板句
    {"category": "五类：连接废话与模板句", "level": "中危", "word": "综上所述", "rewrite": "删除，直接进入结论"},
    {"category": "五类：连接废话与模板句", "level": "中危", "word": "总而言之", "rewrite": "删除，直接进入结论"},
    {"category": "五类：连接废话与模板句", "level": "中危", "word": "众所周知", "rewrite": "删除"},
    {"category": "五类：连接废话与模板句", "level": "中危", "word": "毋庸置疑", "rewrite": "删除"},
    {"category": "五类：连接废话与模板句", "level": "中危", "word": "不难看出", "rewrite": "删除"},
    {"category": "五类：连接废话与模板句", "level": "中危", "word": "我们可以说", "rewrite": "删除"},
    {"category": "五类：连接废话与模板句", "level": "中危", "word": "正所谓", "rewrite": "删除，除非引用规范条文"},
    {"category": "五类：连接废话与模板句", "level": "中危", "word": "常言道", "rewrite": "删除，除非引用规范条文"},
    {"category": "五类：连接废话与模板句", "level": "中危", "word": "的领导下", "rewrite": "删除公文模板句"},
    {"category": "五类：连接废话与模板句", "level": "高危", "word": "随着", "rewrite": "删除网络范文开头，直接写本项目内容"},
    {"category": "五类：连接废话与模板句", "level": "高危", "word": "为了积极响应", "rewrite": "删除模板句"},
    {"category": "五类：连接废话与模板句", "level": "低危", "word": "在百忙之中", "rewrite": "删除客套话"},
    {"category": "五类：连接废话与模板句", "level": "低危", "word": "不辞辛劳", "rewrite": "删除客套话"},
    {"category": "五类：连接废话与模板句", "level": "低危", "word": "我们坚信", "rewrite": "删除，用数据证明"},
    {"category": "五类：连接废话与模板句", "level": "低危", "word": "我们有信心", "rewrite": "删除，用数据证明"},
    {"category": "五类：连接废话与模板句", "level": "低危", "word": "下一步", "rewrite": "写「X月X日前完成XX」"},
    {"category": "五类：连接废话与模板句", "level": "低危", "word": "后续将", "rewrite": "写「X月X日前完成XX」"},
    # 六类：口号标语类
    {"category": "六类：口号标语类", "level": "高危", "word": "安全第一，预防为主", "rewrite": "写「危大工程X项，每项配专项方案+专家论证」"},
    {"category": "六类：口号标语类", "level": "高危", "word": "质量是企业的生命", "rewrite": "写「三检制+样板引路，实测实量合格率≥98%」"},
    {"category": "六类：口号标语类", "level": "高危", "word": "用户至上，诚信为本", "rewrite": "写「售后2小时到场，24小时解决」"},
    {"category": "六类：口号标语类", "level": "高危", "word": "精心施工，铸造精品", "rewrite": "写「分项工程一次验收合格率100%」"},
    {"category": "六类：口号标语类", "level": "中危", "word": "绿色施工，保护环境", "rewrite": "写「扬尘6个100%，雾炮机覆盖半径X米」"},
    {"category": "六类：口号标语类", "level": "中危", "word": "文明施工，和谐共建", "rewrite": "写「围挡公益广告X幅，渣土运输路线报备」"},
]


def _categories_from_words() -> list[dict]:
    groups: dict[str, dict] = {}
    for item in FILLER_WORDS:
        cat = item["category"]
        if cat not in groups:
            groups[cat] = {"category": cat, "level": item["level"], "words": []}
        if item["word"] not in groups[cat]["words"]:
            groups[cat]["words"].append(item["word"])
    return list(groups.values())


FILLER_WORD_CATEGORIES = _categories_from_words()

HIGH_RISK_SENTENCE_PATTERNS = [
    r"加强\S{0,8}管理[，,].{0,8}确保\S{0,8}(安全|质量)",
    r"高度重视\S{0,8}工作[，,].{0,8}全面加强\S{0,8}建设",
    r"科学安排施工进度[，,]合理组织劳动力",
    r"严格按照国家规范和相关标准施工",
    r"根据工程实际情况[，,]采取有效措施",
    r"在施工过程中[，,]我们[将会]?",
    r"建立健全\S{0,8}体系[，,]完善\S{0,8}制度",
    r"采用先进施工工艺[，,]保证工程质量",
    r"认真做好各项准备工作",
    r"加大投入力度[，,]确保工期",
]

FILLER_SELF_CHECK_RULES = [
    "数字规则：段落中至少出现 1 个数字（数量、时间、频率、百分比、尺寸、规范号）",
    "动作规则：动词必须是可执行动作（配置、安装、检查、验收、培训），而不是态度（加强、重视、确保）",
    "对象规则：每项措施必须有明确对象（谁来做、做什么、对什么做）",
    "验证规则：每项承诺必须有验证方式（验收标准、检查频次、整改时限、复检方法）",
    "密度规则：全文虚词密度不超过 5%，每页至少 1 个数据或图表支撑",
]

DEFAULT_WEIGHTS = {
    "completeness": 30,
    "relevance": 25,
    "compliance": 20,
    "feasibility": 15,
    "standardization": 10,
}

# 软件服务类：评分更看重需求逐条响应和方案可落地（功能点、SLA、交付周期），规范性权重低于工程类
SW_DEFAULT_WEIGHTS = {
    "completeness": 25,
    "relevance": 30,
    "compliance": 20,
    "feasibility": 17,
    "standardization": 8,
}

DIMENSION_LABELS = {
    "completeness": "完整性",
    "relevance": "针对性",
    "compliance": "合规性",
    "feasibility": "可落地性",
    "standardization": "规范性",
}

DIMENSION_RUBRIC = {
    "completeness": {
        "focus": "逐条对照招标文件评分目录，核对章节、附表、附图、承诺书、资质资料是否齐全",
        "penalty": "缺一项该小项直接 0 分；自动生成缺项清单",
    },
    "relevance": {
        "focus": "识别通用空话、万能模板；校验是否匹配本项目地点、规模、地质、工期、现场工况",
        "penalty": "全文模板相似度>42%→技术标整体降档；重难点/四新查重>40%→小节清零",
    },
    "compliance": {
        "focus": "自动匹配现行强条规范；施工工艺、安全、扬尘、危大工程方案审查（临边防护 1.2m、扫地杆≤20cm 等属地细节）",
        "penalty": "违规标准注低分；严重违规触发否决投标提示",
    },
    "feasibility": {
        "focus": "过滤完善、充分、合理等无量化虚词；优先采信带具体工期、人员数量、设备型号、工程量测算、闭环管控流程的表述",
        "penalty": "无量化数据/图表/台账=空话不得分",
    },
    "standardization": {
        "focus": "三级标题编号、目录页码、图表索引、PDF 识别清晰度、排版统一度、查重检测",
        "penalty": "乱码、图片 PDF 无法识别、目录错位、暗标违规扣分",
    },
}

THRESHOLD_CATALOG = [
    {
        "key": "filler_density_safe",
        "label": "虚词密度安全线",
        "value": 5,
        "unit": "%",
        "description": "大模型判定的措施章空话占比参考线；超过则由专项检查「虚词密度」提示。虚词表只作参考，不用于两文件查重",
    },
    {
        "key": "full_text_similarity_safe",
        "label": "全文模板相似度安全线",
        "value": 30,
        "unit": "%",
        "description": "v1.1 查重红线：两份技术标整体相似度应 ≤30%；仅「查重分析」页使用",
    },
    {
        "key": "full_text_similarity_risk",
        "label": "全文模板相似度风险线",
        "value": 42,
        "unit": "%",
        "description": "超过则两份技术标整体按降档处理；仅「查重分析」页使用",
    },
    {
        "key": "key_section_similarity_safe",
        "label": "重难点/四新专项查重安全线",
        "value": 20,
        "unit": "%",
        "description": "重难点、四新等专项章节相似度应 ≤20%；仅「查重分析」页使用",
    },
    {
        "key": "key_section_similarity_risk",
        "label": "重难点/四新专项查重风险线",
        "value": 40,
        "unit": "%",
        "description": "超过则该小节清零；仅「查重分析」页使用",
    },
    {
        "key": "cross_bidder_paragraph_risk",
        "label": "本企业跨项目段落雷同风险线",
        "value": 60,
        "unit": "%",
        "description": "两份技术标段落相似度超过该值时标记；仅「查重分析」页使用，不比对其他投标人",
    },
    {
        "key": "cross_bidder_whole_risk",
        "label": "本企业跨项目整体雷同风险线",
        "value": 80,
        "unit": "%",
        "description": "两份技术标全文相似度超过该值时标记；仅「查重分析」页使用，不比对其他投标人",
    },
    {
        "key": "asset_liability_ratio_max",
        "label": "资产负债率上限",
        "value": 85,
        "unit": "%",
        "description": "超过该比例由专项检查「资产负债率」标记；若评标尺子另有上限则尺子优先。不用于两文件查重",
    },
    {
        "key": "price_deviation_ok",
        "label": "报价偏离正常区间",
        "value": 5,
        "unit": "%",
        "description": "相对评标基准价偏离 ±该值内视为正常；由专项检查「报价偏离」判定（E2）",
    },
    {
        "key": "price_deviation_warn",
        "label": "报价偏离预警区间",
        "value": 10,
        "unit": "%",
        "description": "相对基准价偏离超过该值触发异常价预警；由专项检查「报价偏离」判定（E2）",
    },
    {
        "key": "price_deviation_malicious",
        "label": "恶意低价废标线",
        "value": 20,
        "unit": "%",
        "description": "报价低于基准价该比例以上且无成本说明时废标；由专项检查「报价偏离」判定（E1）",
    },
    {
        "key": "qty_deviation_ok",
        "label": "工程量总量偏差阈值",
        "value": 5,
        "unit": "%",
        "description": "清单与施组同类同单位汇总偏差超过该值扣分；由技术评分「工程量逻辑匹配」判定",
    },
    {
        "key": "qty_material_mismatch",
        "label": "主材严重不匹配倍数",
        "value": 2,
        "unit": "倍",
        "description": "采购计划与清单推算主材相差达到该倍数记方案前后矛盾；无采购计划则跳过本条",
    },
    {
        "key": "excavator_m3_per_shift",
        "label": "挖机默认台班产量",
        "value": 400,
        "unit": "m³",
        "description": "标书未写台班产量时按该值估算土方产能；问题项会写明假设",
    },
]

THRESHOLDS = {item["key"]: item["value"] for item in THRESHOLD_CATALOG}

VETO_CHECK_POINTS = [
    {
        "key": "file_form",
        "category": "文件形态",
        "point": "格式、目录、页码、加密、上传格式符合招标要求；无空白页、乱码、错页、漏页；不使用纯图片扫描 PDF",
        "items": [
            "格式、目录、页码符合招标要求",
            "无空白页、乱码、错页、漏页",
            "不使用纯图片扫描 PDF",
            "文件未加密、可正常打开",
        ],
        "wiredItems": [
            "无空白页、乱码、错页、漏页",
            "不使用纯图片扫描 PDF",
            "文件未加密、可正常打开",
        ],
        "wired": "部分接入",
        "wiredNote": "L5 检查空白页、目录域、修订痕迹、批注、加密/损坏文件与纯图片扫描 PDF",
        "engine": "e5_layout",
    },
    {
        "key": "qualification",
        "category": "资质证书",
        "point": "营业执照、资质证书、安全生产许可证、人员证书有效期/等级/专业匹配",
        "items": [
            "营业执照在有效期内",
            "企业资质证书等级/专业匹配",
            "安全生产许可证在有效期内",
            "人员证书有效期与专业匹配",
        ],
        "wiredItems": [
            "营业执照在有效期内",
            "安全生产许可证在有效期内",
        ],
        "wired": "部分接入",
        "wiredNote": "E1 对照正文与证件原图：看图模型识读证号/有效期，过期废标；扫描件短边低于 400 像素或 dpi 过低记无法识别风险。不查询国家资质证照库，专业对口仍需人工确认",
        "engine": "e1_veto",
    },
    {
        "key": "personnel",
        "category": "人员核查",
        "point": "项目经理注册单位、安考证、社保一致；无在建承诺；安全员、八大员社保证书齐全",
        "items": [
            "项目经理注册单位与投标人一致",
            "安考证与社保缴纳单位一致",
            "无在建项目任职承诺",
            "安全员、八大员社保证明齐全",
        ],
        "wiredItems": [
            "项目经理注册单位与投标人一致",
        ],
        "wired": "部分接入",
        "wiredNote": "E1 对照投标书正文人员/社保表述是否附证书编号或社保证明；不查询资质证照库，不联网社保局",
        "engine": "e1_veto",
    },
    {
        "key": "collusion",
        "category": "串标痕迹",
        "point": "不与其他投标人共享制作环境；本系统核验本企业文件哈希与历史标书雷同，不伪造其他投标人围串标",
        "items": [
            "不与其他投标人共用制作环境",
            "本企业已归档投标文件 MD5 撞库",
            "不比对其他公司未公开的投标文件",
        ],
        "wired": "接入判定",
        "wiredNote": "E1 对本企业其他项目投标文件做 MD5 撞库与长句比对；明确不伪造跨投标人围串标结果",
        "engine": "e1_veto",
    },
    {
        "key": "content_match",
        "category": "内容合规",
        "point": "不出现其他项目名称、其他地区名称、其他招标人名称等错配",
        "items": [
            "不得出现其他项目名称",
            "不得出现其他地区名称",
            "不得出现其他招标人名称",
        ],
        "wired": "接入判定",
        "wiredNote": "E1 扫描本企业其他项目名称是否串入当前投标文件",
        "engine": "e1_veto",
    },
    {
        "key": "bid_elements",
        "category": "投标要素",
        "point": "投标有效期、保证金、签字盖章、骑缝章、法人授权书按招标文件完成。身份残留改由暗标规则判定",
        "items": [
            "投标有效期满足招标天数",
            "投标保证金按招标要求提交",
            "签字盖章、骑缝章、法人授权书已实质完成",
        ],
        "wiredItems": [
            "投标有效期满足招标天数",
            "投标保证金按招标要求提交",
            "签字盖章、骑缝章、法人授权书已实质完成",
        ],
        "wired": "部分接入",
        "wiredNote": "E1 检查投标书有效期天数、签章占位符、保证金关键词。单位名称是否写入技术暗标由「暗标规则」单独判定。",
        "engine": "e1_veto",
    },
    {
        "key": "price",
        "category": "报价",
        "point": "无漏项、无负数、无异常畸高畸低；暂列金额按招标文件固定填写",
        "items": [
            "报价不得为负数",
            "报价不得漏项、不得留空占位",
            "不得超过招标预算上限",
            "暂列金额按招标文件固定填写",
        ],
        "wired": "接入判定",
        "wiredNote": "E1 废标：负数、漏项占位、超预算、暂列金额与固定值不符。相对评标基准价偏离由专项检查「报价偏离」单独判定，不在本项重复。",
        "engine": "e1_veto",
    },
    {
        "key": "star_clause",
        "category": "星号条款",
        "point": "招标文件标记*的实质性条款全部响应，任何一条不响应即废标",
        "items": [
            "星号条款全部响应",
            "废标条款全部响应",
            "任何一条实质性不响应即废标",
        ],
        "wired": "接入判定",
        "wiredNote": "招标解析完成后（锁定优先，否则用最新一轮已完成解析），E1 按 mustRespond 检索星号/废标条款，未检出即废标；实质性条款未响应记降档",
        "engine": "e1_veto",
    },
]

BUSINESS_CHECK_POINTS = [
    {
        "key": "performance",
        "category": "企业类似业绩",
        "point": "数量、规模、时间、合同、验收证明齐全；合同+中标通知书+竣工验收报告+官网截图四件套齐全",
        "items": [
            "业绩数量、规模、时间齐全",
            "合同原件或复印件",
            "中标通知书",
            "竣工验收报告",
            "招标官网中标公示截图",
        ],
        "wiredItems": [
            "业绩数量、规模、时间齐全",
            "合同原件或复印件",
            "中标通知书",
            "竣工验收报告",
            "招标官网中标公示截图",
        ],
        "wired": "部分接入",
        "wiredNote": "E2 在正文出现「业绩」等关键词时核验四件套关键词，并检查该业绩是否附带数量/规模/时间量化数字；数据真实性仍需人工核对",
        "engine": "e2_business",
    },
    {
        "key": "finance",
        "category": "财务指标",
        "point": "近三年营收、现金流、审计报告完整清晰，数据前后一致",
        "items": ["近三年营收可核验", "现金流与审计报告完整", "数据前后一致"],
        "wiredItems": ["近三年营收可核验", "现金流与审计报告完整"],
        "wired": "部分接入",
        "wiredNote": "E2 在涉及财务指标时核验营收/现金流/审计报告关键词完整性。资产负债率上限由专项检查单独判定，不在本项重复。数据真实性不联网核验",
        "engine": "e2_business",
    },
    {
        "key": "honor",
        "category": "荣誉认证",
        "point": "企业荣誉、奖项、ISO 体系认证按要求附有效期内证书",
        "items": ["荣誉奖项按招标要求附证", "ISO 体系认证在有效期内"],
        "wiredItems": ["荣誉奖项按招标要求附证", "ISO 体系认证在有效期内"],
        "wired": "部分接入",
        "wiredNote": "E2 对照投标书正文是否写到荣誉/ISO 并附证书编号或有效期；不查询资质证照库，不联网颁证机构核实真伪",
        "engine": "e2_business",
    },
    {
        "key": "localization",
        "category": "本地化服务",
        "point": "本地分支机构、售后网点、备品备件库、应急响应方案",
        "items": ["本地分支机构", "售后网点", "备品备件库", "应急响应方案"],
        "wiredItems": ["本地分支机构", "售后网点", "备品备件库", "应急响应方案"],
        "wired": "部分接入",
        "wiredNote": "E2 在正文写到本地化服务时核验分支/网点/备品/应急是否写全",
        "engine": "e2_business",
    },
    {
        "key": "staffing",
        "category": "人员配置",
        "point": "岗位齐全、证书对口、持证人数达标",
        "items": ["岗位齐全", "证书专业对口", "持证人数达标"],
        "wiredItems": ["岗位齐全", "持证人数达标"],
        "wired": "部分接入",
        "wiredNote": "E2 对照投标书正文人员配置是否写到岗位并附证书编号；若招标文件解析出岗位人数要求，再核验正文是否写到该岗位。不查询资质证照库",
        "engine": "e2_business",
    },
    {
        "key": "equipment",
        "category": "设备机械",
        "point": "清单齐全，型号参数数量符合需求，附购置发票或租赁协议",
        "items": ["设备清单齐全", "型号参数数量符合需求", "购置发票或租赁协议"],
        "wiredItems": ["设备清单齐全", "购置发票或租赁协议"],
        "wired": "部分接入",
        "wiredNote": "E2 对照投标书正文设备/机械表述是否附设备清单、型号或发票/租赁协议；若招标文件解析出设备数量要求，再核验正文是否写到该设备。不查询资质证照库",
        "engine": "e2_business",
    },
    {
        "key": "credit",
        "category": "信用记录",
        "point": "信用中国、中国政府采购网无失信，附查询截图",
        "items": ["信用中国无失信", "中国政府采购网无失信", "附查询截图"],
        "wiredItems": ["附查询截图"],
        "wired": "部分接入",
        "wiredNote": "E2 对照投标书正文信用查询表述是否附查询截图或无失信结论；不查询资质证照库，不联网信用中国或政府采购网",
        "engine": "e2_business",
    },
]

TECH_SCORE_MODULES = [
    {
        "key": "org_outline",
        "score": 13,  # 5×13 + 10+10+5+10 = 100，供 AI 预审报告展示「模块名 N 分」
        "module": "施工组织总纲",
        "logic": "工程概况、重难点结合本项目实际；开篇绑定本项目全称+独有特征",
        "category": "施工组织总纲",
        "point": "工程概况、重难点结合本项目实际；开篇绑定本项目全称+独有特征",
        "items": ["开篇写明本项目全称", "重难点结合本项目地点/工期/地质", "避免通用模板开篇"],
        "wired": "接入判定",
        "wiredNote": "E3 语义 Prompt 参考本模块打分，同时 e3_tech_modules 核验技术标开篇是否绑定本项目全称，缺项计入 L3 扣分",
        "engine": "e3_semantic",
    },
    {
        "key": "special_plan",
        "score": 13,
        "module": "专项施工方案",
        "logic": "分部分项方案完整；关键工序、危大工程单独阐述并引用最新规范条文号",
        "category": "专项施工方案",
        "point": "分部分项方案完整；关键工序、危大工程单独阐述并引用最新规范条文号",
        "items": ["分部分项方案完整", "危大工程单独阐述", "引用最新规范条文号"],
        "wired": "接入判定",
        "wiredNote": "E3 语义 Prompt 参考；e3_tech_modules 核验出现危大工程时是否引用规范条文号，缺项计入 L3 扣分；条文号有效性无全国规范库不做核对",
        "engine": "e3_semantic",
    },
    {
        "key": "schedule",
        "score": 13,
        "module": "工期管控",
        "logic": "必须附双代号网络图或横道图，纯文字不认；关键线路清晰",
        "category": "工期管控",
        "point": "必须附双代号网络图或横道图，纯文字不认；关键线路清晰",
        "items": ["双代号网络图或横道图", "关键线路清晰", "纯文字进度描述不得分"],
        "wired": "接入判定",
        "wiredNote": "E3 语义 Prompt 参考；e3_tech_modules 核验出现工期/进度计划时是否含「网络图/横道图」字样，缺项计入 L3 扣分；不解析图片内容确认真为网络图",
        "engine": "e3_semantic",
    },
    {
        "key": "quality",
        "score": 13,
        "module": "质量管理",
        "logic": "质保体系、三级交底、样板引路、验收流程完整；引用具体规范条文号",
        "category": "质量管理",
        "point": "质保体系、三级交底、样板引路、验收流程完整；引用具体规范条文号",
        "items": ["质保体系", "三级交底", "样板引路", "验收流程", "规范条文号"],
        "wired": "接入判定",
        "wiredNote": "E3 语义 Prompt 参考；e3_tech_modules 核验三级交底/样板引路/验收流程要素完整性，缺 2 项以上计入 L3 扣分",
        "engine": "e3_semantic",
    },
    {
        "key": "safety",
        "score": 13,
        "module": "安全文明",
        "logic": "安全责任制、危险源清单、专项防护；属地扬尘六个 100%、临边 1.2m 等细则写入",
        "category": "安全文明",
        "point": "安全责任制、危险源清单、专项防护；属地扬尘六个 100%、临边 1.2m 等细则写入",
        "items": ["安全责任制", "危险源清单", "专项防护", "扬尘六个 100%", "临边防护 1.2m"],
        "wired": "接入判定",
        "wiredNote": "E3 Prompt 含属地细节；E2 在正文已写临边/扬尘主题时核验启用细则包中的量化要求；e3_tech_modules 核验危险源清单与专项防护要素，缺项计入 L3 扣分",
        "engine": "e3_semantic",
    },
    {
        "key": "environment",
        "score": 10,
        "module": "环保水保",
        "logic": "噪声治理、污水固废处理具体；绿色施工四节一环保量化",
        "category": "环保水保",
        "point": "噪声治理、污水固废处理具体；绿色施工四节一环保量化",
        "items": ["噪声治理", "污水固废处理", "四节一环保量化"],
        "wired": "接入判定",
        "wiredNote": "E3 Prompt 参考；e3_tech_modules 核验环保/噪声/污水相关表述是否附量化数值（%/dB/吨），缺项计入 L3 扣分",
        "engine": "e3_semantic",
    },
    {
        "key": "resources",
        "score": 10,
        "module": "资源配置",
        "logic": "劳动力动态曲线、材料采购、机械进退场全部量化，数据可交叉验证",
        "category": "资源配置",
        "point": "劳动力动态曲线、材料采购、机械进退场全部量化，数据可交叉验证",
        "items": ["劳动力动态曲线", "材料采购量化", "机械进退场", "数据可交叉验证"],
        "wired": "接入判定",
        "wiredNote": "E3 关注有无量化；E2 在人数与宿舍面积同时出现时按人均 4㎡ 交叉验算；e3_tech_modules 核验是否检出「劳动力动态曲线」字样，缺项计入 L3 建议项",
        "engine": "e3_semantic",
    },
    {
        "key": "after_sales",
        "score": 5,
        "module": "售后质保",
        "logic": "维修响应时限（2小时到场/24小时修复）、巡检计划、备品备件清单齐全",
        "category": "售后质保",
        "point": "维修响应时限（2小时到场/24小时修复）、巡检计划、备品备件清单齐全",
        "items": ["2小时到场", "24小时修复", "巡检计划", "备品备件清单"],
        "wired": "接入判定",
        "wiredNote": "E3 Prompt 参考；e3_tech_modules 核验售后表述是否含量化响应时限（如「X 小时」），缺项计入 L3 扣分；未核验售后网点真实性",
        "engine": "e3_semantic",
    },
    {
        "key": "qty_logic",
        "score": 10,
        "module": "工程量逻辑匹配",
        "logic": "清单与施组同类同单位总量偏差不超过阈值；主材与采购计划匹配；土方与挖机产能交叉核验",
        "category": "工程量逻辑匹配",
        "point": "清单与施组同类同单位总量偏差不超过阈值；主材与采购计划匹配；土方与挖机产能交叉核验",
        "items": ["清单与施组总量 ±5%", "主材与采购计划匹配", "土方与挖机产能匹配"],
        "wired": "接入判定",
        "wiredNote": "e_qty_logic 从招标清单汇总混凝土/土方/钢筋，大模型只抽标书原文数字后做确定性比对；无清单或无标书对应量记「无法比对」，不视为一致通过。关闭本卡后预审跳过整块",
        "engine": "e_qty_logic",
    },
]

DUP_CHECK_POINTS = [
    {
        "key": "filler_density",
        "category": "虚词密度",
        "point": "措施性章节空话占比不超过参考线（默认 5%），空话句须补数量/对象/频次",
        "items": ["空话占比参考线默认 5%", "由大模型按语义判定", "虚词表仅供参考"],
        "wired": "接入判定",
        "wiredNote": "E4 用大模型阅读原文，统计措施章空话占比；虚词表只进提示词，见词不直接扣分。背景章原则性表述不计入",
        "engine": "e4_duplicate_filler",
    },
    {
        "key": "price_deviation",
        "category": "报价偏离",
        "point": "相对评标基准价：±5% 内正常，超过 10% 预警，超过 20% 且无说明则恶意低价废标",
        "items": ["正常区间默认 ±5%", "预警区间默认 10%", "恶意低价废标线默认 20%"],
        "wired": "接入判定",
        "wiredNote": "L2 按本页数值对基准价偏离扣分/预警；L1 在超过废标线且正文无成本说明时废标。一票否决「报价」只查负数/漏项/超预算，不重复本项。",
        "engine": "e2_business",
    },
    {
        "key": "asset_liability",
        "category": "资产负债率",
        "point": "投标文件中的资产负债率不超过规则页上限（默认 85%），招标评标尺子另有上限时尺子优先",
        "items": ["上限默认 85%", "超过则标记财务风险", "数值在本页下方可改"],
        "wired": "接入判定",
        "wiredNote": "E2 核验正文中的资产负债率是否超过本页上限（评标尺子优先）。商务自查「财务指标」只核验营收/现金流/审计报告完整性，不重复本项。",
        "engine": "e2_business",
    },
    {
        "key": "high_risk_words",
        "category": "高危虚词",
        "point": "措施章中语义空泛、缺数据的表述扣分，并给出应补充的量化改写",
        "items": ["态度词无落地信息", "承诺套话无对象/频次", "虚词表仅供大模型参考"],
        "wired": "接入判定",
        "wiredNote": "E4 大模型阅读投标书原文后点名空话句；虚词表与改写建议只作参考，禁止见词即报",
        "engine": "e4_duplicate_filler",
    },
    {
        "key": "high_risk_sentences",
        "category": "高危模板句",
        "point": "识别「科学安排施工进度，合理组织劳动力」等高危句式",
        "items": ["万能模板句语义判定", "建议注入本项目地点/工期/地质与数据"],
        "wired": "接入判定",
        "wiredNote": "E4 大模型识别万能模板句；内置句式只作参考，有具体数据的句子不报",
        "engine": "e4_duplicate_filler",
    },
    {
        "key": "self_check_five",
        "category": "虚词自查五规则",
        "point": "数字、动作、对象、验证、密度五条，作为技术标语义评审约束",
        "items": list(FILLER_SELF_CHECK_RULES),
        "wiredItems": [
            "密度规则：全文虚词密度不超过 5%，每页至少 1 个数据或图表支撑",
        ],
        "wired": "接入判定",
        "wiredNote": "五规则写入 E4 虚词语义提示词，由大模型对照原文找缺数字/动作/对象/验证的句子",
        "engine": "e4_duplicate_filler",
    },
]

DUP_SIMILARITY_POINTS = [
    {
        "key": "full_text_sim",
        "category": "全文模板查重",
        "point": "两份技术标整体相似度应 ≤30%，超过 42% 按降档处理",
        "items": ["安全线默认 30%", "风险线默认 42%", "通读抽出全文再比"],
        "wired": "接入判定",
        "wiredNote": "仅「查重分析」比对两份上传的技术标；不进入 AI 预审，不比对其他投标人",
        "engine": "e_duplicate_pair",
    },
    {
        "key": "key_section_sim",
        "category": "重难点/四新专项查重",
        "point": "重难点、四新等专项章节相似度应 ≤20%，超过 40% 该小节清零",
        "items": ["安全线默认 20%", "风险线默认 40%", "命中重难点/四新后再比"],
        "wired": "接入判定",
        "wiredNote": "仅「查重分析」对两份文件中带重难点/四新提示的段落比对；两边都没有则本项不适用",
        "engine": "e_duplicate_pair",
    },
    {
        "key": "cross_bidder",
        "category": "本企业跨项目查重",
        "point": "两份文件段落雷同 60%、整体雷同 80% 时标记复用风险",
        "items": ["段落雷同默认 60%", "整体雷同默认 80%", "不比对其他投标人未公开文件"],
        "wired": "接入判定",
        "wiredNote": "仅「查重分析」比对本次上传的两份技术标（本企业跨项目复用场景）；关闭后不再用段落/整体雷同线点灯",
        "engine": "e_duplicate_pair",
    },
]

HIGH_SCORE_STRATEGIES = [
    {
        "key": "checklist_map",
        "category": "清单化对标响应",
        "point": "评分点→标书章节→页码一一映射",
        "items": ["评分点映射章节", "页码可回溯", "缺项可见"],
        "wired": "接入判定",
        "wiredNote": "招标解析抽出的评分细则会注入 E3 提示词，并由约定对照引擎逐条检索投标书；未覆盖的评分点记 L3 扣分",
        "engine": "e3_semantic",
    },
    {
        "key": "quantify",
        "category": "数据代替定性空话",
        "point": "虚词全部替换为可量化表述",
        "items": ["删除加强/确保等态度词", "改为数量、时限、频次、百分比"],
        "wiredItems": ["删除加强/确保等态度词"],
        "wired": "部分接入",
        "wiredNote": "E4 对语义空话给出带数据的改写参考；不自动改写全文",
        "engine": "e4_duplicate_filler",
    },
    {
        "key": "originality",
        "category": "原创度控制红线",
        "point": "全文查重≤30%，重难点章节≤20%",
        "items": ["全文 ≤30%", "重难点 ≤20%"],
        "wiredItems": ["全文 ≤30%", "重难点 ≤20%"],
        "wired": "部分接入",
        "wiredNote": "与「查重阈值」全文/专项查重同一套数字，仅「查重分析」两文件比对使用，不进入 AI 预审",
        "engine": "e_duplicate_pair",
    },
    {
        "key": "local_first",
        "category": "本地化策略优先",
        "point": "本地业绩、本地团队、本地售后列明",
        "items": ["本地业绩", "本地团队", "本地售后"],
        "wiredItems": ["本地售后"],
        "wired": "部分接入",
        "wiredNote": "属地细则包启用后由 E2 核验量化条款；本地业绩真实性未自动核验",
        "engine": "e2_business",
    },
    {
        "key": "structured_layout",
        "category": "严格结构化排版",
        "point": "三级标题 1→1.1→1.1.1，目录自动生成",
        "items": ["标题层级连续", "目录使用自动域", "页码与正文一致"],
        "wiredItems": ["标题层级连续", "目录使用自动域"],
        "wired": "部分接入",
        "wiredNote": "E5 检查标题跳级、目录域、修订痕迹和批注",
        "engine": "e5_layout",
    },
    {
        "key": "data_loop",
        "category": "数据链逻辑闭环",
        "point": "高峰人数与宿舍面积、塔吊覆盖与平面图可交叉验证",
        "items": ["劳动力与临建面积匹配", "机械覆盖与平面图匹配"],
        "wiredItems": ["劳动力与临建面积匹配"],
        "wired": "部分接入",
        "wiredNote": "E2 在高峰人数与宿舍/临建面积同时写出时按人均 4㎡ 交叉验算；塔吊覆盖未自动验算",
        "engine": "e2_business",
    },
    {
        "key": "chart_meta",
        "category": "图表自制规范",
        "point": "清除图片属性中的作者/单位/软件元数据",
        "items": ["清除作者", "清除单位", "清除软件元数据"],
        "wiredItems": ["清除作者"],
        "wired": "部分接入",
        "wiredNote": "E5 检查文档级作者属性；不解析每张图片的 EXIF",
        "engine": "e5_layout",
    },
    {
        "key": "code_cite",
        "category": "规范引用精准",
        "point": "精确到条文号，不使用废止规范",
        "items": ["引用到条文号", "不使用废止规范"],
        "wiredItems": ["引用到条文号"],
        "wired": "部分接入",
        "wiredNote": "E3 Prompt 要求引用条文号；E2 在正文同时出现规范编号与「废止」时提示人工核对。本系统无国家现行规范库",
        "engine": "e2_business",
    },
    {
        "key": "mock_review",
        "category": "模拟 AI 预审",
        "point": "正式投标前自检缺项、查重、格式、逻辑矛盾",
        "items": ["缺项", "查重", "格式", "逻辑矛盾"],
        "wired": "接入判定",
        "wiredNote": "即本系统预审中心 E1–E5；逻辑矛盾依赖 E3 语义，不是形式化证明",
        "engine": "e1_veto",
    },
    {
        "key": "zero_veto",
        "category": "一票否决零容错",
        "point": "资质、人员、社保、签字、盖章、保证金、有效期、报价专人交叉复核",
        "items": ["资质", "人员社保", "签字盖章", "保证金", "有效期", "报价"],
        "wiredItems": ["资质", "签字盖章", "保证金", "有效期", "报价"],
        "wired": "部分接入",
        "wiredNote": "与「一票否决」tab 同一口径：星号/报价/有效期/保证金关键词已接入，人员社保对照投标书正文且不联网社保局",
        "engine": "e1_veto",
    },
]

ANON_CHECK_POINTS = [
    {
        "key": "identity_text",
        "category": "技术标身份残留",
        "point": "技术暗标不得出现单位名称、简称、地址、徽标、公章、人员姓名，以及特有工法、专利、企业文化等能认出投标人的内容",
        "items": ["单位名称与简称", "地址", "徽标与公章", "人员姓名", "特有工法、专利或企业文化"],
        "wiredItems": ["单位名称与简称"],
        "wired": "部分接入",
        "wiredNote": "招标解析标明暗标或盲评后，E5 在技术标正文检索营业执照上的单位名称，并按废标提示。未要求暗标时不判。地址、徽标、公章、人员姓名和工法专利需人工看",
        "engine": "e5_layout",
    },
    {
        "key": "doc_meta",
        "category": "文档属性",
        "point": "清除 Word 作者、单位和最后修改者，避免从文档属性认出投标人",
        "items": ["文档作者属性", "最后修改者", "单位属性"],
        "wiredItems": ["文档作者属性"],
        "wired": "部分接入",
        "wiredNote": "招标要求暗标或盲评时，E5 读取 Word 核心作者属性并按废标提示。未要求暗标时不判。不解析每张图片的 EXIF",
        "engine": "e5_layout",
    },
    {
        "key": "color_mark",
        "category": "颜色与特殊记号",
        "point": "正文和图表使用黑色，不用彩色、底纹、水印、下划线或着重号暗示身份",
        "items": ["正文与图表黑色", "无彩色", "无底纹、水印、下划线或着重号"],
        "wired": "仅对照",
        "wiredNote": "颜色和特殊记号只对照招标文件，不自动废标",
        "engine": "e5_layout",
    },
    {
        "key": "typeface",
        "category": "字体字形",
        "point": "正文使用黑色常规字体，不加粗、不斜体。封面或标题若招标文件另有黑体要求，以招标文件为准",
        "items": ["正文黑色常规", "不加粗", "不斜体"],
        "wiredItems": ["不加粗"],
        "wired": "部分接入",
        "wiredNote": "招标要求暗标或盲评时，E5 发现加粗段落只给建议，不废标。斜体和具体字号需对照招标文件",
        "engine": "e5_layout",
    },
    {
        "key": "header_footer",
        "category": "页眉页脚与页码",
        "point": "技术暗标通常不设页眉、页脚和页码。是否允许，以本项目招标文件为准",
        "items": ["无页眉", "无页脚", "无页码"],
        "wired": "仅对照",
        "wiredNote": "页眉页脚和页码不自动废标，由编制人对照招标文件",
        "engine": "e5_layout",
    },
    {
        "key": "paper_layout",
        "category": "纸张行距页边距",
        "point": "白底 A4。行距、页边距、首行缩进各地要求不同，只按本项目招标文件对照，不套用某一个城市的厘米数",
        "items": ["白底 A4", "行距按招标文件", "页边距与首行缩进按招标文件"],
        "wired": "仅对照",
        "wiredNote": "南充、通辽、锡盟等地的行距和页边距并不相同，这些数值不自动废标",
        "engine": "e5_layout",
    },
    {
        "key": "chart_bw",
        "category": "图表黑白",
        "point": "图表黑白绘制，边框用细实线，图内文字为黑色。不在暗标中重复明标里的品牌规格",
        "items": ["图表黑白", "边框细实线", "不重复明标品牌规格"],
        "wired": "仅对照",
        "wiredNote": "图表颜色和边框不自动识别，需人工对照",
        "engine": "e5_layout",
    },
    {
        "key": "cover_catalog",
        "category": "封面与目录",
        "point": "封面按招标文件的统一格式，不得签字盖章。部分地区规定暗标不编目录、不留空页",
        "items": ["封面无签字盖章", "目录按招标文件", "无空页"],
        "wired": "仅对照",
        "wiredNote": "封面、目录和空页是否允许，以招标文件为准，不自动废标",
        "engine": "e5_layout",
    },
]

RULE_CATALOGS = {
    "business": BUSINESS_CHECK_POINTS,
    "tech": TECH_SCORE_MODULES,
    "dup_check": DUP_CHECK_POINTS,
    "dup_sim": DUP_SIMILARITY_POINTS,
    "strategy": HIGH_SCORE_STRATEGIES,
    "anon": ANON_CHECK_POINTS,
}


def resolve_wired_items(spec: dict) -> list[str]:
    """卡片上高亮的已接入子项：接入判定=全部；部分接入=wiredItems；仅对照=空。"""
    items = [str(x) for x in (spec.get("items") or [])]
    wired = spec.get("wired") or "仅对照"
    explicit = spec.get("wiredItems")
    if isinstance(explicit, list):
        allow = {str(x) for x in explicit}
        return [x for x in items if x in allow]
    if wired == "接入判定":
        return list(items)
    return []


def veto_wired_items(key: str, wired: str, items: list[str]) -> list[str]:
    for spec in VETO_CHECK_POINTS:
        if spec.get("key") == key:
            return resolve_wired_items(spec)
    if wired == "接入判定":
        return list(items)
    return []


def catalog_wired_items(kind: str, key: str, wired: str, items: list[str]) -> list[str]:
    for spec in RULE_CATALOGS.get(kind) or []:
        if spec.get("key") == key:
            return resolve_wired_items(spec)
    if wired == "接入判定":
        return list(items)
    return []

LOCAL_RULE_PACKAGES = [
    {
        "name": "扬尘六个 100% 细则包",
        "region": "合肥/安徽",
        "status": "启用",
        "items": [
            "围挡率 100%",
            "洒水降尘 100%",
            "出入口冲洗 100%",
            "扬尘防治 6 个 100%",
            "雾炮机覆盖半径可核验",
            "渣土运输路线报备",
        ],
    },
    {
        "name": "临边洞口防护细则包",
        "region": "合肥/安徽",
        "status": "启用",
        "items": [
            "临边防护高度 1.2m",
            "扫地杆距地 ≤20cm",
            "洞口盖板固定",
            "安全网兜底",
        ],
    },
]

SEVERITY_PENALTY = {
    "废标": 40,
    "降档": 15,
    "扣分": 8,
    "建议": 3,
}

# ---------------------------------------------------------------------------
# 去分数化：AI 预审报告的各项指标（L1-L5 层级、五维评审、技术评分模块……）不再用
# 数字加权/扣分算出一个 0-100 分，而是直接用问题严重度推出 A/B/C/D 定性等级。
# "模拟评委打分"（e_tender_score.py，对照招标书自带的量化评标办法）不属于这里，继续用数字。
# ---------------------------------------------------------------------------
GRADE_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3}  # 数值越大越差，供"取最差等级"合并用
GRADE_LABEL = {
    "A": "优（仅建议或无问题）",
    "B": "良（存在扣分项）",
    "C": "中（存在降档项）",
    "D": "差（存在废标项）",
}


def grade_from_findings(findings: list[dict] | None) -> str:
    """按问题严重度直接推等级，不做任何加权/扣分算术：
    有废标→D；否则有降档→C；否则有扣分→B；只有建议或没问题→A。
    """
    severities = {f.get("severity") for f in (findings or []) if isinstance(f, dict)}
    if "废标" in severities:
        return "D"
    if "降档" in severities:
        return "C"
    if "扣分" in severities:
        return "B"
    return "A"


def worst_grade(grades: list[str] | None) -> str:
    """多个等级合并取最差的一个（比如多分块结果合并、多层级合并成一个分册结论）。"""
    valid = [g for g in (grades or []) if g in GRADE_ORDER]
    if not valid:
        return "A"
    return max(valid, key=lambda g: GRADE_ORDER[g])


REWRITE_BY_WORD = {item["word"]: item["rewrite"] for item in FILLER_WORDS}

# ---------------------------------------------------------------------------
# 软件服务类标书专用规则目录。
#
# 以上 VETO_CHECK_POINTS / BUSINESS_CHECK_POINTS / TECH_SCORE_MODULES /
# DIMENSION_RUBRIC / HIGH_SCORE_STRATEGIES / LOCAL_RULE_PACKAGES 几乎全部围绕
# 施工类招标书（临边防护、扬尘、工程量、网络图/横道图、建造师/安许证……）。
# 软件/IT 服务类标书走下面这一套独立内容，不混用上面的施工专项条目；
# 字段形状（key/category/point/items/wired/wiredNote/engine）与工程类目录保持一致，
# 便于复用同一套前端卡片与后端 wired-items 工具函数。
# ---------------------------------------------------------------------------

SW_VETO_CHECK_POINTS = [
    {
        "key": "file_form",
        "category": "文件形态",
        "point": "格式、目录、页码、加密、上传格式符合招标要求；无空白页、乱码、错页、漏页；不使用纯图片扫描 PDF",
        "items": [
            "格式、目录、页码符合招标要求",
            "无空白页、乱码、错页、漏页",
            "不使用纯图片扫描 PDF",
            "文件未加密、可正常打开",
        ],
        "wiredItems": [
            "无空白页、乱码、错页、漏页",
            "不使用纯图片扫描 PDF",
            "文件未加密、可正常打开",
        ],
        "wired": "部分接入",
        "wiredNote": "L5 检查空白页、目录域、修订痕迹、批注、加密/损坏文件与纯图片扫描 PDF",
        "engine": "e5_layout",
    },
    {
        "key": "qualification",
        "category": "资质证书",
        "point": "营业执照、软件/信息安全相关资质证书有效期、等级与招标要求匹配",
        "items": [
            "营业执照在有效期内",
            "软件企业认定证书/信息安全服务资质等级匹配",
            "体系认证（ISO9001/ISO27001/CMMI）在有效期内",
        ],
        "wiredItems": [
            "营业执照在有效期内",
        ],
        "wired": "部分接入",
        "wiredNote": "E1 对照正文与证件原图：看图模型识读证号/有效期，过期废标；扫描件短边低于 400 像素或 dpi 过低记无法识别风险。不查询国家资质证照库",
        "engine": "e1_veto",
    },
    {
        "key": "team_quals",
        "category": "人员核查",
        "point": "项目经理/技术负责人资质（PMP、信息系统项目管理师等）与社保一致；无在建/在研其他项目冲突承诺",
        "items": [
            "项目经理/技术负责人证书与投标人一致",
            "证书与社保缴纳单位一致",
            "无同期承担其他项目冲突承诺",
            "核心开发、测试、运维人员名单齐全",
        ],
        "wiredItems": [
            "证书与社保缴纳单位一致",
        ],
        "wired": "部分接入",
        "wiredNote": "E1 对照投标书正文人员/社保表述是否附证书编号或社保证明；不查询资质证照库，不联网社保局",
        "engine": "e1_veto",
    },
    {
        "key": "collusion",
        "category": "串标痕迹",
        "point": "不与其他投标人共享制作环境；本系统核验本企业文件哈希与历史标书雷同，不伪造其他投标人围串标",
        "items": [
            "不与其他投标人共用制作环境",
            "本企业已归档投标文件 MD5 撞库",
            "不比对其他公司未公开的投标文件",
        ],
        "wired": "接入判定",
        "wiredNote": "E1 对本企业其他项目投标文件做 MD5 撞库与长句比对；明确不伪造跨投标人围串标结果",
        "engine": "e1_veto",
    },
    {
        "key": "content_match",
        "category": "内容合规",
        "point": "不出现其他项目名称、其他地区名称、其他招标人名称等错配",
        "items": [
            "不得出现其他项目名称",
            "不得出现其他地区名称",
            "不得出现其他招标人名称",
        ],
        "wired": "接入判定",
        "wiredNote": "E1 扫描本企业其他项目名称是否串入当前投标文件",
        "engine": "e1_veto",
    },
    {
        "key": "bid_elements",
        "category": "投标要素",
        "point": "投标有效期、保证金、签字盖章、骑缝章、法人授权书按招标文件完成。身份残留改由暗标规则判定",
        "items": [
            "投标有效期满足招标天数",
            "投标保证金按招标要求提交",
            "签字盖章、骑缝章、法人授权书已实质完成",
        ],
        "wiredItems": [
            "投标有效期满足招标天数",
            "投标保证金按招标要求提交",
            "签字盖章、骑缝章、法人授权书已实质完成",
        ],
        "wired": "部分接入",
        "wiredNote": "E1 检查投标书有效期天数、签章占位符、保证金关键词。单位名称是否写入技术暗标由「暗标规则」单独判定。",
        "engine": "e1_veto",
    },
    {
        "key": "price",
        "category": "报价",
        "point": "无漏项、无负数；报价含税口径与招标文件一致。缺项或未含税口径不一致，按招标文件约定处理",
        "items": [
            "报价不得为负数",
            "报价不得漏项、不得留空占位",
            "不得超过招标预算上限",
            "含税口径与招标文件一致",
        ],
        "wired": "接入判定",
        "wiredNote": "E1 废标：负数、漏项占位、超预算。含税口径是否一致需对照报价表与招标文件。相对评标基准价偏离由专项检查「报价偏离」单独判定。",
        "engine": "e1_veto",
    },
    {
        "key": "star_clause",
        "category": "星号条款",
        "point": "招标文件标记*或写成实质性条款的要求全部响应，任何一条不响应即按招标约定处理",
        "items": [
            "星号条款全部响应",
            "实质性条款全部响应",
            "任何一条实质性不响应即废标",
        ],
        "wired": "接入判定",
        "wiredNote": "招标解析完成后（锁定优先，否则用最新一轮已完成解析），E1 按 mustRespond 检索星号/废标条款，未检出即废标；实质性条款未响应记降档",
        "engine": "e1_veto",
    },
    {
        "key": "xinchuang_gate",
        "category": "信创硬性要求",
        "point": "招标文件把国产化或信创写成资格条件或星号条款时，未响应即按未响应实质性条款处理",
        "items": ["信创或国产化硬性要求已响应", "操作系统、数据库、芯片适配范围写明"],
        "wired": "接入判定",
        "wiredNote": "与星号条款同一口径：招标解析把信创写成 mustRespond 时，E1 未检出响应即降档或废标。未写成硬性条件时不在本项否决",
        "engine": "e1_veto",
    },
    {
        "key": "negative_deviation",
        "category": "技术负偏离",
        "point": "仅当招标文件写明技术参数负偏离即无效时，未响应或负偏离才按废标处理；只扣分的负偏离不在本项否决",
        "items": ["招标写明负偏离即无效", "实质性技术参数已响应"],
        "wired": "接入判定",
        "wiredNote": "E1 只处理招标解析列入 mustRespond 的实质性条款。招标未写明负偏离即无效时，不把一般参数差异判废标",
        "engine": "e1_veto",
    },
]

SW_BUSINESS_CHECK_POINTS = [
    {
        "key": "performance",
        "category": "企业类似业绩",
        "point": "数量、规模、时间、合同、验收证明齐全；合同+中标通知书+项目验收/上线运行证明+官网截图四件套齐全",
        "items": [
            "业绩数量、规模、时间齐全",
            "合同原件或复印件",
            "中标通知书",
            "项目验收报告/上线运行证明",
            "招标官网中标公示截图",
        ],
        "wiredItems": [
            "业绩数量、规模、时间齐全",
            "合同原件或复印件",
            "中标通知书",
            "项目验收报告/上线运行证明",
            "招标官网中标公示截图",
        ],
        "wired": "部分接入",
        "wiredNote": "E2 在正文出现「业绩」等关键词时核验四件套关键词，并检查该业绩是否附带数量/规模/时间量化数字；数据真实性仍需人工核对",
        "engine": "e2_business",
    },
    {
        "key": "finance",
        "category": "财务指标",
        "point": "近三年营收、现金流、审计报告完整清晰，数据前后一致",
        "items": ["近三年营收可核验", "现金流与审计报告完整", "数据前后一致"],
        "wiredItems": ["近三年营收可核验", "现金流与审计报告完整"],
        "wired": "部分接入",
        "wiredNote": "E2 在涉及财务指标时核验营收/现金流/审计报告关键词完整性。资产负债率上限由专项检查单独判定，不在本项重复。数据真实性不联网核验",
        "engine": "e2_business",
    },
    {
        "key": "honor",
        "category": "荣誉认证",
        "point": "ISO9001、ISO27001、CMMI、ITSS 等体系认证按招标要求附有效期内证书",
        "items": ["ISO9001/ISO27001 在有效期内", "CMMI/ITSS 按招标要求附证"],
        "wiredItems": ["ISO9001/ISO27001 在有效期内", "CMMI/ITSS 按招标要求附证"],
        "wired": "部分接入",
        "wiredNote": "E2 对照投标书正文是否写到荣誉/ISO 并附证书编号或有效期；不查询资质证照库，不联网颁证机构核实真伪",
        "engine": "e2_business",
    },
    {
        "key": "localization",
        "category": "本地化服务",
        "point": "本地技术支持团队、驻场服务、应急响应方案",
        "items": ["本地技术支持团队", "驻场服务", "应急响应方案"],
        "wiredItems": ["本地技术支持团队", "驻场服务", "应急响应方案"],
        "wired": "部分接入",
        "wiredNote": "E2 在正文写到本地化服务时核验技术支持团队/驻场/应急响应是否写全",
        "engine": "e2_business",
    },
    {
        "key": "staffing",
        "category": "人员配置",
        "point": "项目经理具备 PMP 或软考证书，并附社保；架构、开发、测试、运维岗位按招标要求配齐",
        "items": ["项目经理 PMP 或软考", "人员社保证明", "岗位齐全（架构/开发/测试/运维）"],
        "wiredItems": ["项目经理 PMP 或软考", "人员社保证明", "岗位齐全（架构/开发/测试/运维）"],
        "wired": "部分接入",
        "wiredNote": "E2 对照投标书正文人员配置是否写到岗位并附证书编号；若招标文件解析出岗位人数要求，再核验正文是否写到该岗位。不查询资质证照库",
        "engine": "e2_business",
    },
    {
        "key": "dev_env",
        "category": "研发运行环境",
        "point": "开发测试环境、服务器/云资源、软件工具许可证清单齐全，附购置/订阅凭证",
        "items": ["开发测试环境清单齐全", "服务器/云资源规格数量符合需求", "软件工具许可证/订阅凭证"],
        "wiredItems": ["开发测试环境清单齐全", "软件工具许可证/订阅凭证"],
        "wired": "部分接入",
        "wiredNote": "E2 对照投标书正文开发/测试环境、服务器或云资源表述是否附清单、规格或许可证凭证；若招标文件解析出资源数量要求，再核验正文是否写到。不查询资质证照库",
        "engine": "e2_business",
    },
    {
        "key": "copyright_auth",
        "category": "软著与授权",
        "point": "自有软件附软件著作权，代理或集成产品附制造商授权书，授权范围覆盖本次投标",
        "items": ["软件著作权登记号", "制造商授权书", "授权范围覆盖本项目"],
        "wiredItems": ["软件著作权登记号", "制造商授权书"],
        "wired": "部分接入",
        "wiredNote": "E2 在正文写到软著或授权时核验是否出现登记号、授权书等字样。不联网版权中心核验真伪",
        "engine": "e2_business",
    },
    {
        "key": "credit",
        "category": "信用记录",
        "point": "信用中国、中国政府采购网无失信，附查询截图",
        "items": ["信用中国无失信", "中国政府采购网无失信", "附查询截图"],
        "wiredItems": ["附查询截图"],
        "wired": "部分接入",
        "wiredNote": "E2 对照投标书正文信用查询表述是否附查询截图或无失信结论；不查询资质证照库，不联网信用中国或政府采购网",
        "engine": "e2_business",
    },
]

SW_TECH_SCORE_MODULES = [
    {
        "key": "overall_plan",
        "score": 12,
        "module": "需求理解",
        "logic": "需求理解写清本项目业务场景、用户对象和建设边界，开篇绑定本项目全称",
        "category": "需求理解",
        "point": "需求理解写清本项目业务场景、用户对象和建设边界，开篇绑定本项目全称",
        "items": ["开篇写明本项目全称", "业务场景与用户对象写清", "建设边界不照搬通用模板"],
        "wired": "接入判定",
        "wiredNote": "E3 语义 Prompt 参考本模块打分，同时 e3_tech_modules 核验技术标开篇是否绑定本项目全称，缺项计入 L3 扣分",
        "engine": "e3_semantic",
    },
    {
        "key": "architecture",
        "score": 12,
        "module": "架构与技术路线",
        "logic": "必须附系统架构图，技术栈选型需说明理由，并与现有系统集成方案对应",
        "category": "架构与技术路线",
        "point": "必须附系统架构图，技术路线说明选型理由，并与现有系统集成方案对应",
        "items": ["附系统架构图原图", "技术栈选型有理由说明", "与现有系统集成方案对应"],
        "wired": "接入判定",
        "wiredNote": "E3 语义 Prompt 参考；e3_tech_modules 核验正文声称有架构图时附近是否有抽出的原图，缺项计入 L3 扣分；不解析图片内容确认真为架构图",
        "engine": "e3_semantic",
    },
    {
        "key": "function_response",
        "score": 12,
        "module": "功能与接口响应",
        "logic": "功能需求逐条响应，接口清单、数据流向和调用方写清楚，不用“全面满足”代替条目",
        "category": "功能与接口响应",
        "point": "功能需求逐条响应，接口清单、数据流向和调用方写清楚",
        "items": ["功能点逐条响应", "接口清单与调用方", "数据流向写清"],
        "wired": "部分接入",
        "wiredNote": "e3_tech_modules 在正文写到功能或接口时，检查是否同时出现接口、响应或数据流向。不逐条对照招标功能表",
        "engine": "e3_semantic",
    },
    {
        "key": "deployment_plan",
        "score": 10,
        "module": "实施与里程碑",
        "logic": "必须附里程碑计划（甘特图或进度表），上线割接与回退方案清晰",
        "category": "实施与里程碑",
        "point": "必须附里程碑计划（甘特图或进度表），上线割接与回退方案清晰",
        "items": ["里程碑计划（甘特图/进度表）", "上线割接方案", "回退/应急方案"],
        "wired": "接入判定",
        "wiredNote": "E3 语义 Prompt 参考；e3_tech_modules 核验出现工期/里程碑时是否含「甘特图/进度表」字样，缺项计入 L3 扣分；不解析图片内容确认真为甘特图",
        "engine": "e3_semantic",
    },
    {
        "key": "data_security",
        "score": 12,
        "module": "等保与数据安全",
        "logic": "等级保护级别、数据加密、隐私合规、灾备方案具体量化",
        "category": "等保与数据安全",
        "point": "等级保护级别、数据加密、隐私合规、灾备方案具体量化",
        "items": ["等保级别明确", "数据加密方案", "灾备方案（RTO/RPO）"],
        "wired": "接入判定",
        "wiredNote": "E3 Prompt 参考；e3_tech_modules 核验数据安全相关表述是否附量化指标（等保级别/RTO/RPO 等数字），缺项计入 L3 扣分",
        "engine": "e3_semantic",
    },
    {
        "key": "xinchuang",
        "score": 10,
        "module": "信创适配",
        "logic": "按招标要求说明操作系统、数据库、中间件和芯片的适配范围，并附适配或兼容性证据",
        "category": "信创适配",
        "point": "操作系统、数据库、中间件和芯片的适配范围写清，并附适配或兼容性证据",
        "items": ["操作系统与数据库适配", "芯片或整机适配范围", "适配或兼容性证据"],
        "wired": "部分接入",
        "wiredNote": "正文写到信创时，e3_tech_modules 检查是否出现适配、兼容或测试报告。招标未要求信创时不因缺少信创章节扣分",
        "engine": "e3_semantic",
    },
    {
        "key": "testing_acceptance",
        "score": 10,
        "module": "测试与验收方案",
        "logic": "单元/集成/性能/安全测试类型覆盖齐全，验收标准与流程明确",
        "category": "测试与验收方案",
        "point": "单元/集成/性能/安全测试类型覆盖齐全，验收标准与流程明确",
        "items": ["测试类型覆盖齐全", "验收标准明确", "验收流程清晰"],
        "wired": "接入判定",
        "wiredNote": "E3 Prompt 参考；e3_tech_modules 核验测试相关表述是否覆盖多种测试类型（单元/集成/性能/安全），仅泛泛提及「测试」计入 L3 建议项",
        "engine": "e3_semantic",
    },
    {
        "key": "after_sales",
        "score": 12,
        "module": "运维 SLA 与培训",
        "logic": "故障响应时限、可用性 SLA、版本升级与用户培训安排都要写到数字",
        "category": "运维 SLA 与培训",
        "point": "故障响应时限、可用性 SLA、版本升级与用户培训安排都要写到数字",
        "items": ["量化响应时限", "可用性 SLA", "培训计划与升级策略"],
        "wired": "接入判定",
        "wiredNote": "E3 Prompt 参考；e3_tech_modules 核验运维/售后表述是否含量化响应时限（如「X 小时」），缺项计入 L3 扣分；未核验服务网点真实性",
        "engine": "e3_semantic",
    },
    {
        "key": "ip_opensource",
        "score": 10,
        "module": "源码与知识产权",
        "logic": "源代码和文档交付范围明确；开源组件许可证清单齐全，知识产权归属条款明确",
        "category": "源码与知识产权",
        "point": "源代码和文档交付范围明确；开源组件许可证清单齐全，知识产权归属条款明确",
        "items": ["源代码/文档交付范围", "开源组件许可证清单", "知识产权归属条款"],
        "wired": "部分接入",
        "wiredNote": "e3_tech_modules 核验正文提到开源/第三方组件时是否附许可证说明，缺项计入 L3 建议项；不核验许可证真实合规性",
        "engine": "e3_semantic",
    },
]

SW_DIMENSION_RUBRIC = {
    "completeness": {
        "focus": "逐条对照招标文件评分目录，核对章节、附表、附图（架构图/部署图）、承诺书、资质资料是否齐全",
        "penalty": "缺一项该小项直接 0 分；自动生成缺项清单",
    },
    "relevance": {
        "focus": "识别通用空话、万能模板；校验是否匹配本项目业务场景、行业特点、系统规模与集成要求，而非照抄其他行业用语",
        "penalty": "全文模板相似度>42%→技术标整体降档；重难点/核心模块查重>40%→小节清零",
    },
    "compliance": {
        "focus": "自动匹配现行信息技术、网络安全、数据安全相关标准规范（如 GB/T 22239 等级保护、数据安全法合规要求）与软件工程规范",
        "penalty": "违规标准注低分；严重违规（如未达等保要求）触发否决投标提示",
    },
    "feasibility": {
        "focus": "过滤完善、充分、合理等无量化虚词；优先采信带具体工期、人员配置、技术指标、SLA 数字、接口数量的表述",
        "penalty": "无量化数据/图表/台账=空话不得分",
    },
    "standardization": {
        "focus": "三级标题编号、目录页码、图表索引、PDF 识别清晰度、排版统一度、查重检测",
        "penalty": "乱码、图片 PDF 无法识别、目录错位、暗标违规扣分",
    },
}

SW_HIGH_SCORE_STRATEGIES = [
    {
        "key": "checklist_map",
        "category": "清单化对标响应",
        "point": "评分点→标书章节→页码一一映射",
        "items": ["评分点映射章节", "页码可回溯", "缺项可见"],
        "wired": "接入判定",
        "wiredNote": "招标解析抽出的评分细则会注入 E3 提示词，并由约定对照引擎逐条检索投标书；未覆盖的评分点记 L3 扣分",
        "engine": "e3_semantic",
    },
    {
        "key": "quantify",
        "category": "数据代替定性空话",
        "point": "虚词全部替换为可量化表述",
        "items": ["删除加强/确保等态度词", "改为数量、时限、频次、百分比"],
        "wiredItems": ["删除加强/确保等态度词"],
        "wired": "部分接入",
        "wiredNote": "E4 对语义空话给出带数据的改写参考；不自动改写全文",
        "engine": "e4_duplicate_filler",
    },
    {
        "key": "originality",
        "category": "原创度控制红线",
        "point": "全文查重≤30%，核心模块章节≤20%",
        "items": ["全文 ≤30%", "核心模块 ≤20%"],
        "wiredItems": ["全文 ≤30%", "核心模块 ≤20%"],
        "wired": "部分接入",
        "wiredNote": "与「查重阈值」全文/专项查重同一套数字，仅「查重分析」两文件比对使用，不进入 AI 预审",
        "engine": "e_duplicate_pair",
    },
    {
        "key": "local_first",
        "category": "本地化策略优先",
        "point": "本地业绩、本地团队、本地售后列明",
        "items": ["本地业绩", "本地团队", "本地售后"],
        "wiredItems": ["本地售后"],
        "wired": "部分接入",
        "wiredNote": "属地细则包启用后由 E2 核验量化条款；本地业绩真实性未自动核验",
        "engine": "e2_business",
    },
    {
        "key": "structured_layout",
        "category": "严格结构化排版",
        "point": "三级标题 1→1.1→1.1.1，目录自动生成",
        "items": ["标题层级连续", "目录使用自动域", "页码与正文一致"],
        "wiredItems": ["标题层级连续", "目录使用自动域"],
        "wired": "部分接入",
        "wiredNote": "E5 检查标题跳级、目录域、修订痕迹和批注",
        "engine": "e5_layout",
    },
    {
        "key": "interface_consistency",
        "category": "接口与数据链路",
        "point": "接口清单、调用方和数据流向要能对上架构说明，用链路代替空泛架构口号",
        "items": ["接口清单与调用方", "数据流向可追溯", "不用空泛架构口号代替方案"],
        "wired": "仅对照",
        "wiredNote": "接口与数据链路由编制人对照架构说明核验，预审不把口号自动判废标",
        "engine": "e3_semantic",
    },
    {
        "key": "compliance_evidence",
        "category": "等保与信创证据",
        "point": "等保级别、测评或备案材料，以及信创适配范围和证据要写到可核对的名称或编号",
        "items": ["等保级别与测评或备案", "信创适配范围", "适配或兼容性证据"],
        "wiredItems": ["等保级别与测评或备案", "信创适配范围"],
        "wired": "部分接入",
        "wiredNote": "正文写到等保或信创时，技术评分模块检查是否带级别、适配或报告字样。不联网核验证书",
        "engine": "e3_semantic",
    },
    {
        "key": "chart_meta",
        "category": "图表自制规范",
        "point": "清除图片属性中的作者/单位/软件元数据",
        "items": ["清除作者", "清除单位", "清除软件元数据"],
        "wiredItems": ["清除作者"],
        "wired": "部分接入",
        "wiredNote": "E5 检查文档级作者属性；不解析每张图片的 EXIF",
        "engine": "e5_layout",
    },
    {
        "key": "code_cite",
        "category": "规范引用精准",
        "point": "精确到条文号/标准编号，不使用废止规范",
        "items": ["引用到条文号/标准编号", "不使用废止规范"],
        "wiredItems": ["引用到条文号/标准编号"],
        "wired": "部分接入",
        "wiredNote": "E3 Prompt 要求引用条文号/标准编号；E2 在正文同时出现规范编号与「废止」时提示人工核对。本系统无国家现行规范库",
        "engine": "e2_business",
    },
    {
        "key": "mock_review",
        "category": "模拟 AI 预审",
        "point": "正式投标前自检缺项、查重、格式、逻辑矛盾",
        "items": ["缺项", "查重", "格式", "逻辑矛盾"],
        "wired": "接入判定",
        "wiredNote": "即本系统预审中心 E1–E5；逻辑矛盾依赖 E3 语义，不是形式化证明",
        "engine": "e1_veto",
    },
    {
        "key": "zero_veto",
        "category": "一票否决零容错",
        "point": "资质、人员、签字、盖章、保证金、有效期、报价专人交叉复核",
        "items": ["资质", "人员", "签字盖章", "保证金", "有效期", "报价"],
        "wiredItems": ["资质", "签字盖章", "保证金", "有效期", "报价"],
        "wired": "部分接入",
        "wiredNote": "与「一票否决」tab 同一口径：星号/报价/有效期/保证金关键词已接入，人员证书对照投标书正文且不联网核验",
        "engine": "e1_veto",
    },
]

SW_ANON_CHECK_POINTS = [
    {
        "key": "identity_text",
        "category": "技术暗标身份残留",
        "point": "技术暗标分册不得出现单位名称、简称、地址、徽标、公章和人员姓名。商务分册里的资质、业绩、人员证书和软著不算暗标违规",
        "items": ["单位名称与简称", "地址", "徽标与公章", "人员姓名"],
        "wiredItems": ["单位名称与简称"],
        "wired": "部分接入",
        "wiredNote": "招标解析标明暗标或盲评后，E5 在技术分册检索营业执照上的单位名称。商务分册单独预审时，不把资质页上的单位名称判为暗标违规。未要求暗标时不判",
        "engine": "e5_layout",
    },
    {
        "key": "brand_case",
        "category": "品牌、案例与域名",
        "point": "技术暗标分册不得出现可识别的产品品牌、过往案例名称、联系电话和公司域名",
        "items": ["产品品牌", "可识别案例名称", "联系电话", "公司域名"],
        "wiredItems": ["联系电话"],
        "wired": "部分接入",
        "wiredNote": "招标要求暗标或盲评时，E5 在技术分册检索手机号。品牌、案例名称和域名需人工看是否能认出投标人。商务分册中的业绩名称不在本项判违规",
        "engine": "e5_layout",
    },
    {
        "key": "doc_meta",
        "category": "文档属性",
        "point": "清除 Word 作者、单位和最后修改者，避免从文档属性认出投标人",
        "items": ["文档作者属性", "最后修改者", "单位属性"],
        "wiredItems": ["文档作者属性"],
        "wired": "部分接入",
        "wiredNote": "招标要求暗标或盲评时，E5 读取 Word 核心作者属性并按废标提示。未要求暗标时不判",
        "engine": "e5_layout",
    },
    {
        "key": "color_mark",
        "category": "颜色与特殊记号",
        "point": "正文和图表使用黑色，不用彩色、底纹、水印、下划线或着重号暗示身份",
        "items": ["正文与图表黑色", "无彩色", "无底纹、水印、下划线或着重号"],
        "wired": "仅对照",
        "wiredNote": "颜色和特殊记号只对照招标文件，不自动废标",
        "engine": "e5_layout",
    },
    {
        "key": "typeface",
        "category": "字体字形",
        "point": "正文使用黑色常规字体，不加粗、不斜体。封面或标题若招标文件另有黑体要求，以招标文件为准",
        "items": ["正文黑色常规", "不加粗", "不斜体"],
        "wiredItems": ["不加粗"],
        "wired": "部分接入",
        "wiredNote": "招标要求暗标或盲评时，E5 发现加粗段落只给建议，不废标。斜体和具体字号需对照招标文件",
        "engine": "e5_layout",
    },
    {
        "key": "header_footer",
        "category": "页眉页脚与页码",
        "point": "技术暗标通常不设页眉、页脚和页码。是否允许，以本项目招标文件为准",
        "items": ["无页眉", "无页脚", "无页码"],
        "wired": "仅对照",
        "wiredNote": "页眉页脚和页码不自动废标，由编制人对照招标文件",
        "engine": "e5_layout",
    },
    {
        "key": "paper_layout",
        "category": "纸张行距页边距",
        "point": "白底 A4。行距、页边距、首行缩进以本项目招标文件为准，不套用某一个城市的厘米数",
        "items": ["白底 A4", "行距按招标文件", "页边距与首行缩进按招标文件"],
        "wired": "仅对照",
        "wiredNote": "各地行距和页边距并不相同，这些数值不自动废标",
        "engine": "e5_layout",
    },
    {
        "key": "chart_bw",
        "category": "图表黑白",
        "point": "图表黑白绘制，图内文字为黑色，不把可识别的产品界面或品牌图放进技术暗标",
        "items": ["图表黑白", "图内文字黑色", "无产品品牌图"],
        "wired": "仅对照",
        "wiredNote": "图表和产品截图不自动识别，需人工对照",
        "engine": "e5_layout",
    },
    {
        "key": "cover_catalog",
        "category": "封面与目录",
        "point": "封面按招标文件的统一格式，不得签字盖章。目录是否允许，以招标文件为准",
        "items": ["封面无签字盖章", "目录按招标文件", "无空页"],
        "wired": "仅对照",
        "wiredNote": "封面、目录和空页是否允许，以招标文件为准，不自动废标",
        "engine": "e5_layout",
    },
]

SW_RULE_CATALOGS = {
    "business": SW_BUSINESS_CHECK_POINTS,
    "tech": SW_TECH_SCORE_MODULES,
    "strategy": SW_HIGH_SCORE_STRATEGIES,
    "anon": SW_ANON_CHECK_POINTS,
    # 虚词专项检查和查重阈值与工程类口径相同，但单独入库，两类标书各自开关、互不影响。
    "dup_check": DUP_CHECK_POINTS,
    "dup_sim": DUP_SIMILARITY_POINTS,
}


def sw_veto_wired_items(key: str, wired: str, items: list[str]) -> list[str]:
    for spec in SW_VETO_CHECK_POINTS:
        if spec.get("key") == key:
            return resolve_wired_items(spec)
    if wired == "接入判定":
        return list(items)
    return []


def sw_catalog_wired_items(kind: str, key: str, wired: str, items: list[str]) -> list[str]:
    for spec in SW_RULE_CATALOGS.get(kind) or []:
        if spec.get("key") == key:
            return resolve_wired_items(spec)
    if wired == "接入判定":
        return list(items)
    return []


SW_RULE_PACKAGES = [
    {
        "name": "等保测评细则包",
        "region": "行业通用",
        "status": "启用",
        "items": [
            "已完成等级保护测评（按项目要求等级）",
            "测评报告编号可核验",
            "整改项已闭环",
        ],
    },
    {
        "name": "信创适配细则包",
        "region": "行业通用",
        "status": "启用",
        "items": [
            "核心软硬件适配信创名录",
            "国产操作系统/数据库兼容性验证",
            "适配测试报告",
        ],
    },
    {
        "name": "数据出境合规细则包",
        "region": "行业通用",
        "status": "启用",
        "items": [
            "数据出境安全评估/标准合同备案",
            "跨境数据传输清单",
            "合规责任人与联系方式",
        ],
    },
    {
        "name": "源码与知识产权细则包",
        "region": "行业通用",
        "status": "启用",
        "items": [
            "源代码与文档交付范围",
            "知识产权归属条款",
            "软件著作权或制造商授权",
        ],
    },
]

SW_LOCAL_ITEM_CHECKS = [
    {
        "hint": "等保测评报告编号",
        "topic": ("等保", "等级保护"),
        "required": ("测评报告编号", "备案证明", "三级", "二级"),
        "rule": "行业细则-等保测评报告可核验",
        "suggestion": "正文已写等保/等级保护，但未写明测评报告编号或备案证明，请按启用的行业细则补全",
    },
    {
        "hint": "信创适配测试报告",
        "topic": ("信创",),
        "required": ("测试报告", "适配清单", "兼容性验证"),
        "rule": "行业细则-信创适配测试报告",
        "suggestion": "正文已写信创适配，但未写明测试报告或兼容性验证，请按启用的行业细则补全",
    },
    {
        "hint": "数据出境合规说明",
        "topic": ("数据出境", "跨境传输"),
        "required": ("安全评估", "标准合同", "备案"),
        "rule": "行业细则-数据出境合规说明",
        "suggestion": "正文已写数据出境/跨境传输，但未写明安全评估、标准合同或备案情况，请按启用的行业细则补全",
    },
    {
        "hint": "源码交付与知识产权归属",
        "topic": ("源代码", "源码", "知识产权"),
        "required": ("交付", "归属", "著作权"),
        "rule": "行业细则-源码交付与知识产权归属",
        "suggestion": "正文已写源代码或知识产权，但未写明交付范围或权利归属，请按启用的行业细则补全",
    },
]


def rule_scope(key: str) -> dict:
    """青天条目的适用专业。未单列的条目各专业都用。扬尘和临边只对房建、市政。"""
    if key == "safety":
        return {
            "specialties": ["房建", "市政", "水利", "公路"],
            "workTypes": ["通用"],
            "itemSpecialties": {"扬尘六个 100%": ["房建", "市政"], "临边防护 1.2m": ["房建", "市政"]},
        }
    return {"specialties": ["通用"], "workTypes": ["通用"], "itemSpecialties": {}}


def catalog_bundle(is_engineering: bool) -> dict:
    """集中做"工程类常量 vs 软件服务类常量"的选择，避免调用方各自写 if/else。"""
    if is_engineering:
        return {
            "veto": VETO_CHECK_POINTS,
            "business": BUSINESS_CHECK_POINTS,
            "tech": TECH_SCORE_MODULES,
            "strategy": HIGH_SCORE_STRATEGIES,
            "dimension_rubric": DIMENSION_RUBRIC,
            "packages": LOCAL_RULE_PACKAGES,
            "local_item_checks": None,  # None => e2_business 用模块内置的工程类默认值
        }
    return {
        "veto": SW_VETO_CHECK_POINTS,
        "business": SW_BUSINESS_CHECK_POINTS,
        "tech": SW_TECH_SCORE_MODULES,
        "strategy": SW_HIGH_SCORE_STRATEGIES,
        "dimension_rubric": SW_DIMENSION_RUBRIC,
        "packages": SW_RULE_PACKAGES,
        "local_item_checks": SW_LOCAL_ITEM_CHECKS,
    }
