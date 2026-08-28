import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { LexicalComposer } from "@lexical/react/LexicalComposer";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { RichTextPlugin } from "@lexical/react/LexicalRichTextPlugin";
import { HistoryPlugin } from "@lexical/react/LexicalHistoryPlugin";
import { ContentEditable } from "@lexical/react/LexicalContentEditable";
import { OnChangePlugin } from "@lexical/react/LexicalOnChangePlugin";
import { ListPlugin } from "@lexical/react/LexicalListPlugin";
import { LexicalErrorBoundary } from "@lexical/react/LexicalErrorBoundary";
import { TablePlugin } from "@lexical/react/LexicalTablePlugin";
import {
  $createListItemNode,
  $createListNode,
  $isListItemNode,
  $isListNode,
  INSERT_ORDERED_LIST_COMMAND,
  INSERT_UNORDERED_LIST_COMMAND,
  ListItemNode,
  ListNode,
} from "@lexical/list";
import { $patchStyleText, $setBlocksType } from "@lexical/selection";
import { $createHeadingNode, $isHeadingNode, HeadingNode } from "@lexical/rich-text";
import {
  $createTableCellNode,
  $createTableNode,
  $createTableRowNode,
  $isTableCellNode,
  $isTableNode,
  $isTableRowNode,
  TableCellHeaderStates,
  TableCellNode,
  TableNode,
  TableRowNode,
} from "@lexical/table";
import {
  $createParagraphNode,
  $createTextNode,
  $getRoot,
  $getSelection,
  $insertNodes,
  $isElementNode,
  $isParagraphNode,
  $isRangeSelection,
  $isTextNode,
  COMMAND_PRIORITY_EDITOR,
  FORMAT_ELEMENT_COMMAND,
  FORMAT_TEXT_COMMAND,
  REDO_COMMAND,
  UNDO_COMMAND,
  createCommand,
  type ElementFormatType,
  type LexicalCommand,
  type LexicalEditor,
  type LexicalNode,
  type TextNode,
} from "lexical";
import { $createImageNode, $isImageNode, ImageNode } from "../nodes/ImageNode";

const INSERT_CHAPTER_IMAGE_COMMAND: LexicalCommand<{ src: string; alt: string }> = createCommand(
  "INSERT_CHAPTER_IMAGE_COMMAND",
);

const IMAGE_MD_RE = /^!\[([^\]]*)\]\((\/api\/writer-images\/[^/]+\/file)\)$/;
const INLINE_SPLIT_RE = /(\*\*.+?\*\*|__.+?__|\*.+?\*)/g;

const FONT_STACK: Record<string, string> = {
  宋体: '"宋体", SimSun, serif',
  黑体: '"黑体", SimHei, sans-serif',
  仿宋: '"仿宋", FangSong, serif',
  楷体: '"楷体", KaiTi, serif',
  "Times New Roman": '"Times New Roman", Times, serif',
  Arial: "Arial, Helvetica, sans-serif",
};

function cssFontFamily(name: string): string {
  return FONT_STACK[name] || `"${name}"`;
}

function styleFromFont(font?: string, size?: string): string {
  const parts: string[] = [];
  if (font) parts.push(`font-family: ${cssFontFamily(font)}`);
  if (size) parts.push(`font-size: ${size}`);
  return parts.join("; ");
}

function parseNodeFont(style: string): { font?: string; size?: string } {
  const fam = /font-family:\s*([^;]+)/i.exec(style || "");
  const sz = /font-size:\s*([^;]+)/i.exec(style || "");
  let font: string | undefined;
  if (fam) {
    const raw = fam[1].trim();
    const quoted = /["']([^"']+)["']/.exec(raw);
    font = (quoted ? quoted[1] : raw.split(",")[0]).trim();
  }
  return { font, size: sz ? sz[1].trim() : undefined };
}

const FONT_WRAP_RE = /\{\{([^|}]+)\|([^}]+)\}\}([\s\S]*?)\{\{\/\}\}/g;

const FONT_SIZE_CSS: Record<string, string> = {
  小二: "18pt",
  三号: "16pt",
  小三: "15pt",
  四号: "14pt",
  小四: "12pt",
  五号: "10.5pt",
  小五: "9pt",
};

function applyAlign(node: { setFormat: (f: ElementFormatType) => void }, align: ElementFormatType | "") {
  if (align === "center" || align === "right") node.setFormat(align);
}

