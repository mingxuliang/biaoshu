"""水利工程子类型工艺库。纯数据加判定，只给水利施组的目录和提示用。

每个子类型含工艺清单、重难点候选、监测观测项和验收单元划分。
工艺和重难点都带触发关键词：招标范围里没有出现就不进目录，避免凑数。
"""

from __future__ import annotations

import re

# key -> 子类型定义。
SUBTYPES: dict[str, dict] = {
    "river": {
        "label": "河道治理",
        "pattern": r"河道|清淤|护岸|护坡|疏浚|生态|河长|岸线|防汛道路",
        "works": [
            {
                "title": "护坡护岸施工方法",
                "name": "护坡护岸",
                "pattern": r"护坡|护岸",
                "idea": "基面处理 → 垫层 → 砌筑或安装 → 勾缝或充填 → 验收。每步挂参数，约束用文字表述。",
            },
            {
                "title": "河道清淤施工方法",
                "name": "河道清淤",
                "pattern": r"清淤|疏浚",
                "idea": "围堰截流 → 抽排水 → 干地开挖 → 分段推进 → 余土外运。每步挂一个带单位的参数，并引用依据账里的一条规范编号。",
            },
            {
                "title": "防汛道路施工方法",
                "name": "防汛道路",
                "pattern": r"防汛道路|道路",
                "idea": "路基整形 → 基层 → 面层 → 排水与边坡 → 验收。参数取设计参数账。",
            },
            {
                "title": "堰坝拆建加固施工方法",
                "name": "堰坝拆建加固",
                "pattern": r"堰坝|拆建堰|堰",
                "idea": "按节点账写拆除窗口、基坑、重建和过水验收。天数不得另起一套。",
            },
        ],
        "difficulties": [
            {
                "title": "汛期与清淤窗口冲突",
                "pattern": r"清淤|汛",
                "text": "清淤和堰坝拆建必须落在汛前窗口内，窗口之外不能下河作业。",
            },
        ],
        "monitors": ["河道水位", "岸坡位移", "施工期水质"],
        "acceptance": "单元工程按护岸、清淤、道路分段划分，分部为河道整治，单位工程为本标段。",
    },
    "dike": {
        "label": "堤防防洪",
        "pattern": r"堤防|堤身|防洪墙|防洪堤|圩堤|堤线|搅拌桩|堤顶|防洪",
        "works": [
            {
                "title": "堤身填筑施工方法",
                "name": "堤身填筑",
                "pattern": r"堤身|堤防|填筑|培厚|加高|堤线",
                "idea": "清基 → 分层填筑 → 碾压 → 压实度检测 → 边坡修整。压实度、分层厚度取设计参数账，没有就写【待核实】。",
            },
            {
                "title": "水泥土搅拌桩施工方法",
                "name": "水泥土搅拌桩",
                "pattern": r"搅拌桩|软基|软土|水泥土|地基处理",
                "idea": "桩位放样 → 钻进喷浆搅拌 → 提升复搅 → 桩头处理 → 取芯检测。水泥掺量、桩径、桩长取设计参数账。",
            },
            {
                "title": "防洪墙施工方法",
                "name": "防洪墙",
                "pattern": r"防洪墙|挡墙|翼墙|混凝土墙",
                "idea": "基坑 → 垫层 → 钢筋模板 → 混凝土浇筑 → 伸缩缝止水 → 养护。强度、抗渗、抗冻等级成组写，取设计参数账。",
            },
            {
                "title": "堤顶道路施工方法",
                "name": "堤顶道路",
                "pattern": r"堤顶|防汛道路|道路",
                "idea": "路基整形 → 基层 → 面层 → 排水。参数取设计参数账。",
            },
        ],
        "difficulties": [
            {
                "title": "软土地基处理与沉降控制",
                "pattern": r"搅拌桩|软基|软土|地基处理",
                "text": "堤基为软土时，处理质量和沉降控制决定堤身稳定。",
            },
            {
                "title": "堤身填筑压实质量",
                "pattern": r"堤身|填筑|堤防",
                "text": "分层填筑、含水率控制和压实度检测是堤防质量的主线。",
            },
        ],
        "monitors": ["堤身沉降", "堤身位移", "渗压", "基坑水位"],
        "acceptance": "单元工程按堤段和桩号划分，分部含堤基处理、堤身填筑、防洪墙，单位工程为本标段。",
    },
    "pump": {
        "label": "泵站涵闸",
        "pattern": r"泵站|水闸|涵闸|节制闸|涵洞|箱涵|闸站|泵房|装机",
        "works": [
            {
                "title": "泵站深基坑支护与降水施工方法",
                "name": "泵站深基坑",
                "pattern": r"泵站|泵房|基坑|深基坑",
                "idea": "支护形式 → 降水井布置 → 分层开挖 → 支撑与监测 → 底板垫层。降水深度、监测频率取设计参数账，没有就写【待核实】。",
            },
            {
                "title": "涵闸底板与止水施工方法",
                "name": "涵闸底板",
                "pattern": r"闸|涵",
                "idea": "基坑验槽 → 底板钢筋混凝土 → 闸墩 → 止水带与伸缩缝 → 养护。强度、抗渗、抗冻等级成组写。",
            },
            {
                "title": "泵房与机电设备安装施工方法",
                "name": "泵房设备",
                "pattern": r"泵房|机组|电气|机电|装机",
                "idea": "设备到场验收 → 基础与预埋 → 机组安装 → 电气调试 → 试运行。装机容量和台数与构筑物账一致。",
            },
        ],
        "difficulties": [
            {
                "title": "泵站深基坑降水与支护",
                "pattern": r"泵站|泵房|深基坑",
                "text": "泵站基坑较深，降水和支护同时影响周边堤防和管线。",
            },
            {
                "title": "涵闸混凝土裂缝与止水",
                "pattern": r"闸|涵",
                "text": "大体积混凝土温控和止水带安装质量是涵闸渗漏的主要风险。",
            },
        ],
        "monitors": ["基坑水位", "支护位移", "周边沉降", "渗压"],
        "acceptance": "单元工程按每座泵站或涵闸分别划分，分部含基础、主体、机电安装，单位工程为本标段。",
    },
    "canal": {
        "label": "灌区渠系",
        "pattern": r"灌区|渠系|渠道|衬砌|干渠|支渠|斗渠|渡槽|倒虹吸",
        "works": [
            {
                "title": "渠系衬砌施工方法",
                "name": "渠系衬砌",
                "pattern": r"衬砌|渠道|渠系|干渠|支渠|斗渠",
                "idea": "渠基整形 → 垫层 → 衬砌（现浇或预制）→ 分缝止水 → 养护。厚度、强度等级、分缝间距取设计参数账。",
            },
            {
                "title": "渠系建筑物施工方法",
                "name": "渠系建筑物",
                "pattern": r"渡槽|倒虹吸|涵|闸|桥",
                "idea": "按建筑物类型分别写基础、主体、接缝和回填。座数与构筑物账一致。",
            },
            {
                "title": "分段通水与试运行",
                "name": "分段通水",
                "pattern": r"灌区|通水|渠系|渠道",
                "idea": "按渠段分期通水，避开灌溉期，写清通水流量分级、渗漏检查和验收条件。",
            },
        ],
        "difficulties": [
            {
                "title": "灌溉期与施工期冲突",
                "pattern": r"灌区|渠系|渠道",
                "text": "渠系要在非灌溉期完成，用水户不能断水，施工窗口窄。",
            },
        ],
        "monitors": ["渠道水位", "渗漏量", "衬砌变形"],
        "acceptance": "单元工程按渠段和建筑物划分，分部含渠道衬砌、渠系建筑物，单位工程为本标段。",
    },
    "reservoir": {
        "label": "水库塘坝",
        "pattern": r"水库|塘坝|除险加固|大坝|溢洪道|放水涵|坝体|坝坡",
        "works": [
            {
                "title": "坝体加固与防渗施工方法",
                "name": "坝体加固",
                "pattern": r"坝体|大坝|防渗|灌浆|坝坡|塘坝",
                "idea": "坝体清理 → 防渗处理 → 分层填筑或灌浆 → 坝坡护砌 → 观测设施埋设。参数取设计参数账。",
            },
            {
                "title": "溢洪道与放水涵施工方法",
                "name": "溢洪道放水涵",
                "pattern": r"溢洪道|放水涵|输水涵",
                "idea": "导流 → 基础 → 主体混凝土 → 止水与接缝 → 金属结构安装。强度、抗渗、抗冻等级成组写。",
            },
            {
                "title": "塘坝整修与库区清淤施工方法",
                "name": "塘坝整修",
                "pattern": r"塘坝|清淤|库区",
                "idea": "排水 → 清淤 → 坝坡整修 → 护坡 → 验收。清淤量、外运去向写清。",
            },
        ],
        "difficulties": [
            {
                "title": "带水作业与库水位控制",
                "pattern": r"水库|塘坝|大坝",
                "text": "水库运行期的水位控制，决定放空、导流和施工窗口。",
            },
        ],
        "monitors": ["库水位", "坝体渗流", "坝体位移"],
        "acceptance": "单元工程按坝段和建筑物划分，分部含坝体、溢洪道、放水涵，单位工程为本标段。",
    },
    "farmland": {
        "label": "高标准农田",
        "pattern": r"高标准农田|地力培肥|农用井|机井|田间道路|沟渠疏浚|农田|灌排",
        "works": [
            {
                "title": "土壤改良与地力培肥施工方法",
                "name": "地力培肥",
                "pattern": r"地力培肥|有机肥|土壤改良",
                "idea": "地块核实 → 有机肥进场检验 → 机械播撒 → 翻耕覆土 → 验收。亩均用量和总亩数取清单，没有就写【待核实】。",
            },
            {
                "title": "农用井工程施工方法",
                "name": "农用井",
                "pattern": r"农用井|机井|成井|洗井",
                "idea": "钻机就位 → 成孔护壁 → 井管安装 → 滤料回填 → 洗井抽水试验 → 井台。眼数、井深、孔径取清单。",
            },
            {
                "title": "沟渠疏浚施工方法",
                "name": "沟渠疏浚",
                "pattern": r"沟渠|疏浚|大沟|中沟|小沟",
                "idea": "清表 → 分段开挖 → 土方就地摊铺或外运 → 修坡修底 → 断面验收。长度和土方量取清单，施工期不得中断灌排。",
            },
            {
                "title": "渠系建筑物施工方法",
                "name": "渠系建筑物",
                "pattern": r"梁板桥|涵管桥|路下排水涵|拦水坝|桥涵",
                "idea": "按桥梁、涵管、拦水坝分别写围堰、基坑、主体、回填。座数与清单一致。拦水坝必须写施工导流。",
            },
            {
                "title": "田间道路施工方法",
                "name": "田间道路",
                "pattern": r"田间道路|水泥混凝土路|煤矸石",
                "idea": "路基 → 基层 → 面层 → 交叉口 → 养护。新建与拆除重建分段写，长度取清单。",
            },
        ],
        "difficulties": [
            {
                "title": "农用井分布施工与成井质量",
                "pattern": r"农用井|机井",
                "text": "井位点位分散，多台钻机并行，成井含砂量和出水量要逐井控制。",
            },
            {
                "title": "沟渠疏浚大方量土方调配",
                "pattern": r"沟渠|疏浚",
                "text": "沟渠线路长、土方量大，就地摊铺受耕作限制，外运要控制扬尘和对农田的占用。",
            },
            {
                "title": "施工期农田灌溉保障",
                "pattern": r"农田|灌溉|灌排|高标准农田",
                "text": "施工区域本身是农田，沟渠截流和桥涵围堰期间不得中断灌溉和排涝。",
            },
        ],
        "monitors": ["沟渠水位", "灌溉保证", "成井出水量", "路基压实度"],
        "acceptance": "单元工程按井、沟段、桥涵、路段划分，分部含灌溉排水、田间道路、地力培肥，单位工程为本标段。",
    },
}

