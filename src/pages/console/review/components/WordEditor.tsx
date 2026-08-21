import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import { LexicalComposer } from "@lexical/react/LexicalComposer";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { RichTextPlugin } from "@lexical/react/LexicalRichTextPlugin";
import { HistoryPlugin } from "@lexical/react/LexicalHistoryPlugin";
import { ContentEditable } from "@lexical/react/LexicalContentEditable";
import { OnChangePlugin } from "@lexical/react/LexicalOnChangePlugin";
import { ListPlugin } from "@lexical/react/LexicalListPlugin";
import { TablePlugin } from "@lexical/react/LexicalTablePlugin";
import { LinkPlugin } from "@lexical/react/LexicalLinkPlugin";
import {
  ListNode,
  ListItemNode,
  INSERT_ORDERED_LIST_COMMAND,
  INSERT_UNORDERED_LIST_COMMAND,
} from "@lexical/list";
import { LinkNode, TOGGLE_LINK_COMMAND } from "@lexical/link";
import { TableNode, TableRowNode, TableCellNode, INSERT_TABLE_COMMAND } from "@lexical/table";
import { $patchStyleText, $setBlocksType } from "@lexical/selection";
import {
  $createParagraphNode,
  $createTextNode,
  $getRoot,
  $getSelection,
  $isElementNode,
  $isRangeSelection,
  $isTextNode,
  FORMAT_TEXT_COMMAND,
  FORMAT_ELEMENT_COMMAND,
  UNDO_COMMAND,
  REDO_COMMAND,
  type LexicalEditor,
  type LexicalNode,
  type SerializedEditorState,
  type TextFormatType,
} from "lexical";
import { $createHeadingNode, $isHeadingNode, HeadingNode } from "@lexical/rich-text";
import type { BidSection } from "@/lib/api";
import type { PreReviewIssue } from "@/mocks/preReview";
import { LexicalErrorBoundary } from "@lexical/react/LexicalErrorBoundary";

export interface RevisionBlock {
  type: "heading" | "paragraph";
  level?: number;
  text: string;
}

export interface SerializedRevisionContent {
  contentState: SerializedEditorState;
  blocks: RevisionBlock[];
  wordCount: number;
}

export interface WordEditorHandle {
  scrollToSection: (sectionId: string) => void;
  scrollToIssue: (issueId: string) => void;
  getSerializedContent: () => SerializedRevisionContent | null;
}

interface WordEditorProps {
  sections: BidSection[];
  issues: PreReviewIssue[];
  editMode: boolean;
  onIssueClick: (issueId: string) => void;
  initialContentState?: Record<string, unknown> | null;
  onAutosave?: (content: SerializedRevisionContent) => void;
}

const severityInline: Record<string, { bg: string; color: string }> = {
  废标: { bg: "rgba(255,77,79,0.30)", color: "#c0392b" },
  降档: { bg: "rgba(255,140,0,0.28)", color: "#b35900" },
  扣分: { bg: "rgba(245,178,0,0.30)", color: "#96700a" },
  建议: { bg: "rgba(40,120,255,0.22)", color: "#1d5bbf" },
};

const fontSizeOptions = [12, 14, 16, 18, 22, 26, 32];

/* 构建初始文档：章节标题 + 段落，问题句原地高亮 */
function buildInitialState(
  editor: LexicalEditor,
  sections: BidSection[],
  issues: PreReviewIssue[],
  anchorMapRef: { current: Record<string, string> },
) {
  const issueMap = new Map(issues.map((i) => [i.id, i]));
  editor.update(() => {
    const root = $getRoot();
    root.clear();
    sections.forEach((section) => {
      const level = section.level === 1 ? "h1" : section.level === 2 ? "h2" : "h3";
      const heading = $createHeadingNode(level);
      heading.append($createTextNode(section.heading));
      anchorMapRef.current[section.id] = heading.getKey();
      root.append(heading);

      section.paragraphs.forEach((para) => {
        const p = $createParagraphNode();
        if (para.problem) {
          const issue = issueMap.get(para.problem.issueId);
          const style = severityInline[issue?.severity || "建议"] || severityInline.建议;
          const parts = para.text.split(para.problem.highlight);
          parts.forEach((part, idx) => {
            if (part) p.append($createTextNode(part));
            if (idx < parts.length - 1) {
              const hl = $createTextNode(para.problem.highlight);
              hl.setStyle(`background-color:${style.bg};color:${style.color};border-radius:3px;padding:0 1px;`);
              anchorMapRef.current[para.problem!.issueId] = hl.getKey();
              p.append(hl);
            }
          });
        } else {
          p.append($createTextNode(para.text));
        }
        root.append(p);
      });
    });
  });
}

