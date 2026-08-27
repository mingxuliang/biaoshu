import { useCallback, useEffect, useRef, useState } from "react";
import type { OutlineNode } from "@/lib/api";
import { displayOutlineTitle, renumberOutline } from "@/lib/outlineNum";

interface OutlineTreeProps {
  nodes: OutlineNode[];
  activeId: string;
  onSelect: (id: string) => void;
  onNodesChange: (nodes: OutlineNode[]) => void;
  onKnowledge: (id: string) => void;
  knowledgeCounts?: Record<string, number>;
  locateHint?: string;
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

function getNodeLevel(nodes: OutlineNode[], nodeId: string): number {
  const node = nodes.find((n) => n.id === nodeId);
  if (!node || !node.parentId) return 0;
  return 1 + getNodeLevel(nodes, node.parentId);
}

function getSiblings(nodes: OutlineNode[], nodeId: string): OutlineNode[] {
  const node = nodes.find((n) => n.id === nodeId);
  if (!node) return [];
  return node.parentId === null ? getTopLevelNodes(nodes) : getChildren(nodes, node.parentId);
}

function nextNum(nodes: OutlineNode[], parentId: string | null): string {
  const count = parentId === null ? getTopLevelNodes(nodes).length : getChildren(nodes, parentId).length;
  return String(count + 1);
}

function getVisible(nodes: OutlineNode[]): OutlineNode[] {
  const out: OutlineNode[] = [];
  const walk = (parentId: string | null) => {
    const kids = parentId === null ? getTopLevelNodes(nodes) : getChildren(nodes, parentId);
    for (const n of kids) {
      out.push(n);
      if (n.expanded) walk(n.id);
    }
  };
  walk(null);
  return out;
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
    idea: "请描述本章编写思路…",
    aiIdea: "围绕评分点补充结构化的编写思路…",
    optimized: false,
    status: "待生成",
    words: 0,
    aiRounds: 0,
  };
}

