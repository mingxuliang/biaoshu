import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import Modal from "../components/Modal";
import Toast from "../components/Toast";
import PaginationBar from "../components/PaginationBar";
import AuthImage from "../components/AuthImage";
import { useAuth } from "@/context/AuthContext";
import { hasPerm } from "@/lib/permissions";
import {
  ApiError,
  getKnowledgeChapterDetail,
  getKnowledgeChapters,
  listKnowledgeDocuments,
  rechunkKnowledgeDocument,
  type KnowledgeChapter,
  type KnowledgeChapterDetail,
  type KnowledgeDoc,
} from "@/lib/api";

interface ToastState {
  message: string;
  type: "success" | "error" | "info";
  visible: boolean;
}

const PAGE_SIZE = 15;
const inputCls =
  "h-9 w-full rounded-md border border-background-300 bg-background-50 px-3 text-sm text-foreground-900 outline-none transition-all focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20 placeholder:text-foreground-500";
const labelCls = "mb-1.5 block text-xs font-medium text-foreground-600";

const typeIcon: Record<string, string> = {
  历史中标标书: "ri-file-chart-line",
  专项方案: "ri-file-settings-line",
  施工工艺: "ri-tools-line",
  规范条文: "ri-book-2-line",
  制度表单: "ri-file-list-3-line",
  图表模板: "ri-pie-chart-2-line",
};

function imageCountOf(ch: KnowledgeChapter): number {
  return (ch.imageCount ?? ch.images?.length ?? 0) + (ch.children || []).reduce((sum, child) => sum + imageCountOf(child), 0);
}

function childCountOf(ch: KnowledgeChapter): number {
  return (ch.children || []).length;
}

function tertiaryCountOf(ch: KnowledgeChapter): number {
  return (ch.children || []).reduce((sum, child) => sum + (child.children || []).length, 0);
}