# 与子类型无关的通用重难点候选：范围里命中才用。
COMMON_DIFFICULTIES: list[dict] = [
    {
        "title": "邻近村庄与敏感点保护",
        "pattern": r"居民|学校|村庄|集镇|水源|饮用水|养殖",
        "text": "施工区临近居民点或水源，噪声、扬尘、水质和交通都要有对应措施。",
    },
    {
        "title": "场地狭窄与交通组织",
        "pattern": r"狭窄|交通不便|单行道|便道|进场道路",
        "text": "进场道路和作业面受限，材料运输和机械进场要提前组织。",
    },
]

# 机构化监测项的列定义由 engineering_writer 的 GRID_COLUMNS 提供。


def detect_subtypes(blob: str, limit: int = 3) -> list[str]:
    """按招标范围、规模、工程名关键词打分，返回得分最高的子类型键。"""
    text = blob or ""
    scored: list[tuple[int, str]] = []
    for key, spec in SUBTYPES.items():
        score = len(re.findall(spec["pattern"], text))
        if score:
            scored.append((score, key))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [key for _, key in scored[:limit]]


def subtype_labels(keys: list[str]) -> list[str]:
    return [SUBTYPES[k]["label"] for k in keys if k in SUBTYPES]


def craft_works(keys: list[str], blob: str, limit: int = 10) -> list[dict]:
    """返回应进目录的工艺。子类型里一项也没命中时，至少给前两项。"""
    text = blob or ""
    out: list[dict] = []
    for key in keys:
        spec = SUBTYPES.get(key)
        if not spec:
            continue
        hit = [w for w in spec["works"] if re.search(w["pattern"], text)]
        picked = hit or spec["works"][:2]
        for work in picked:
            if all(work["title"] != item["title"] for item in out):
                out.append(work)
    return out[:limit]


def craft_difficulties(keys: list[str], blob: str) -> list[dict]:
    """范围命中才出的重难点候选，子类型的在前，通用的在后。"""
    text = blob or ""
    out: list[dict] = []
    pools = [SUBTYPES[k]["difficulties"] for k in keys if k in SUBTYPES] + [COMMON_DIFFICULTIES]
    for pool in pools:
        for item in pool:
            if re.search(item["pattern"], text) and all(item["title"] != o["title"] for o in out):
                out.append(item)
    return out


def craft_monitors(keys: list[str]) -> list[str]:
    out: list[str] = []
    for key in keys:
        for name in SUBTYPES.get(key, {}).get("monitors", []):
            if name not in out:
                out.append(name)
    return out


def acceptance_hint(keys: list[str]) -> str:
    parts = [SUBTYPES[k]["acceptance"] for k in keys if k in SUBTYPES]
    return " ".join(parts)