export default function OutlineTree({
  nodes,
  activeId,
  onSelect,
  onNodesChange,
  onKnowledge,
  knowledgeCounts = {},
  locateHint = "点击章节定位到对应编写思路；招标文件页可锚定原文条款",
}: OutlineTreeProps) {
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const menuRef = useRef<HTMLDivElement>(null);
  const editRef = useRef<HTMLInputElement>(null);

  const visible = getVisible(nodes);
  const knowledgeCount = nodes.filter((n) => (knowledgeCounts[n.id] ?? 0) > 0).length;

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setContextMenu(null);
    };
    if (contextMenu) {
      document.addEventListener("mousedown", onDown);
      return () => document.removeEventListener("mousedown", onDown);
    }
  }, [contextMenu]);

  useEffect(() => {
    if (editingId && editRef.current) {
      editRef.current.focus();
      editRef.current.select();
    }
  }, [editingId]);

  const toggle = useCallback(
    (id: string) => onNodesChange(nodes.map((n) => (n.id === id ? { ...n, expanded: !n.expanded } : n))),
    [nodes, onNodesChange]
  );

  const handleAction = useCallback(
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
        case "rename":
          setEditingId(nodeId);
          setEditValue(displayOutlineTitle(node.title, node.num));
          break;
        case "moveUp":
        case "moveDown": {
          const sibs = getSiblings(nodes, nodeId);
          const idx = sibs.findIndex((s) => s.id === nodeId);
          const target = action === "moveUp" ? idx - 1 : idx + 1;
          if (idx < 0 || target < 0 || target >= sibs.length) break;
          const otherId = sibs[target].id;
          const flat = [...nodes];
          const a = flat.findIndex((n) => n.id === nodeId);
          const b = flat.findIndex((n) => n.id === otherId);
          [flat[a], flat[b]] = [flat[b], flat[a]];
          onNodesChange(renumberOutline(flat));
          break;
        }
        case "addSibling": {
          const newId = `p-${Date.now()}`;
          const expanded = node.parentId === null ? { ...node, expanded: true } : node;
          const flat = nodes.map((n) => (n.id === nodeId ? expanded : n));
          const insertIdx = flat.findIndex((n) => n.id === nodeId);
          const base = newNode(newId, nextNum(flat, node.parentId), node.parentId === null ? "新增章节" : "新增小节", node.parentId);
          flat.splice(insertIdx + 1, 0, base);
          onNodesChange(renumberOutline(flat));
          onSelect(newId);
          break;
        }
        case "addChild": {
          const newId = `p-${Date.now()}`;
          const expanded = nodes.map((n) => (n.id === nodeId ? { ...n, expanded: true } : n));
          const base = newNode(newId, nextNum(expanded, nodeId), "新增小节", nodeId);
          const flat = [...expanded];
          const insertIdx = flat.findIndex((n) => n.id === nodeId);
          const lastChildIdx = flat.reduce((last, n, i) => (n.parentId === nodeId ? i : last), insertIdx);
          flat.splice(lastChildIdx + 1, 0, base);
          onNodesChange(renumberOutline(flat));
          onSelect(newId);
          break;
        }
        case "delete": {
          const del = new Set<string>();
          const collect = (id: string) => {
            del.add(id);
            getChildren(nodes, id).forEach((c) => collect(c.id));
          };
          collect(nodeId);
          const next = nodes.filter((n) => !del.has(n.id));
          onNodesChange(renumberOutline(next));
          if (del.has(activeId)) onSelect(next[0]?.id ?? "");
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

  const showMenu = useCallback((e: React.MouseEvent, nodeId: string) => {
    e.stopPropagation();
    e.preventDefault();
    setContextMenu({ nodeId, x: e.clientX, y: e.clientY });
  }, []);

  return (
    <div className="flex h-full w-64 shrink-0 flex-col rounded-lg border border-background-300 bg-background-100 lg:w-72">
      <div className="border-b border-background-300 px-3 py-2.5">
        <div className="flex items-center justify-between">
          <h3 className="flex items-center gap-1.5 text-xs font-semibold text-foreground-700">
            <i className="ri-list-unordered text-sm text-primary-500"></i>
            章节目录
          </h3>
          <span className="font-label text-xs font-medium text-foreground-500">{nodes.length} 章</span>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-foreground-500">
          <span className="flex items-center gap-1">
            <i className="ri-bookmark-line text-primary-500"></i>
            已绑定知识库 {knowledgeCount}/{nodes.length}
          </span>
        </div>
      </div>

      <div className="flex-1 space-y-0 overflow-y-auto py-1">
        {visible.map((node) => {
          const active = node.id === activeId;
          const level = getNodeLevel(nodes, node.id);
          const hasChild = getChildren(nodes, node.id).length > 0;
          const isEditing = editingId === node.id;
          const hasKb = (knowledgeCounts[node.id] ?? 0) > 0;

          return (
            <div
              key={node.id}
              className={`group relative flex cursor-pointer items-start gap-1 py-1.5 pr-1 transition-colors ${
                active ? "bg-primary-50" : "hover:bg-background-50"
              }`}
              style={{ paddingLeft: `${level * 16 + 8}px` }}
              onClick={() => {
                if (!isEditing) onSelect(node.id);
              }}
              onContextMenu={(e) => showMenu(e, node.id)}
            >
              {hasChild ? (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    toggle(node.id);
                  }}
                  className="mt-0.5 flex h-4 w-4 shrink-0 cursor-pointer items-center justify-center rounded text-foreground-400 hover:text-foreground-600"
                >
                  <i className={`ri-arrow-right-s-line text-xs transition-transform ${node.expanded ? "rotate-90" : ""}`}></i>
                </button>
              ) : (
                <span className="mt-0.5 h-4 w-4 shrink-0"></span>
              )}

              <span className={`font-label mt-0.5 min-w-[2.75rem] shrink-0 text-right text-[11px] leading-snug ${active ? "text-primary-600" : "text-foreground-500"}`}>
                {node.num}
              </span>

              {isEditing ? (
                <input
                  ref={editRef}
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
                <span className={`min-w-0 flex-1 whitespace-normal break-words text-xs leading-snug ${active ? "font-medium text-primary-700" : "text-foreground-700"}`}>
                  {displayOutlineTitle(node.title, node.num)}
                </span>
              )}

              {!isEditing && (
                <>
                  {hasKb && (
                    <span className="shrink-0 text-[10px] text-primary-500">
                      <i className="ri-bookmark-3-fill"></i>
                    </span>
                  )}
                  <button
                    type="button"
                    title="设置参考知识库"
                    onClick={(e) => {
                      e.stopPropagation();
                      onKnowledge(node.id);
                    }}
                    className="flex h-5 w-5 shrink-0 cursor-pointer items-center justify-center rounded text-foreground-400 hover:bg-primary-50 hover:text-primary-500"
                  >
                    <i className="ri-bookmark-line text-xs"></i>
                  </button>
                  <div className="hidden items-center gap-0.5 group-hover:flex">
                    <button
                      type="button"
                      title="更多操作"
                      onClick={(e) => showMenu(e, node.id)}
                      className="flex h-5 w-5 shrink-0 cursor-pointer items-center justify-center rounded text-foreground-400 hover:bg-background-200 hover:text-foreground-700"
                    >
                      <i className="ri-more-fill text-xs"></i>
                    </button>
                  </div>
                </>
              )}
            </div>
          );
        })}

        {visible.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center gap-1 px-4 py-8 text-center text-xs text-foreground-500">
            <i className="ri-file-list-3-line text-lg text-foreground-400"></i>
            暂无目录，请先在右侧生成目录
          </div>
        )}
      </div>

      <div className="border-t border-background-300 px-3 py-2.5 text-[11px] text-foreground-500">
        <i className="ri-sparkling-2-line mr-1 text-primary-500"></i>
        {locateHint}
      </div>

      {contextMenu && (
        <div
          ref={menuRef}
          className="fixed z-50 w-44 overflow-hidden rounded-lg border border-background-300 bg-background-50 py-1 shadow-lg"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          <button type="button" className="flex w-full cursor-pointer items-center gap-2 px-3 py-1.5 text-xs text-foreground-700 transition-colors hover:bg-background-100" onClick={() => handleAction("rename")}>
            <i className="ri-edit-line text-xs text-foreground-500"></i>修改节点名称
          </button>
          <button type="button" className="flex w-full cursor-pointer items-center gap-2 px-3 py-1.5 text-xs text-foreground-700 transition-colors hover:bg-background-100" onClick={() => onKnowledge(contextMenu.nodeId)}>
            <i className="ri-bookmark-line text-xs text-primary-500"></i>设置参考知识库
          </button>
          <div className="mx-2 my-1 border-t border-background-200"></div>
          <button type="button" className="flex w-full cursor-pointer items-center gap-2 px-3 py-1.5 text-xs text-foreground-700 transition-colors hover:bg-background-100" onClick={() => handleAction("moveUp")}>
            <i className="ri-arrow-up-line text-xs text-foreground-500"></i>上移
          </button>
          <button type="button" className="flex w-full cursor-pointer items-center gap-2 px-3 py-1.5 text-xs text-foreground-700 transition-colors hover:bg-background-100" onClick={() => handleAction("moveDown")}>
            <i className="ri-arrow-down-line text-xs text-foreground-500"></i>下移
          </button>
          <div className="mx-2 my-1 border-t border-background-200"></div>
          <button type="button" className="flex w-full cursor-pointer items-center gap-2 px-3 py-1.5 text-xs text-foreground-700 transition-colors hover:bg-background-100" onClick={() => handleAction("addSibling")}>
            <i className="ri-add-line text-xs text-primary-500"></i>添加章节
          </button>
          <button type="button" className="flex w-full cursor-pointer items-center gap-2 px-3 py-1.5 text-xs text-foreground-700 transition-colors hover:bg-background-100" onClick={() => handleAction("addChild")}>
            <i className="ri-node-tree text-xs text-primary-500"></i>添加子章节
          </button>
          <div className="mx-2 my-1 border-t border-background-200"></div>
          <button type="button" className="flex w-full cursor-pointer items-center gap-2 px-3 py-1.5 text-xs text-red-600 transition-colors hover:bg-red-50" onClick={() => handleAction("delete")}>
            <i className="ri-delete-bin-line text-xs"></i>删除
          </button>
        </div>
      )}
    </div>
  );
}