export default function KnowledgeDocumentDetailPage() {
  const { docId = "" } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const canEdit = hasPerm(user?.role, "writer");
  const [doc, setDoc] = useState<KnowledgeDoc | null>(null);
  const [chapters, setChapters] = useState<KnowledgeChapter[]>([]);
  const [ready, setReady] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [rechunking, setRechunking] = useState(false);
  const [toast, setToast] = useState<ToastState>({ message: "", type: "success", visible: false });
  const [detail, setDetail] = useState<KnowledgeChapterDetail | null>(null);
  const [detailChild, setDetailChild] = useState<KnowledgeChapter | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const showToast = (message: string, type: ToastState["type"] = "success") => {
    setToast({ message, type, visible: true });
    window.setTimeout(() => setToast((t) => ({ ...t, visible: false })), 3000);
  };

  useEffect(() => {
    if (!docId) return;
    let cancelled = false;
    setReady(false);
    Promise.all([listKnowledgeDocuments(), getKnowledgeChapters(docId)])
      .then(([docs, chs]) => {
        if (cancelled) return;
        setDoc(docs.find((d) => d.id === docId) || null);
        setChapters(chs);
      })
      .catch(() => {
        if (!cancelled) showToast("加载章节切片失败，请稍后重试", "error");
      })
      .finally(() => {
        if (!cancelled) setReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, [docId]);

  const filtered = useMemo(() => {
    if (!keyword.trim()) return chapters;
    const kw = keyword.trim().toLowerCase();
    return chapters.filter((ch) => {
      const hitSelf = ch.heading.toLowerCase().includes(kw);
      const hitChild = (ch.children || []).some(
        (c) =>
          c.heading.toLowerCase().includes(kw) ||
          (c.children || []).some((g) => g.heading.toLowerCase().includes(kw)),
      );
      return hitSelf || hitChild;
    });
  }, [chapters, keyword]);

  useEffect(() => {
    setPage(1);
  }, [keyword, docId]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const paged = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  const stats = useMemo(() => {
    const primary = chapters.length;
    const secondary = chapters.reduce((sum, ch) => sum + childCountOf(ch), 0);
    const tertiary = chapters.reduce((sum, ch) => sum + tertiaryCountOf(ch), 0);
    const withImage = chapters.filter((ch) => imageCountOf(ch) > 0).length;
    return { primary, secondary, tertiary, withImage };
  }, [chapters]);

  const reloadChapters = () => {
    if (!docId) return Promise.resolve();
    return Promise.all([listKnowledgeDocuments(), getKnowledgeChapters(docId)]).then(([docs, chs]) => {
      setDoc(docs.find((d) => d.id === docId) || null);
      setChapters(chs);
    });
  };

  const handleRechunk = async () => {
    if (!docId) return;
    setRechunking(true);
    try {
      await rechunkKnowledgeDocument(docId);
      await reloadChapters();
      showToast("已按目录重新切片", "success");
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "重新切片失败，请稍后重试", "error");
    } finally {
      setRechunking(false);
    }
  };

  const openChapter = (item: KnowledgeChapter) => {
    if (!docId) return;
    setDetailLoading(true);
    setDetailChild(item.level === "一级" ? null : item);
    setDetail({
      docTitle: doc?.title || "",
      heading: item.heading,
      paragraphs: [],
      images: item.images || [],
    });
    getKnowledgeChapterDetail(docId, item.heading)
      .then((d) => setDetail(d))
      .catch(() => showToast("章节详情加载失败", "error"))
      .finally(() => setDetailLoading(false));
  };

  if (!ready) {
    return (
      <div className="rounded-lg border border-background-300 bg-background-100 py-16 text-center">
        <i className="ri-loader-4-line animate-spin text-3xl text-primary-500"></i>
        <p className="mt-3 text-sm text-foreground-500">正在加载章节切片…</p>
      </div>
    );
  }

  if (!doc) {
    return (
      <div className="rounded-lg border border-background-300 bg-background-100 py-16 text-center">
        <i className="ri-error-warning-line text-3xl text-foreground-400"></i>
        <p className="mt-3 text-sm text-foreground-500">知识文档不存在或已删除</p>
        <button
          type="button"
          onClick={() => navigate("/console/knowledge")}
          className="mt-4 h-9 cursor-pointer rounded-md border border-background-300 px-4 text-sm text-foreground-600 hover:bg-background-200"
        >
          返回文档知识库
        </button>
      </div>
    );
  }

  const statCards = [
    { key: "primary", label: "一级章节", value: stats.primary, icon: "ri-bookmark-3-line", gradient: "from-primary-400 to-primary-600", bar: "from-primary-500 to-primary-400" },
    { key: "secondary", label: "二级小节", value: stats.secondary, icon: "ri-node-tree", gradient: "from-secondary-400 to-secondary-500", bar: "from-secondary-400 to-secondary-300" },
    { key: "tertiary", label: "三级条目", value: stats.tertiary, icon: "ri-list-check-2", gradient: "from-primary-400 to-primary-600", bar: "from-primary-500 to-primary-400" },
    { key: "withImage", label: "已配图", value: stats.withImage, icon: "ri-image-line", gradient: "from-accent-400 to-accent-500", bar: "from-accent-500 to-accent-400" },
  ];

  return (
    <div>
      <PageHeader
        title={doc.title}
        description={`${doc.type} · ${doc.scope} · 按文档目录切到三级：3.1 一级，3.1.1 二级，3.1.1.1 三级，配图随章节保留。`}
        actions={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => navigate("/console/knowledge")}
              className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md border border-background-300 bg-background-100 px-4 text-sm font-medium text-foreground-700 transition-colors hover:bg-background-200"
            >
              <i className="ri-arrow-left-s-line text-sm"></i>
              全部知识文档
            </button>
            {canEdit && (
              <button
                type="button"
                disabled={rechunking}
                onClick={handleRechunk}
                className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <i className={`${rechunking ? "ri-loader-4-line animate-spin" : "ri-node-tree"} text-sm`}></i>
                {rechunking ? "正在按目录切片…" : "按目录重新切片"}
              </button>
            )}
          </div>
        }
      />

      <div className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {statCards.map((card) => (
          <div
            key={card.key}
            className="group relative flex items-center gap-3 overflow-hidden rounded-lg border border-background-300 bg-background-100 p-3.5 transition-all duration-300 hover:border-primary-300/60"
          >
            <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br ${card.gradient} text-background-50`}>
              <i className={`${card.icon} text-lg`}></i>
            </span>
            <div className="min-w-0 flex-1">
              <div className="font-label text-[11px] text-foreground-500">{card.label}</div>
              <div className="font-heading text-gradient mt-0.5 text-xl font-bold tracking-wide">{card.value}</div>
            </div>
            <div className={`absolute bottom-0 left-0 right-0 h-[2px] bg-gradient-to-r ${card.bar} opacity-0 transition-opacity duration-300 group-hover:opacity-100`} />
          </div>
        ))}
      </div>

      <div className="mb-4 flex flex-col gap-3 rounded-lg border border-background-300 bg-background-100 p-3.5 lg:flex-row lg:items-center">
        <div className="flex flex-wrap items-center gap-1.5">
          {(doc.tags || []).map((tag) => (
            <span key={tag} className="inline-flex items-center gap-0.5 rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700">
              <i className="ri-price-tag-3-line"></i>
              {tag}
            </span>
          ))}
          {doc.reviewFlag && (
            <span className="inline-flex items-center gap-1 rounded bg-accent-50 px-1.5 py-0.5 text-[10px] text-accent-700">
              <i className="ri-alert-line"></i>
              {doc.reviewFlag}
            </span>
          )}
        </div>
        <div className="relative flex-1 lg:max-w-xs lg:ml-auto">
          <i className="ri-search-line absolute left-3 top-1/2 -translate-y-1/2 text-xs text-foreground-500"></i>
          <input
            type="text"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="搜索一级、二级或三级章节…"
            className={`${inputCls} pl-9`}
          />
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border border-background-300 bg-background-100">
        <div className="overflow-x-auto">
            <table className="w-full min-w-[1080px] text-left">
              <thead>
                <tr className="font-label border-b border-background-300 bg-background-50 text-xs text-foreground-500">
                  <th className="px-4 py-3 font-medium">一级章节</th>
                  <th className="px-3 py-3 font-medium">二级目录</th>
                  <th className="px-3 py-3 font-medium">正文摘要</th>
                  <th className="px-3 py-3 font-medium">附图</th>
                  <th className="px-3 py-3 text-right font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
              {paged.map((ch) => (
                <tr key={ch.heading} className="group border-b border-background-200 transition-colors last:border-0 hover:bg-primary-50/30">
                  <td className="px-4 py-3 align-top">
                    <div className="flex items-start gap-2.5">
                      <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-gradient-to-br from-secondary-400 to-secondary-500 text-background-50">
                        <i className={`${typeIcon[doc.type] ?? "ri-article-line"} text-sm`}></i>
                      </span>
                      <div className="min-w-0">
                        <button
                          type="button"
                          onClick={() => openChapter(ch)}
                          className="cursor-pointer text-left text-sm font-medium text-foreground-900 hover:text-primary-600"
                        >
                          {ch.heading}
                        </button>
                        <div className="mt-0.5 text-xs text-foreground-500">
                          {ch.level || "一级"}
                          {(ch.children || []).length > 0 ? ` · 二级 ${ch.children!.length} 项` : ""}
                          {tertiaryCountOf(ch) > 0 ? ` · 三级 ${tertiaryCountOf(ch)} 项` : ""}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td className="max-w-[420px] px-3 py-3 align-top">
                    {(ch.children || []).length === 0 ? (
                      <span className="text-xs text-foreground-400">无二级目录</span>
                    ) : (
                      <div className="max-h-40 overflow-y-auto pr-1">
                        <div className="mb-1 text-[11px] text-foreground-500">二级目录 {ch.children!.length} 项：</div>
                        <div className="space-y-1">
                          {ch.children!.map((c) => (
                            <div key={c.heading}>
                              <button
                                type="button"
                                onClick={() => openChapter(c)}
                                className="cursor-pointer text-left text-[12px] font-medium text-primary-600 hover:underline"
                              >
                                {c.heading}
                              </button>
                              {(c.children || []).length > 0 && (
                                <div className="mt-0.5 line-clamp-2 pl-2 text-[11px] leading-relaxed text-foreground-600">
                                  <span className="text-foreground-400">三级 {c.children!.length} 项：</span>
                                  {c.children!.map((g) => g.heading).join("、")}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </td>
                  <td className="max-w-[280px] px-3 py-3 align-top">
                    <div className="line-clamp-3 text-xs leading-relaxed text-foreground-600">
                      {ch.excerpt || "点开查看本章正文、表格与配图。"}
                    </div>
                  </td>
                  <td className="px-3 py-3 align-top">
                    {imageCountOf(ch) === 0 ? (
                      <span className="text-xs text-foreground-400">无图</span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded bg-primary-50 px-1.5 py-0.5 text-[10px] font-medium text-primary-600">
                        <i className="ri-image-line"></i>
                        {imageCountOf(ch)} 张
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-3 text-right align-top">
                    <button
                      type="button"
                      title="查看章节切片"
                      onClick={() => openChapter(ch)}
                      className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-colors hover:bg-background-200 hover:text-foreground-800 ml-auto"
                    >
                      <i className="ri-eye-line text-sm"></i>
                    </button>
                  </td>
                </tr>
              ))}
              {paged.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-16 text-center text-sm text-foreground-500">
                    该文档还没有识别出章节切片
                  </td>
                </tr>
              )}
              </tbody>
            </table>
        </div>
        <PaginationBar total={filtered.length} page={safePage} pageSize={PAGE_SIZE} onPageChange={setPage} />
      </div>

      <Modal
        open={!!detail}
        onClose={() => {
          setDetail(null);
          setDetailChild(null);
        }}
        title={detail?.heading || "章节切片"}
        subtitle={`${detail?.level || (detailChild ? "二级" : "一级")} · ${doc.title}`}
      >
        {detailLoading ? (
          <div className="py-10 text-center text-sm text-foreground-500">
            <i className="ri-loader-4-line mr-1 animate-spin"></i>
            加载中…
          </div>
        ) : detail ? (
          <div className="space-y-4">
            {(detail.images || []).length > 0 && (
              <div>
                <div className={labelCls}>章节配图</div>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                  {detail.images!.map((img) => (
                    <div key={img.id} className="overflow-hidden rounded-lg border border-background-300 bg-background-50">
                      <AuthImage src={img.url} alt={img.caption} eager className="h-24 w-full object-cover" />
                      {img.caption ? (
                        <div className="truncate px-2 py-1.5 text-[11px] text-foreground-600">{img.caption}</div>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>
            )}
            <div>
              <div className={labelCls}>章节正文</div>
              {detail.paragraphs.length === 0 ? (
                <p className="text-xs text-foreground-500">本章无正文，仅保留标题与配图。</p>
              ) : (
                <div className="max-h-[360px] space-y-2.5 overflow-y-auto rounded-lg border border-background-300 bg-background-50 px-3 py-2.5">
                  {detail.paragraphs.map((p, i) => (
                    <p key={i} className="text-sm leading-relaxed text-foreground-700 whitespace-pre-wrap">
                      {p}
                    </p>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : null}
      </Modal>

      <Toast message={toast.message} type={toast.type} visible={toast.visible} />
    </div>
  );
}
