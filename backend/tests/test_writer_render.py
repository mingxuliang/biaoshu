"""版式预览的内容哈希、缓存和渲染服务回退，不依赖真实 LibreOffice。"""

from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from types import SimpleNamespace

import pymupdf

from app.engines.writer_export import subtree_ids
from app.engines.writer_render import (
    RenderUnavailable,
    convert_docx_to_pdf,
    docx_fingerprint,
    is_valid_hash,
    render_docx,
    render_page_png,
)


def _docx(*parts: tuple[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in parts:
            zf.writestr(name, data)
    return buf.getvalue()


def _pdf() -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "preview")
    data = doc.tobytes()
    doc.close()
    return data


class WriterRenderCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        settings = SimpleNamespace(
            upload_dir=self._tmp.name,
            lo_render_url="http://lo.test:8090",
            lo_render_timeout_sec=5,
        )
        self._patch = unittest.mock.patch(
            "app.engines.writer_render.get_settings", return_value=settings
        )
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmp.cleanup()

    def test_fingerprint_ignores_doc_props_and_zip_timestamps(self) -> None:
        body = b"<w:document>same</w:document>"
        first = _docx(("word/document.xml", body), ("docProps/core.xml", b"a"))
        second = _docx(("docProps/core.xml", b"changed"), ("word/document.xml", body))
        self.assertEqual(docx_fingerprint(first), docx_fingerprint(second))
        changed = _docx(("word/document.xml", b"<w:document>other</w:document>"))
        self.assertNotEqual(docx_fingerprint(first), docx_fingerprint(changed))

    def test_hash_rejects_path_escape(self) -> None:
        self.assertTrue(is_valid_hash("a" * 64))
        self.assertFalse(is_valid_hash("../etc/passwd"))
        self.assertFalse(is_valid_hash("A" * 64))

    def test_second_render_hits_cache(self) -> None:
        docx = _docx(("word/document.xml", b"<w:document/>"))
        pdf = _pdf()
        with unittest.mock.patch(
            "app.engines.writer_render.convert_docx_to_pdf", return_value=pdf
        ) as convert:
            first = render_docx("draft/1", docx)
            second = render_docx("draft/1", docx)
        self.assertEqual(convert.call_count, 1)
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(first["pages"], 1)
        self.assertEqual(first["hash"], second["hash"])
        png = render_page_png("draft/1", first["hash"], 1)
        self.assertTrue(png.startswith(b"\x89PNG"))
        with self.assertRaises(FileNotFoundError):
            render_page_png("draft/1", "b" * 64, 1)

    def test_unreachable_service_falls_back_to_local_soffice(self) -> None:
        with unittest.mock.patch(
            "app.engines.writer_render._convert_via_service",
            side_effect=ConnectionError("down"),
        ), unittest.mock.patch(
            "app.engines.writer_render._convert_via_local_soffice",
            return_value=b"%PDF",
        ) as local:
            self.assertEqual(convert_docx_to_pdf(b"docx"), b"%PDF")
        local.assert_called_once()

    def test_service_failure_does_not_fall_back(self) -> None:
        with unittest.mock.patch(
            "app.engines.writer_render._convert_via_service",
            side_effect=RenderUnavailable("bad"),
        ), unittest.mock.patch(
            "app.engines.writer_render._convert_via_local_soffice",
        ) as local:
            with self.assertRaises(RenderUnavailable):
                convert_docx_to_pdf(b"docx")
        local.assert_not_called()

    def test_subtree_keeps_outline_order(self) -> None:
        outline = [
            {"id": "a"},
            {"id": "a1", "parentId": "a"},
            {"id": "b"},
            {"id": "a2", "parentId": "a"},
        ]
        self.assertEqual(subtree_ids(outline, "a"), ["a", "a1", "a2"])
        self.assertEqual(subtree_ids(outline, "missing"), [])


if __name__ == "__main__":
    unittest.main()