function splitAlign(line: string): { align: ElementFormatType | ""; rest: string } {
  if (line.startsWith(">>> ")) return { align: "center", rest: line.slice(4) };
  if (line.startsWith(">>>")) return { align: "center", rest: line.slice(3) };
  if (line.startsWith(">> ")) return { align: "right", rest: line.slice(3) };
  return { align: "", rest: line };
}

function alignPrefix(node: { getFormatType?: () => string }): string {
  const align = node.getFormatType?.() || "";
  if (align === "center") return ">>> ";
  if (align === "right") return ">> ";
  return "";
}

function isTableSep(line: string): boolean {
  return /^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$/.test(line.trim());
}

function isTableRow(line: string): boolean {
  const t = line.trim();
  return t.startsWith("|") && t.split("|").length >= 3;
}

function parseTableRow(line: string): string[] {
  let t = line.trim();
  if (t.startsWith("|")) t = t.slice(1);
  if (t.endsWith("|")) t = t.slice(0, -1);
  return t.split("|").map((c) => c.trim());
}

function appendTable(root: ReturnType<typeof $getRoot>, rows: string[][]) {
  if (!rows.length) return;
  const width = Math.max(...rows.map((r) => r.length));
  const table = $createTableNode();
  rows.forEach((cells, rIdx) => {
    const row = $createTableRowNode();
    for (let i = 0; i < width; i += 1) {
      const header = rIdx === 0 ? TableCellHeaderStates.ROW : TableCellHeaderStates.NO_STATUS;
      const cell = $createTableCellNode(header);
      const p = $createParagraphNode();
      const text = cells[i] || "";
      if (text) appendInline(p, text);
      cell.append(p);
      row.append(cell);
    }
    table.append(row);
  });
  root.append(table);
}

function appendStyledInline(
  parent: { append: (n: LexicalNode) => void },
  text: string,
  font?: string,
  size?: string,
) {
  const style = styleFromFont(font, size);
  const parts = text.split(INLINE_SPLIT_RE).filter(Boolean);
  const apply = (n: TextNode) => {
    if (style) n.setStyle(style);
  };
  if (!parts.length) {
    const n = $createTextNode("");
    apply(n);
    parent.append(n);
    return;
  }
  parts.forEach((part) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      const n = $createTextNode(part.slice(2, -2));
      n.toggleFormat("bold");
      apply(n);
      parent.append(n);
      return;
    }
    if (part.startsWith("__") && part.endsWith("__") && part.length > 4) {
      const n = $createTextNode(part.slice(2, -2));
      n.toggleFormat("underline");
      apply(n);
      parent.append(n);
      return;
    }
    if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
      const n = $createTextNode(part.slice(1, -1));
      n.toggleFormat("italic");
      apply(n);
      parent.append(n);
      return;
    }
    const n = $createTextNode(part);
    apply(n);
    parent.append(n);
  });
}

