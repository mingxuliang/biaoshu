"""暗标导出脱敏：把 docx 里能暴露投标人身份的非正文信息清干净。

只清「正文以外」的东西，不改正文：
- 文档核心属性（作者、最后修改者、标题、主题、关键词、备注、分类）；
- docProps/app.xml 里的公司、负责人；docProps/custom.xml 里的自定义属性；
- 批注（正文里的批注标记和 comments.xml 内容）；
- 修订痕迹（接受全部修订：删掉删除内容，保留插入内容，去掉格式修订记录）；
- 页眉页脚里出现的投标单位名称。

正文里出现单位名称是废标级问题，由预审引擎拦截，不在这里偷偷改写。
"""

from __future__ import annotations

import io
import re
import zipfile

from lxml import etree

from .safe_office import SAFE_PARSER

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _w(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


_APP_BLANK_TAGS = ("Company", "Manager")
_REVISION_PROP_TAGS = (
    "rPrChange",
    "pPrChange",
    "sectPrChange",
    "tblPrChange",
    "tblPrExChange",
    "trPrChange",
    "tcPrChange",
    "tblGridChange",
    "numberingChange",
    "moveFromRangeStart",
    "moveFromRangeEnd",
    "moveToRangeStart",
    "moveToRangeEnd",
)


def _blank_app_xml(data: bytes) -> bytes:
    text = data.decode("utf-8", errors="ignore")
    for tag in _APP_BLANK_TAGS:
        text = re.sub(rf"<{tag}>.*?</{tag}>", f"<{tag}></{tag}>", text, flags=re.S)
        text = re.sub(rf"<{tag}\s*/>", f"<{tag}></{tag}>", text)
    return text.encode("utf-8")


def _empty_custom_xml(data: bytes) -> bytes:
    try:
        root = etree.fromstring(data, parser=SAFE_PARSER)
    except etree.XMLSyntaxError:
        return data
    for child in list(root):
        root.remove(child)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _accept_revisions(root) -> None:
    for node in list(root.iter(_w("del"))):
        parent = node.getparent()
        if parent is not None:
            parent.remove(node)
    for node in list(root.iter(_w("moveFrom"))):
        parent = node.getparent()
        if parent is not None:
            parent.remove(node)
    for tag in ("ins", "moveTo"):
        for node in list(root.iter(_w(tag))):
            parent = node.getparent()
            if parent is None:
                continue
            index = parent.index(node)
            for child in list(node):
                parent.insert(index, child)
                index += 1
            parent.remove(node)
    for tag in _REVISION_PROP_TAGS:
        for node in list(root.iter(_w(tag))):
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)


def _strip_comment_marks(root) -> None:
    for tag in ("commentRangeStart", "commentRangeEnd"):
        for node in list(root.iter(_w(tag))):
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)
    for node in list(root.iter(_w("commentReference"))):
        run = node.getparent()
        if run is not None and run.tag == _w("r") and run.getparent() is not None:
            run.getparent().remove(run)
        elif run is not None:
            run.remove(node)


def _scrub_names(root, names: list[str]) -> int:
    """把 w:t 里的投标单位名称删掉。名称可能被拆在几个 run 里，所以按段落拼起来判断。"""
    removed = 0
    for para in root.iter(_w("p")):
        texts = list(para.iter(_w("t")))
        if not texts:
            continue
        joined = "".join(t.text or "" for t in texts)
        if not any(name in joined for name in names):
            continue
        for name in names:
            if name not in joined:
                continue
            joined = joined.replace(name, "")
            removed += 1
        # 清掉后重新分配：全部文字放回第一个 w:t，其余清空，保留段落和 run 结构
        texts[0].text = joined
        texts[0].set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        for extra in texts[1:]:
            extra.text = ""
    return removed


def _is_header_footer(name: str) -> bool:
    return bool(re.match(r"word/(header|footer)\d*\.xml$", name))


def anonymize_docx(source: bytes, bidder_names: list[str] | None = None) -> bytes:
    """返回脱敏后的 docx 字节。传入的不是合法 docx 时原样抛出 BadZipFile。"""
    import docx

    names = sorted({n.strip() for n in (bidder_names or []) if n and len(n.strip()) >= 4}, key=len, reverse=True)

    # 第一步：核心属性。用 python-docx 改，保证 core.xml 结构合法
    document = docx.Document(io.BytesIO(source))
    props = document.core_properties
    props.author = ""
    props.last_modified_by = ""
    props.title = ""
    props.subject = ""
    props.keywords = ""
    props.comments = ""
    props.category = ""
    buf = io.BytesIO()
    document.save(buf)

    # 第二步：直接处理 zip 里的各个 part
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            name = info.filename
            if name == "docProps/app.xml":
                data = _blank_app_xml(data)
            elif name == "docProps/custom.xml":
                data = _empty_custom_xml(data)
            elif name == "word/comments.xml":
                try:
                    root = etree.fromstring(data, parser=SAFE_PARSER)
                    for child in list(root):
                        root.remove(child)
                    data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
                except etree.XMLSyntaxError:
                    pass
            elif name == "word/document.xml" or _is_header_footer(name):
                try:
                    root = etree.fromstring(data, parser=SAFE_PARSER)
                except etree.XMLSyntaxError:
                    zout.writestr(info, data)
                    continue
                _accept_revisions(root)
                _strip_comment_marks(root)
                if names and _is_header_footer(name):
                    _scrub_names(root, names)
                data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
            zout.writestr(info, data)
    return out.getvalue()


def residual_identity(source: bytes, bidder_names: list[str] | None = None) -> list[str]:
    """脱敏后自检：返回还残留的身份信息说明，空列表表示干净。"""
    import docx

    problems: list[str] = []
    names = [n.strip() for n in (bidder_names or []) if n and len(n.strip()) >= 4]
    document = docx.Document(io.BytesIO(source))
    props = document.core_properties
    for field in ("author", "last_modified_by", "title", "subject", "keywords", "comments", "category"):
        if (getattr(props, field, "") or "").strip():
            problems.append(f"文档属性 {field}")
    with zipfile.ZipFile(io.BytesIO(source)) as zf:
        for name in zf.namelist():
            data = zf.read(name)
            if name == "docProps/app.xml":
                text = data.decode("utf-8", errors="ignore")
                for tag in _APP_BLANK_TAGS:
                    m = re.search(rf"<{tag}>(.+?)</{tag}>", text, flags=re.S)
                    if m and m.group(1).strip():
                        problems.append(f"app.xml {tag}")
            elif name == "docProps/custom.xml":
                if b"<property" in data or b":property" in data:
                    problems.append("自定义属性")
            elif name == "word/comments.xml":
                if b"<w:comment " in data or b"<w:comment>" in data:
                    problems.append("批注")
            elif name == "word/document.xml":
                if b"<w:ins " in data or b"<w:del " in data:
                    problems.append("修订痕迹")
            elif _is_header_footer(name) and names:
                text = data.decode("utf-8", errors="ignore")
                plain = re.sub(r"<[^>]+>", "", text)
                if any(n in plain for n in names):
                    problems.append(f"页眉页脚 {name}")
    return problems