/* 重建章节/问题锚点：兼顾「按 sections 首建」与「从 contentState 恢复」两条路径，
   通过标题顺序对应 section，通过高亮文本反查 issueId 对应问题句 */
function rebuildAnchorMap(
  editor: LexicalEditor,
  sections: BidSection[],
  anchorMapRef: { current: Record<string, string> },
) {
  const highlightToIssueId = new Map<string, string>();
  sections.forEach((s) =>
    s.paragraphs.forEach((p) => {
      if (p.problem) highlightToIssueId.set(p.problem.highlight, p.problem.issueId);
    }),
  );
  const headingOrder = sections.map((s) => s.id);
  let headingIdx = 0;

  editor.getEditorState().read(() => {
    const root = $getRoot();
    root.getChildren().forEach((node: LexicalNode) => {
      if ($isHeadingNode(node)) {
        if (headingIdx < headingOrder.length) {
          anchorMapRef.current[headingOrder[headingIdx]] = node.getKey();
          headingIdx += 1;
        }
        return;
      }
      if (!$isElementNode(node)) return;
      node.getChildren().forEach((child: LexicalNode) => {
        if ($isTextNode(child) && child.getStyle()) {
          const issueId = highlightToIssueId.get(child.getTextContent());
          if (issueId && !anchorMapRef.current[issueId]) {
            anchorMapRef.current[issueId] = child.getKey();
          }
        }
      });
    });
  });
}

/* 把当前编辑器状态序列化为 {contentState, blocks, wordCount}，供保存版本/自动保存使用 */
function serializeContent(editor: LexicalEditor): SerializedRevisionContent {
  let blocks: RevisionBlock[] = [];
  let wordCount = 0;
  editor.getEditorState().read(() => {
    const root = $getRoot();
    blocks = root.getChildren().map((node: LexicalNode) => {
      if ($isHeadingNode(node)) {
        const level = Number(node.getTag().replace("h", "")) || 1;
        return { type: "heading" as const, level, text: node.getTextContent() };
      }
      return { type: "paragraph" as const, text: node.getTextContent() };
    });
    wordCount = root.getTextContent().length;
  });
  return { contentState: editor.getEditorState().toJSON(), blocks, wordCount };
}