function appendInline(parent: { append: (n: LexicalNode) => void }, text: string) {
  FONT_WRAP_RE.lastIndex = 0;
  const chunks: { text: string; font?: string; size?: string }[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  const re = new RegExp(FONT_WRAP_RE.source, "g");
  while ((m = re.exec(text))) {
    if (m.index > last) chunks.push({ text: text.slice(last, m.index) });
    chunks.push({ text: m[3], font: m[1].trim(), size: m[2].trim() });
    last = m.index + m[0].length;
  }
  if (last < text.length) chunks.push({ text: text.slice(last) });
  if (!chunks.length) chunks.push({ text });
  chunks.forEach((c) => {
    if (!c.text && !c.font && !c.size) return;
    appendStyledInline(parent, c.text, c.font, c.size);
  });
}

function serializeInline(node: LexicalNode): string {
  if ($isImageNode(node)) {
    return `![${node.getAlt()}](${node.getSrc()})`;
  }
  if ($isTextNode(node)) {
    let text = node.getTextContent();
    if (node.hasFormat("bold")) text = `**${text}**`;
    if (node.hasFormat("italic")) text = `*${text}*`;
    if (node.hasFormat("underline")) text = `__${text}__`;
    const { font, size } = parseNodeFont(node.getStyle() || "");
    if (font || size) {
      text = `{{${font || "宋体"}|${size || "12pt"}}}${text}{{/}}`;
    }
    return text;
  }
  if ($isElementNode(node)) {
    return node.getChildren().map(serializeInline).join("");
  }
  return node.getTextContent();
}

function markdownToEditor(editor: LexicalEditor, markdown: string) {
  editor.update(
    () => {
      const root = $getRoot();
      root.clear();
      const lines = markdown.replace(/\r\n/g, "\n").split("\n");
      let listType: "bullet" | "number" | null = null;
      let listNode: ReturnType<typeof $createListNode> | null = null;

      const flushList = () => {
        if (listNode) root.append(listNode);
        listNode = null;
        listType = null;
      };

      const startList = (type: "bullet" | "number") => {
        if (listType !== type) {
          flushList();
          listType = type;
          listNode = $createListNode(type === "number" ? "number" : "bullet");
        }
      };

      let i = 0;
      while (i < lines.length) {
        const line = lines[i];
        const { align, rest } = splitAlign(line);
        const trimmed = rest.trim();
        if (trimmed.startsWith("```")) {
          i += 1;
          continue;
        }
        if (isTableRow(line) || isTableSep(line)) {
          flushList();
          const rows: string[][] = [];
          while (i < lines.length && (isTableRow(lines[i]) || isTableSep(lines[i]))) {
            if (!isTableSep(lines[i])) rows.push(parseTableRow(lines[i]));
            i += 1;
          }
          appendTable(root, rows);
          continue;
        }
        const img = IMAGE_MD_RE.exec(trimmed);
        if (img) {
          flushList();
          root.append($createImageNode(img[2], img[1]));
          i += 1;
          continue;
        }
        const heading = /^(#{1,6})\s+(.*)$/.exec(trimmed);
        if (heading) {
          flushList();
          const depth = heading[1].length;
          const tag = depth <= 2 ? "h2" : "h3";
          const h = $createHeadingNode(tag);
          appendInline(h, heading[2]);
          applyAlign(h, align);
          root.append(h);
          i += 1;
          continue;
        }
        const bullet = /^[-*]\s+/.exec(trimmed);
        if (bullet) {
          startList("bullet");
          const item = $createListItemNode();
          appendInline(item, trimmed.slice(bullet[0].length));
          listNode!.append(item);
          i += 1;
          continue;
        }
        const numbered = /^(\d+)[.)]\s+/.exec(trimmed);
        if (numbered) {
          startList("number");
          const item = $createListItemNode();
          appendInline(item, trimmed.slice(numbered[0].length));
          listNode!.append(item);
          i += 1;
          continue;
        }
        flushList();
        const p = $createParagraphNode();
        if (rest.trim()) appendInline(p, rest.replace(/\s+$/, ""));
        applyAlign(p, align);
        root.append(p);
        i += 1;
      }
      flushList();
      if (root.getChildrenSize() === 0) {
        root.append($createParagraphNode());
      }
    },
    { discrete: true },
  );
}

function editorToMarkdown(editor: LexicalEditor): string {
  let out = "";
  editor.getEditorState().read(() => {
    const lines: string[] = [];
    const walk = (node: LexicalNode) => {
      if ($isImageNode(node)) {
        lines.push(`![${node.getAlt()}](${node.getSrc()})`);
        return;
      }
      if ($isTableNode(node)) {
        const rows = node.getChildren().filter($isTableRowNode);
        const grid = rows.map((row) =>
          row
            .getChildren()
            .filter($isTableCellNode)
            .map((cell) => serializeInline(cell).replace(/\|/g, "\\|").trim()),
        );
        if (!grid.length) return;
        const width = Math.max(...grid.map((r) => r.length), 1);
        const pad = (r: string[]) => {
          const next = [...r];
          while (next.length < width) next.push("");
          return next;
        };
        const fmt = (r: string[]) => `| ${pad(r).join(" | ")} |`;
        lines.push(fmt(grid[0]));
        lines.push(`| ${Array.from({ length: width }, () => "---").join(" | ")} |`);
        grid.slice(1).forEach((r) => lines.push(fmt(r)));
        return;
      }
      if ($isHeadingNode(node)) {
        const tag = node.getTag();
        const prefix = tag === "h3" ? "### " : "## ";
        lines.push(alignPrefix(node) + prefix + serializeInline(node));
        return;
      }
      if ($isListNode(node)) {
        const ordered = node.getListType() === "number";
        node.getChildren().forEach((child, idx) => {
          if (!$isListItemNode(child)) return;
          const body = serializeInline(child);
          lines.push(ordered ? `${idx + 1}. ${body}` : `- ${body}`);
        });
        return;
      }
      if ($isParagraphNode(node)) {
        lines.push(alignPrefix(node) + serializeInline(node));
        return;
      }
    };
    $getRoot().getChildren().forEach(walk);
    out = lines.join("\n");
  });
  return out;
}

function ImageInsertPlugin() {
  const [editor] = useLexicalComposerContext();
  useEffect(() => {
    return editor.registerCommand(
      INSERT_CHAPTER_IMAGE_COMMAND,
      (payload) => {
        editor.update(() => {
          const image = $createImageNode(payload.src, payload.alt);
          const after = $createParagraphNode();
          const selection = $getSelection();
          if ($isRangeSelection(selection)) {
            $insertNodes([image, after]);
          } else {
            $getRoot().append(image);
            $getRoot().append(after);
          }
        });
        return true;
      },
      COMMAND_PRIORITY_EDITOR,
    );
  }, [editor]);
  return null;
}

function LoadMarkdownPlugin({
  markdown,
  revision,
  onLoaded,
}: {
  markdown: string;
  revision: number;
  onLoaded: () => void;
}) {
  const [editor] = useLexicalComposerContext();
  useEffect(() => {
    markdownToEditor(editor, markdown);
    onLoaded();
    // 只在 revision 变化时重载，避免用户输入回流把光标打乱
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editor, revision]);
  return null;
}

function EditablePlugin({ enabled }: { enabled: boolean }) {
  const [editor] = useLexicalComposerContext();
  useEffect(() => {
    editor.setEditable(enabled);
  }, [editor, enabled]);
  return null;
}

function Toolbar({
  fontFamily,
  fontSize,
  onFontFamily,
  onFontSize,
}: {
  fontFamily: string;
  fontSize: string;
  onFontFamily: (v: string) => void;
  onFontSize: (v: string) => void;
}) {
  const [editor] = useLexicalComposerContext();
  const [findOpen, setFindOpen] = useState(false);
  const [findText, setFindText] = useState("");
  const [replaceText, setReplaceText] = useState("");

  const exec = (cmd: string) => {
    if (cmd === "bold") editor.dispatchCommand(FORMAT_TEXT_COMMAND, "bold");
    if (cmd === "italic") editor.dispatchCommand(FORMAT_TEXT_COMMAND, "italic");
    if (cmd === "underline") editor.dispatchCommand(FORMAT_TEXT_COMMAND, "underline");
    if (cmd === "ul") editor.dispatchCommand(INSERT_UNORDERED_LIST_COMMAND, undefined);
    if (cmd === "ol") editor.dispatchCommand(INSERT_ORDERED_LIST_COMMAND, undefined);
    if (cmd === "alignLeft") editor.dispatchCommand(FORMAT_ELEMENT_COMMAND, "left");
    if (cmd === "alignCenter") editor.dispatchCommand(FORMAT_ELEMENT_COMMAND, "center");
    if (cmd === "alignRight") editor.dispatchCommand(FORMAT_ELEMENT_COMMAND, "right");
    if (cmd === "undo") editor.dispatchCommand(UNDO_COMMAND, undefined);
    if (cmd === "redo") editor.dispatchCommand(REDO_COMMAND, undefined);
  };

  const setBlock = (type: "p" | "h2" | "h3") => {
    editor.update(() => {
      const selection = $getSelection();
      if (!$isRangeSelection(selection)) return;
      $setBlocksType(selection, () => (type === "p" ? $createParagraphNode() : $createHeadingNode(type)));
    });
  };

  const applyFont = (family: string, size: string) => {
    editor.update(() => {
      const selection = $getSelection();
      if (!$isRangeSelection(selection)) return;
      $patchStyleText(selection, {
        "font-family": FONT_STACK[family] || family,
        "font-size": FONT_SIZE_CSS[size] || size,
      });
    });
  };

  const replaceAll = () => {
    const needle = findText;
    if (!needle) return;
    editor.update(() => {
      const visit = (node: LexicalNode) => {
        if ($isTextNode(node) && node.getTextContent().includes(needle)) {
          const next = node.getTextContent().split(needle).join(replaceText);
          (node as TextNode).setTextContent(next);
        }
        if ($isElementNode(node)) node.getChildren().forEach(visit);
      };
      $getRoot().getChildren().forEach(visit);
    });
  };

  const iconBtn =
    "flex h-6 w-6 cursor-pointer items-center justify-center rounded text-foreground-500 transition-colors hover:bg-background-200 hover:text-foreground-800 disabled:cursor-not-allowed disabled:opacity-40";

  return (
    <div className="flex flex-wrap items-center gap-1 border-b border-background-300 bg-background-50 px-3 py-1.5">
      <button type="button" className={iconBtn} title="撤销" onClick={() => exec("undo")}>
        <i className="ri-arrow-go-back-line text-xs"></i>
      </button>
      <button type="button" className={iconBtn} title="重做" onClick={() => exec("redo")}>
        <i className="ri-arrow-go-forward-line text-xs"></i>
      </button>
      <div className="mx-1 hidden h-4 w-px bg-background-300 sm:block" />
      <select
        value={fontFamily}
        onChange={(e) => {
          onFontFamily(e.target.value);
          applyFont(e.target.value, fontSize);
        }}
        className="h-6 cursor-pointer rounded border border-background-300 bg-background-50 px-1.5 text-[11px] text-foreground-700 outline-none focus:border-primary-400"
        title="应用到选中文字"
      >
        {Object.keys(FONT_STACK).map((f) => (
          <option key={f} value={f}>
            {f}
          </option>
        ))}
      </select>
      <select
        value={fontSize}
        onChange={(e) => {
          onFontSize(e.target.value);
          applyFont(fontFamily, e.target.value);
        }}
        className="h-6 cursor-pointer rounded border border-background-300 bg-background-50 px-1.5 text-[11px] text-foreground-700 outline-none focus:border-primary-400"
        title="应用到选中文字"
      >
        {Object.keys(FONT_SIZE_CSS).map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
      <div className="mx-1 hidden h-4 w-px bg-background-300 sm:block" />
      <button type="button" className={iconBtn} title="加粗" onClick={() => exec("bold")}>
        <i className="ri-bold text-xs"></i>
      </button>
      <button type="button" className={iconBtn} title="斜体" onClick={() => exec("italic")}>
        <i className="ri-italic text-xs"></i>
      </button>
      <button type="button" className={iconBtn} title="下划线" onClick={() => exec("underline")}>
        <i className="ri-underline text-xs"></i>
      </button>
      <div className="mx-1 hidden h-4 w-px bg-background-300 sm:block" />
      <button type="button" className={iconBtn} title="无序列表" onClick={() => exec("ul")}>
        <i className="ri-list-unordered text-xs"></i>
      </button>
      <button type="button" className={iconBtn} title="有序列表" onClick={() => exec("ol")}>
        <i className="ri-list-ordered-2 text-xs"></i>
      </button>
      <button type="button" className={iconBtn} title="左对齐" onClick={() => exec("alignLeft")}>
        <i className="ri-align-left text-xs"></i>
      </button>
      <button type="button" className={iconBtn} title="居中" onClick={() => exec("alignCenter")}>
        <i className="ri-align-center text-xs"></i>
      </button>
      <button
        type="button"
        className="flex h-6 cursor-pointer items-center rounded px-1.5 text-[11px] text-foreground-500 transition-colors hover:bg-background-200 hover:text-foreground-800"
        title="正文"
        onClick={() => setBlock("p")}
      >
        正文
      </button>
      <button
        type="button"
        className="flex h-6 cursor-pointer items-center rounded px-1.5 text-[11px] text-foreground-500 transition-colors hover:bg-background-200 hover:text-foreground-800"
        title="二级标题"
        onClick={() => setBlock("h2")}
      >
        H2
      </button>
      <button
        type="button"
        className="flex h-6 cursor-pointer items-center rounded px-1.5 text-[11px] text-foreground-500 transition-colors hover:bg-background-200 hover:text-foreground-800"
        title="三级标题"
        onClick={() => setBlock("h3")}
      >
        H3
      </button>
      <div className="mx-1 hidden h-4 w-px bg-background-300 sm:block" />
      <button
        type="button"
        className="flex h-6 cursor-pointer items-center gap-1 rounded px-1.5 text-[11px] text-foreground-500 transition-colors hover:bg-background-200"
        title="查找替换"
        onClick={() => setFindOpen((v) => !v)}
      >
        <i className="ri-find-replace-line text-xs"></i>
        查找替换
      </button>
      {findOpen && (
        <div className="flex flex-wrap items-center gap-1">
          <input
            value={findText}
            onChange={(e) => setFindText(e.target.value)}
            placeholder="查找"
            className="h-6 w-24 rounded border border-background-300 bg-background-50 px-1.5 text-[11px] outline-none focus:border-primary-400"
          />
          <input
            value={replaceText}
            onChange={(e) => setReplaceText(e.target.value)}
            placeholder="替换为"
            className="h-6 w-24 rounded border border-background-300 bg-background-50 px-1.5 text-[11px] outline-none focus:border-primary-400"
          />
          <button
            type="button"
            onClick={replaceAll}
            className="h-6 cursor-pointer rounded bg-primary-500 px-2 text-[11px] text-background-50"
          >
            全部替换
          </button>
        </div>
      )}
    </div>
  );
}

export interface ChapterEditorHandle {
  insertImage: (src: string, alt: string) => boolean;
}

interface ChapterEditorProps {
  chapterId: string;
  markdown: string;
  editable: boolean;
  fontFamily: string;
  fontSize: string;
  onFontFamily: (v: string) => void;
  onFontSize: (v: string) => void;
  onMarkdownChange: (markdown: string) => void;
  onReady?: (handle: ChapterEditorHandle) => void;
}

export default function ChapterEditor({
  chapterId,
  markdown,
  editable,
  fontFamily,
  fontSize,
  onFontFamily,
  onFontSize,
  onMarkdownChange,
  onReady,
}: ChapterEditorProps) {
  const editorRef = useRef<LexicalEditor | null>(null);
  const lastPushed = useRef(markdown);
  const skipChange = useRef(true);
  const [loadRevision, setLoadRevision] = useState(0);

  const editorConfig = useMemo(
    () => ({
      namespace: `writer-chapter-${chapterId}`,
      nodes: [HeadingNode, ListNode, ListItemNode, ImageNode, TableNode, TableCellNode, TableRowNode],
      theme: {
        heading: { h1: "editor-heading-h1", h2: "editor-heading-h2", h3: "editor-heading-h3" },
        paragraph: "editor-paragraph",
        text: {
          bold: "editor-text-bold",
          italic: "editor-text-italic",
          underline: "editor-text-underline",
          strikethrough: "editor-text-strikethrough",
          code: "editor-text-code",
        },
        list: { ul: "editor-list-ul", ol: "editor-list-ol", listitem: "editor-listitem" },
      },
      onError: (error: unknown) => {
        console.error("Chapter editor error:", error);
      },
    }),
    [chapterId],
  );

  useEffect(() => {
    if (markdown === lastPushed.current) return;
    lastPushed.current = markdown;
    setLoadRevision((n) => n + 1);
  }, [markdown]);

  const handleLoaded = useCallback(() => {
    skipChange.current = true;
  }, []);

  const handleChange = useCallback(() => {
    const editor = editorRef.current;
    if (!editor) return;
    if (skipChange.current) {
      skipChange.current = false;
      return;
    }
    const next = editorToMarkdown(editor);
    lastPushed.current = next;
    onMarkdownChange(next);
  }, [onMarkdownChange]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
    <LexicalComposer initialConfig={editorConfig as never} key={chapterId}>
      <Toolbar fontFamily={fontFamily} fontSize={fontSize} onFontFamily={onFontFamily} onFontSize={onFontSize} />
      <EditorBridge
        onReady={(editor) => {
          editorRef.current = editor;
          onReady?.({
            insertImage: (src, alt) => {
              skipChange.current = false;
              editor.dispatchCommand(INSERT_CHAPTER_IMAGE_COMMAND, { src, alt });
              return true;
            },
          });
        }}
      />
      <LoadMarkdownPlugin markdown={markdown} revision={loadRevision} onLoaded={handleLoaded} />
      <EditablePlugin enabled={editable} />
      <HistoryPlugin />
      <ListPlugin />
      <TablePlugin />
      <ImageInsertPlugin />
      <div className="relative flex-1 overflow-y-auto bg-background-200/50 px-4 py-4">
        <RichTextPlugin
          contentEditable={
            <ContentEditable
              aria-label="章节正文编辑器"
              className="lex-editor word-sheet mx-auto min-h-[620px] max-w-3xl rounded-sm px-10 py-10"
            />
          }
          placeholder={
            <div className="pointer-events-none absolute left-1/2 top-24 w-full max-w-3xl -translate-x-1/2 px-10 text-[13px] text-foreground-400">
              点击右上角「AI 生成」自动撰写，或直接在此编辑。右侧图片点「插入」会放在当前光标处。
            </div>
          }
          ErrorBoundary={LexicalErrorBoundary}
        />
      </div>
      <OnChangePlugin onChange={handleChange} ignoreSelectionChange />
    </LexicalComposer>
    </div>
  );
}

function EditorBridge({ onReady }: { onReady: (editor: LexicalEditor) => void }) {
  const [editor] = useLexicalComposerContext();
  useEffect(() => {
    onReady(editor);
  }, [editor, onReady]);
  return null;
}
