import { useCallback, useEffect, useRef, useState } from "react";
import type { OutlineNode } from "@/lib/api";
import { displayOutlineTitle, isOriginalFormTitle, renumberOutline } from "@/lib/outlineNum";

interface ChapterTreeProps {
  nodes: OutlineNode[];
  activeId: string;
  generatingId: string | null;
  onSelect: (id: string) => void;
  onGenerate: (id: string) => void;
  onNodesChange: (nodes: OutlineNode[]) => void;
}

type MenuAction = "rename" | "moveUp" | "moveDown" | "addSibling" | "addChild" | "delete";

interface ContextMenuState {
  nodeId: string;
  x: number;
  y: number;
}

function getTopLevelNodes(nodes: OutlineNode[]): OutlineNode[] {
  return nodes.filter((n) => n.parentId === null);
}

function getChildren(nodes: OutlineNode[], parentId: string): OutlineNode[] {
  return nodes.filter((n) => n.parentId === parentId);
}

function hasChildren(nodes: OutlineNode[], parentId: string): boolean {
  return nodes.some((n) => n.parentId === parentId);
}

function getVisibleNodes(nodes: OutlineNode[]): OutlineNode[] {
  const result: OutlineNode[] = [];
  const walk = (parentId: string | null) => {
    const kids = parentId === null ? getTopLevelNodes(nodes) : getChildren(nodes, parentId);
    for (const n of kids) {
      result.push(n);
      if (n.expanded) walk(n.id);
    }
  };
  walk(null);
  return result;
}

function getNodeLevel(nodes: OutlineNode[], nodeId: string): number {
  const node = nodes.find((n) => n.id === nodeId);
  if (!node || !node.parentId) return 0;
  return 1 + getNodeLevel(nodes, node.parentId);
}

function getSiblings(nodes: OutlineNode[], nodeId: string): OutlineNode[] {
  const node = nodes.find((n) => n.id === nodeId);
  if (!node) return [];
  if (node.parentId === null) return getTopLevelNodes(nodes);
  return getChildren(nodes, node.parentId);
}

function newNode(id: string, num: string, title: string, parentId: string | null): OutlineNode {
  return {
    id,
    num,
    title,
    parentId,
    expanded: false,
    weight: 0,
    dimension: null,
    idea: "",
    aiIdea: "",
    optimized: false,
    status: "待生成",
    words: 0,
    aiRounds: 0,
  };
}