function Toolbar({ editMode, onIssueClick }: { editMode: boolean; onIssueClick: (issueId: string) => void }) {
  const [editor] = useLexicalComposerContext();
  const [fontSize, setFontSize] = useState(14);
  const [brush, setBrush] = useState(false);
  const brushRef = useRef<{ format: number; style: string } | null>(null);

  const exec = (cmd: string) => {
    if (cmd === "bold") editor.dispatchCommand(FORMAT_TEXT_COMMAND, "bold");
    if (cmd === "italic") editor.dispatchCommand(FORMAT_TEXT_COMMAND, "italic");
    if (cmd === "underline") editor.dispatchCommand(FORMAT_TEXT_COMMAND, "underline");
    if (cmd === "strike") editor.dispatchCommand(FORMAT_TEXT_COMMAND, "strikethrough");
    if (cmd === "code") editor.dispatchCommand(FORMAT_TEXT_COMMAND, "code");
    if (cmd === "ul") editor.dispatchCommand(INSERT_UNORDERED_LIST_COMMAND, undefined);
    if (cmd === "ol") editor.dispatchCommand(INSERT_ORDERED_LIST_COMMAND, undefined);
    if (cmd === "alignLeft") editor.dispatchCommand(FORMAT_ELEMENT_COMMAND, "left");
    if (cmd === "alignCenter") editor.dispatchCommand(FORMAT_ELEMENT_COMMAND, "center");
    if (cmd === "alignRight") editor.dispatchCommand(FORMAT_ELEMENT_COMMAND, "right");
    if (cmd === "alignJustify") editor.dispatchCommand(FORMAT_ELEMENT_COMMAND, "justify");
    if (cmd === "undo") editor.dispatchCommand(UNDO_COMMAND, undefined);
    if (cmd === "redo") editor.dispatchCommand(REDO_COMMAND, undefined);
  };

  const setBlock = (type: "p" | "h1" | "h2" | "h3") => {
    editor.update(() => {
      const selection = $getSelection();
      if (!$isRangeSelection(selection)) return;
      const nodes = type === "p" ? [$createParagraphNode()] : [$createHeadingNode(type)];
      $setBlocksType(selection, () => nodes);
    });
  };

  const setFont = (size: number) => {
    setFontSize(size);
    editor.update(() => {
      const selection = $getSelection();
      if (!$isRangeSelection(selection)) return;
      $patchStyleText(selection, { "font-size": `${size}px` });
    });
  };

  const insertTable = () => {
    editor.dispatchCommand(INSERT_TABLE_COMMAND, { rows: 3, columns: 4, includeHeaders: true });
  };

  const addLink = () => {
    const url = window.prompt("输入链接地址：", "https://");
    if (!url) return;
    editor.dispatchCommand(TOGGLE_LINK_COMMAND, url);
  };

  /* 格式刷：记录当前选区格式 */
  const copyBrush = () => {
    editor.getEditorState().read(() => {
      const selection = $getSelection();
      if (!$isRangeSelection(selection)) return;
      const node = selection.getNodes().find($isTextNode);
      if (!node) return;
      brushRef.current = { format: node.getFormat(), style: node.getStyle() };
      setBrush(true);
    });
  };

  /* 格式刷：把记录的格式应用到当前选区 */
  const applyBrush = () => {
    if (!brushRef.current) return;
    const { format, style } = brushRef.current;
    editor.update(() => {
      const selection = $getSelection();
      if (!$isRangeSelection(selection)) return;
      selection.getNodes().forEach((n) => {
        if ($isTextNode(n)) {
          n.setFormat(format as TextFormatType | number);
          n.setStyle(style);
        }
      });
    });
    brushRef.current = null;
    setBrush(false);
  };

  const blockBtn =
    "flex h-7 cursor-pointer items-center gap-1 whitespace-nowrap rounded px-2 text-xs text-foreground-600 transition-colors hover:bg-background-200 hover:text-foreground-900";
  const iconBtn = "flex h-7 w-7 cursor-pointer items-center justify-center rounded text-sm text-foreground-600 transition-colors hover:bg-background-200 hover:text-foreground-900";

  return (
    <div className="flex flex-wrap items-center gap-1 border-b border-background-300 bg-background-100 px-2.5 py-1.5">
      <button type="button" title="撤销" onClick={() => exec("undo")} className={iconBtn}><i className="ri-arrow-go-back-line"></i></button>
      <button type="button" title="重做" onClick={() => exec("redo")} className={iconBtn}><i className="ri-arrow-go-forward-line"></i></button>
      <span className="mx-1 h-4 w-px bg-background-300" />
      <button type="button" title="格式刷" onClick={copyBrush} className={`${iconBtn} ${brush ? "bg-primary-100 text-primary-600" : ""}`}><i className="ri-brush-2-line"></i></button>
      {brush && (
        <button type="button" title="应用到当前选区" onClick={applyBrush} className="flex h-7 cursor-pointer items-center gap-1 whitespace-nowrap rounded bg-primary-500 px-2 text-xs font-medium text-background-50 transition-colors hover:bg-primary-600">
          应用格式刷
        </button>
      )}
      <span className="mx-1 h-4 w-px bg-background-300" />
      <select value={fontSize} onChange={(e) => setFont(Number(e.target.value))} className="h-7 cursor-pointer rounded border border-background-300 bg-background-50 px-1.5 text-xs text-foreground-700 outline-none">
        {fontSizeOptions.map((s) => <option key={s} value={s}>{s}px</option>)}
      </select>
      <span className="mx-1 h-4 w-px bg-background-300" />
      <button type="button" title="正文" onClick={() => setBlock("p")} className={blockBtn}>正文</button>
      <button type="button" title="一级标题" onClick={() => setBlock("h1")} className={blockBtn}>H1</button>
      <button type="button" title="二级标题" onClick={() => setBlock("h2")} className={blockBtn}>H2</button>
      <button type="button" title="三级标题" onClick={() => setBlock("h3")} className={blockBtn}>H3</button>
      <span className="mx-1 h-4 w-px bg-background-300" />
      <button type="button" title="加粗" onClick={() => exec("bold")} className={`${iconBtn} font-bold`}>B</button>
      <button type="button" title="斜体" onClick={() => exec("italic")} className={`${iconBtn} italic`}>I</button>
      <button type="button" title="下划线" onClick={() => exec("underline")} className={`${iconBtn} underline`}>U</button>
      <button type="button" title="删除线" onClick={() => exec("strike")} className={`${iconBtn} line-through`}>S</button>
      <button type="button" title="行内代码" onClick={() => exec("code")} className={iconBtn}><i className="ri-code-s-slash-line"></i></button>
      <span className="mx-1 h-4 w-px bg-background-300" />
      <button type="button" title="无序列表" onClick={() => exec("ul")} className={iconBtn}><i className="ri-list-unordered"></i></button>
      <button type="button" title="有序列表" onClick={() => exec("ol")} className={iconBtn}><i className="ri-list-ordered"></i></button>
      <button type="button" title="左对齐" onClick={() => exec("alignLeft")} className={iconBtn}><i className="ri-align-left"></i></button>
      <button type="button" title="居中" onClick={() => exec("alignCenter")} className={iconBtn}><i className="ri-align-center"></i></button>
      <button type="button" title="右对齐" onClick={() => exec("alignRight")} className={iconBtn}><i className="ri-align-right"></i></button>
      <button type="button" title="两端对齐" onClick={() => exec("alignJustify")} className={iconBtn}><i className="ri-align-justify"></i></button>
      <span className="mx-1 h-4 w-px bg-background-300" />
      <button type="button" title="插入链接" onClick={addLink} className={iconBtn}><i className="ri-link"></i></button>
      <button type="button" title="插入表格" onClick={insertTable} className={iconBtn}><i className="ri-table-2"></i></button>
      <div className="ml-auto flex items-center gap-1">
        {editMode ? (
          <span className="flex items-center gap-1 text-[11px] text-primary-600">
            <i className="ri-edit-line"></i>编辑中
          </span>
        ) : (
          <span className="flex items-center gap-1 text-[11px] text-foreground-500">
            <i className="ri-eye-line"></i>预览
          </span>
        )}
        <button
          type="button"
          title="一键锚定首个问题"
          onClick={() => onIssueClick("")}
          className="flex h-7 cursor-pointer items-center gap-1 whitespace-nowrap rounded-md border border-background-300 px-2 text-[11px] text-foreground-500 transition-colors hover:bg-background-200"
        >
          <i className="ri-focus-3-line text-xs"></i>
          锚定问题
        </button>
      </div>
    </div>
  );
}

const WordEditor = forwardRef<WordEditorHandle, WordEditorProps>(function WordEditor(
  { sections, issues, editMode, onIssueClick, initialContentState, onAutosave },
  ref,
) {
  const anchorMapRef = useRef<Record<string, string>>({});
  const editorRef = useRef<LexicalEditor | null>(null);
  const [editorReady, setEditorReady] = useState(false);
  const [wordCount, setWordCount] = useState(0);
  const autosaveTimerRef = useRef<number | null>(null);

  const editorConfig = useMemo(
    () => ({
      namespace: "bidword",
      nodes: [HeadingNode, ListNode, ListItemNode, LinkNode, TableNode, TableRowNode, TableCellNode],
      theme: {
        heading: {
          h1: "editor-heading-h1",
          h2: "editor-heading-h2",
          h3: "editor-heading-h3",
        },
        paragraph: "editor-paragraph",
        text: {
          bold: "editor-text-bold",
          italic: "editor-text-italic",
          underline: "editor-text-underline",
          strikethrough: "editor-text-strikethrough",
          code: "editor-text-code",
        },
        link: "editor-link",
      },
      onError: (error: unknown) => {
        console.error("Lexical error:", error);
      },
    }),
    [],
  );

  /* 编辑器初始化后构建文档内容：有 contentState 则恢复上次编辑状态，否则按真实段落首建 */
  useEffect(() => {
    if (!editorRef.current || !editorReady) return;
    const editor = editorRef.current;
    if (initialContentState) {
      try {
        const state = editor.parseEditorState(initialContentState as unknown as SerializedEditorState);
        editor.setEditorState(state);
      } catch (error) {
        console.error("恢复编辑器内容失败，回退为按段落重建：", error);
        buildInitialState(editor, sections, issues, anchorMapRef);
      }
    } else {
      buildInitialState(editor, sections, issues, anchorMapRef);
    }
    rebuildAnchorMap(editor, sections, anchorMapRef);
    setWordCount(serializeContent(editor).wordCount);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editorReady]);

  /* 编辑/预览切换 */
  useEffect(() => {
    editorRef.current?.setEditable(editMode);
  }, [editMode]);

  const scrollToKey = useCallback((key: string) => {
    if (!editorRef.current) return;
    const dom = editorRef.current.getElementByKey(key);
    if (dom) {
      dom.scrollIntoView({ behavior: "smooth", block: "center" });
      dom.classList.add("issue-flash");
      window.setTimeout(() => dom.classList.remove("issue-flash"), 3400);
    }
  }, []);

  useImperativeHandle(
    ref,
    () => ({
      scrollToSection: (sectionId: string) => {
        const key = anchorMapRef.current[sectionId];
        if (key) scrollToKey(key);
      },
      scrollToIssue: (issueId: string) => {
        const key = anchorMapRef.current[issueId];
        if (key) scrollToKey(key);
      },
      getSerializedContent: () => {
        if (!editorRef.current) return null;
        return serializeContent(editorRef.current);
      },
    }),
    [scrollToKey],
  );

  /* 编辑内容变化后 debounce 自动保存，避免每次按键都请求后端 */
  const handleChange = useCallback(() => {
    if (!editorRef.current) return;
    const content = serializeContent(editorRef.current);
    setWordCount(content.wordCount);
    if (!onAutosave) return;
    if (autosaveTimerRef.current) window.clearTimeout(autosaveTimerRef.current);
    autosaveTimerRef.current = window.setTimeout(() => {
      onAutosave(content);
    }, 6000);
  }, [onAutosave]);

  useEffect(() => {
    return () => {
      if (autosaveTimerRef.current) window.clearTimeout(autosaveTimerRef.current);
    };
  }, []);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <LexicalComposer initialConfig={editorConfig as never}>
        <Toolbar editMode={editMode} onIssueClick={onIssueClick} />
        <div className="flex-1 overflow-auto bg-background-200/50 px-6 py-6">
          <EditorBridge
            onReady={(editor) => {
              editorRef.current = editor;
              setEditorReady(true);
            }}
          />
          <HistoryPlugin />
          <ListPlugin />
          <TablePlugin />
          <LinkPlugin />
          <RichTextPlugin
            contentEditable={<ContentEditable aria-label="投标书编辑器" className="lex-editor word-sheet mx-auto max-w-[820px] px-10 py-12" />}
            placeholder={<div className="pointer-events-none absolute top-16 left-12 text-sm text-foreground-400">在空白处点击开始编辑…</div>}
            ErrorBoundary={LexicalErrorBoundary}
          />
          <OnChangePlugin onChange={handleChange} />
        </div>
      </LexicalComposer>
      <div className="flex items-center justify-between border-t border-background-300 bg-background-100 px-4 py-1.5 text-[11px] text-foreground-500">
        <span className="flex items-center gap-1"><i className="ri-file-word-2-line text-primary-500"></i>智标云投标书</span>
        <span className="flex items-center gap-3">
          <span>字数 {wordCount}</span>
          <span>第 1 页 / 共 1 页</span>
        </span>
      </div>
    </div>
  );
});

function EditorBridge({ onReady }: { onReady: (editor: LexicalEditor) => void }) {
  const [editor] = useLexicalComposerContext();
  useEffect(() => {
    onReady(editor);
  }, [editor, onReady]);
  return null;
}

export default WordEditor;