export default function ChapterTree({
  nodes,
  activeId,
  generatingId,
  onSelect,
  onGenerate,
  onNodesChange,
}: ChapterTreeProps) {
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const menuRef = useRef<HTMLDivElement>(null);
  const editInputRef = useRef<HTMLInputElement>(null);

  const visibleNodes = getVisibleNodes(nodes);
  const doneCount = nodes.filter((n) => n.status === "已完成" || n.status === "用原文").length;
  const percent = Math.round((doneCount / Math.max(nodes.length, 1)) * 100);

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setContextMenu(null);
      }
    };
    if (contextMenu) {
      document.addEventListener("mousedown", handleClick);
      return () => document.removeEventListener("mousedown", handleClick);
    }
  }, [contextMenu]);

  useEffect(() => {
    if (editingId && editInputRef.current) {
      editInputRef.current.focus();
      editInputRef.current.select();
    }
  }, [editingId]);

  const toggleExpand = useCallback(
    (id: string) => {
      onNodesChange(nodes.map((n) => (n.id === id ? { ...n, expanded: !n.expanded } : n)));
    },
    [nodes, onNodesChange]
  );

  const handleMenuAction = useCallback(
    (action: MenuAction) => {
      if (!contextMenu) return;
      const nodeId = contextMenu.nodeId;
      const node = nodes.find((n) => n.id === nodeId);
      if (!node) {
        setContextMenu(null);
        return;
      }

      setContextMenu(null);

      switch (action) {
        case "rename": {
          setEditingId(nodeId);
          setEditValue(displayOutlineTitle(node.title, node.num));
          break;
        }
        case "moveUp": {
          const siblings = getSiblings(nodes, nodeId);
          const idx = siblings.findIndex((s) => s.id === nodeId);
          if (idx <= 0) break;
          const prevId = siblings[idx - 1].id;
          const flat = [...nodes];
          const aIdx = flat.findIndex((n) => n.id === nodeId);
          const bIdx = flat.findIndex((n) => n.id === prevId);
          if (aIdx >= 0 && bIdx >= 0) {
            [flat[aIdx], flat[bIdx]] = [flat[bIdx], flat[aIdx]];
            onNodesChange(renumberOutline(flat));
          }
          break;
        }
        case "moveDown": {
          const siblings = getSiblings(nodes, nodeId);
          const idx = siblings.findIndex((s) => s.id === nodeId);
          if (idx < 0 || idx >= siblings.length - 1) break;
          const nextId = siblings[idx + 1].id;
          const flat = [...nodes];
          const aIdx = flat.findIndex((n) => n.id === nodeId);
          const bIdx = flat.findIndex((n) => n.id === nextId);
          if (aIdx >= 0 && bIdx >= 0) {
            [flat[aIdx], flat[bIdx]] = [flat[bIdx], flat[aIdx]];
            onNodesChange(renumberOutline(flat));
          }
          break;
        }
        case "addSibling": {
          const newId = `c-${Date.now()}`;
          const siblings = getSiblings(nodes, nodeId);
          const isTop = node.parentId === null;
          const newNum = isTop
            ? String(siblings.length + 1)
            : `（${["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"][siblings.length] || "新"}）`;
          const created = newNode(newId, newNum, "新建章节", node.parentId);
          const flat = [...nodes];
          const insertIdx = flat.findIndex((n) => n.id === nodeId);
          flat.splice(insertIdx + 1, 0, created);
          onNodesChange(renumberOutline(flat));
          onSelect(newId);
          break;
        }
        case "addChild": {
          const expandedNodes = nodes.map((n) => (n.id === nodeId ? { ...n, expanded: true } : n));
          const children = getChildren(expandedNodes, nodeId);
          const newId = `c-${Date.now()}`;
          const newNum = `（${["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"][children.length] || "新"}）`;
          const created = newNode(newId, newNum, "新建子章节", nodeId);
          const flat = [...expandedNodes];
          const insertIdx = flat.findIndex((n) => n.id === nodeId);
          const lastChildIdx = flat.reduce((last, n, i) => (n.parentId === nodeId ? i : last), insertIdx);
          flat.splice(lastChildIdx + 1, 0, created);
          onNodesChange(renumberOutline(flat));
          onSelect(newId);
          break;
        }
        case "delete": {
          const toDelete = new Set<string>();
          const collect = (id: string) => {
            toDelete.add(id);
            getChildren(nodes, id).forEach((c) => collect(c.id));
          };
          collect(nodeId);
          const next = nodes.filter((n) => !toDelete.has(n.id));
          onNodesChange(renumberOutline(next));
          if (activeId === nodeId || toDelete.has(activeId)) {
            const first = next[0];
            if (first) onSelect(first.id);
          }
          break;
        }
      }
    },
    [contextMenu, nodes, onNodesChange, onSelect, activeId]
  );

  const finishRename = useCallback(() => {
    if (editingId) {
      onNodesChange(nodes.map((n) => (n.id === editingId ? { ...n, title: editValue || n.title } : n)));
    }
    setEditingId(null);
    setEditValue("");
  }, [editingId, editValue, nodes, onNodesChange]);

  const showContextMenu = useCallback((e: React.MouseEvent, nodeId: string) => {
    e.stopPropagation();
    e.preventDefault();
    setContextMenu({ nodeId, x: e.clientX, y: e.clientY });
  }, []);

  return (
    <div className="flex w-64 shrink-0 flex-col rounded-lg border border-background-300 bg-background-100 lg:w-72">
      {/* 章节头部 */}
      <div className="border-b border-background-300 px-3 py-2.5">
        <div className="flex items-center justify-between">
          <h3 className="flex items-center gap-1.5 text-xs font-semibold text-foreground-700">
            <i className="ri-list-unordered text-sm text-primary-500"></i>
            章节大纲
          </h3>
          <span className="font-label text-xs font-medium text-foreground-500">
            {doneCount}/{nodes.length}
          </span>
        </div>
        <div className="mt-2 flex items-center gap-2">
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-background-200">
            <div
              className="h-full rounded-full bg-gradient-to-r from-primary-500 to-primary-400 transition-all"
              style={{ width: `${percent}%` }}
            />
          </div>
          <span className="font-label text-xs font-medium text-primary-600">{percent}%</span>
        </div>
      </div>

      {/* 树形列表 */}
      <div className="flex-1 space-y-0 overflow-y-auto py-1">
        {visibleNodes.map((node) => {
          const active = node.id === activeId;
          const generating = node.id === generatingId;
          const level = getNodeLevel(nodes, node.id);
          const expandable = hasChildren(nodes, node.id);
          const isEditing = editingId === node.id;

          return (
            <div
              key={node.id}
              className={`group relative flex cursor-pointer items-start gap-1 py-1.5 pr-2 transition-colors ${
                active ? "bg-primary-50" : "hover:bg-background-50"
              }`}
              style={{ paddingLeft: `${level * 16 + 8}px` }}
              onClick={() => {
                if (!isEditing) onSelect(node.id);
              }}
              onContextMenu={(e) => showContextMenu(e, node.id)}
            >
              {/* 展开/收起指示器 */}
              {expandable ? (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    toggleExpand(node.id);
                  }}
                  className="mt-0.5 flex h-4 w-4 shrink-0 cursor-pointer items-center justify-center rounded text-foreground-400 hover:text-foreground-600"
                >
                  <i
                    className={`ri-arrow-right-s-line text-xs transition-transform ${
                      node.expanded ? "rotate-90" : ""
                    }`}
                  ></i>
                </button>
              ) : (
                <span className="mt-0.5 h-4 w-4 shrink-0"></span>
              )}

              {/* 状态指示 */}
              {generating ? (
                <span className="flex h-3.5 w-3.5 shrink-0 items-center justify-center">
                  <i className="ri-loader-4-line text-[10px] text-accent-500 animate-spin"></i>
                </span>
              ) : node.status === "已完成" ? (
                <span className="flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-primary-400 to-primary-600 text-background-50">
                  <i className="ri-check-line text-[8px]"></i>
                </span>
              ) : node.status === "用原文" || isOriginalFormTitle(node.title, node.num) ? (
                <span className="flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full bg-secondary-100 text-secondary-600">
                  <i className="ri-file-text-line text-[8px]"></i>
                </span>
              ) : node.status === "生成中" ? (
                <span className="flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full bg-accent-50 text-accent-500">
                  <i className="ri-loader-4-line text-[8px] animate-spin"></i>
                </span>
              ) : (
                <span className="flex h-3.5 w-3.5 shrink-0 items-center justify-center">
                  <i className="ri-circle-line text-[8px] text-foreground-400"></i>
                </span>
              )}

              {/* 章节编号 */}
              <span
                className={`font-label mt-0.5 min-w-[2.75rem] shrink-0 text-right text-[11px] leading-snug ${
                  active ? "text-primary-600" : "text-foreground-500"
                }`}
              >
                {node.num}
              </span>

              {/* 标题 / 编辑框 */}
              {isEditing ? (
                <input
                  ref={editInputRef}
                  value={editValue}
                  onChange={(e) => setEditValue(e.target.value)}
                  onBlur={finishRename}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") finishRename();
                    if (e.key === "Escape") {
                      setEditingId(null);
                      setEditValue("");
                    }
                  }}
                  className="min-w-0 flex-1 rounded border border-primary-300 bg-background-50 px-1.5 py-0.5 text-xs text-foreground-900 outline-none"
                  onClick={(e) => e.stopPropagation()}
                />
              ) : (
                <span
                  className={`min-w-0 flex-1 whitespace-normal break-words text-xs leading-snug ${
                    active ? "font-medium text-primary-700" : "text-foreground-700"
                  }`}
                >
                  {displayOutlineTitle(node.title, node.num)}
                </span>
              )}

              {/* 悬停操作 */}
              {!isEditing && (
                <div className="hidden items-center gap-0.5 group-hover:flex">
                  {node.status === "待生成" && !isOriginalFormTitle(node.title, node.num) && (
                    <button
                      type="button"
                      title="AI 生成本章"
                      onClick={(e) => {
                        e.stopPropagation();
                        onGenerate(node.id);
                      }}
                      className="flex h-5 w-5 cursor-pointer items-center justify-center rounded text-foreground-500 hover:bg-primary-50 hover:text-primary-500"
                    >
                      <i className="ri-sparkling-2-line text-xs"></i>
                    </button>
                  )}
                  <button
                    type="button"
                    title="更多操作"
                    onClick={(e) => showContextMenu(e, node.id)}
                    className="flex h-5 w-5 cursor-pointer items-center justify-center rounded text-foreground-400 hover:bg-background-200 hover:text-foreground-700"
                  >
                    <i className="ri-more-fill text-xs"></i>
                  </button>
                </div>
              )}
            </div>
          );
        })}

        {visibleNodes.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center gap-1 px-4 py-8 text-center text-xs text-foreground-500">
            <i className="ri-file-list-3-line text-lg text-foreground-400"></i>
            暂无章节，请先在目录生成步骤中生成目录
          </div>
        )}
      </div>

      {/* 底部说明 */}
      <div className="border-t border-background-300 px-3 py-2.5 text-[11px] text-foreground-500">
        <i className="ri-sparkling-2-line mr-1 text-primary-500"></i>
        功能点逐条对应；其余需求用应标目录覆盖全文，不照搬招标目录
      </div>

      {/* 上下文菜单 */}
      {contextMenu && (
        <div
          ref={menuRef}
          className="fixed z-50 w-40 overflow-hidden rounded-lg border border-background-300 bg-background-50 py-1 shadow-lg"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          <button
            type="button"
            className="flex w-full cursor-pointer items-center gap-2 px-3 py-1.5 text-xs text-foreground-700 transition-colors hover:bg-background-100"
            onClick={() => handleMenuAction("rename")}
          >
            <i className="ri-edit-line text-xs text-foreground-500"></i>
            修改节点名称
          </button>
          <div className="mx-2 my-1 border-t border-background-200"></div>
          <button
            type="button"
            className="flex w-full cursor-pointer items-center gap-2 px-3 py-1.5 text-xs text-foreground-700 transition-colors hover:bg-background-100"
            onClick={() => handleMenuAction("moveUp")}
          >
            <i className="ri-arrow-up-line text-xs text-foreground-500"></i>
            上移
          </button>
          <button
            type="button"
            className="flex w-full cursor-pointer items-center gap-2 px-3 py-1.5 text-xs text-foreground-700 transition-colors hover:bg-background-100"
            onClick={() => handleMenuAction("moveDown")}
          >
            <i className="ri-arrow-down-line text-xs text-foreground-500"></i>
            下移
          </button>
          <div className="mx-2 my-1 border-t border-background-200"></div>
          <button
            type="button"
            className="flex w-full cursor-pointer items-center gap-2 px-3 py-1.5 text-xs text-foreground-700 transition-colors hover:bg-background-100"
            onClick={() => handleMenuAction("addSibling")}
          >
            <i className="ri-add-line text-xs text-primary-500"></i>
            添加章节
          </button>
          <button
            type="button"
            className="flex w-full cursor-pointer items-center gap-2 px-3 py-1.5 text-xs text-foreground-700 transition-colors hover:bg-background-100"
            onClick={() => handleMenuAction("addChild")}
          >
            <i className="ri-node-tree text-xs text-primary-500"></i>
            添加子章节
          </button>
          <div className="mx-2 my-1 border-t border-background-200"></div>
          <button
            type="button"
            className="flex w-full cursor-pointer items-center gap-2 px-3 py-1.5 text-xs text-red-600 transition-colors hover:bg-red-50"
            onClick={() => handleMenuAction("delete")}
          >
            <i className="ri-delete-bin-line text-xs"></i>
            删除
          </button>
        </div>
      )}
    </div>
  );
}
