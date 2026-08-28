import { useEffect, useState } from "react";
import PageHeader from "../components/PageHeader";
import Toast from "../components/Toast";
import Modal from "../components/Modal";
import {
  ApiError,
  createLlmModel,
  createLlmProvider,
  deleteLlmModel,
  deleteLlmProvider,
  listLlmPresets,
  listLlmProviders,
  patchLlmModel,
  patchLlmProvider,
  testLlmModel,
  type LlmPreset,
  type LlmProvider,
  type LlmProviderKind,
  type WriterLlmModel,
} from "@/lib/api";

const KIND_META: Record<LlmProviderKind, { icon: string; tone: string }> = {
  deepseek: { icon: "ri-brain-line", tone: "from-primary-400 to-primary-600" },
  doubao: { icon: "ri-chat-smile-ai-line", tone: "from-accent-400 to-accent-600" },
  qwen: { icon: "ri-cloud-line", tone: "from-secondary-500 to-primary-500" },
  siliconflow: { icon: "ri-flow-chart", tone: "from-primary-500 to-accent-500" },
  openai: { icon: "ri-sparkling-2-line", tone: "from-foreground-700 to-foreground-900" },
  custom: { icon: "ri-plug-line", tone: "from-secondary-500 to-secondary-700" },
  local: { icon: "ri-computer-line", tone: "from-accent-500 to-primary-500" },
};

const inputCls =
  "h-9 w-full rounded-md border border-background-300 bg-background-50 px-3 text-sm text-foreground-900 outline-none transition-all focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20 placeholder:text-foreground-500";
const labelCls = "mb-1.5 block text-xs font-medium text-foreground-600";

interface ToastState {
  message: string;
  type: "success" | "error" | "info";
  visible: boolean;
}

export default function ModelsPage() {
  const [loading, setLoading] = useState(true);
  const [providers, setProviders] = useState<LlmProvider[]>([]);
  const [presets, setPresets] = useState<LlmPreset[]>([]);
  const [toast, setToast] = useState<ToastState>({ message: "", type: "success", visible: false });
  const [providerModal, setProviderModal] = useState(false);
  const [modelModal, setModelModal] = useState<LlmProvider | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, { baseUrl: string; apiKey: string }>>({});

  const [newKind, setNewKind] = useState<LlmProviderKind>("custom");
  const [newName, setNewName] = useState("");
  const [newUrl, setNewUrl] = useState("");
  const [newKey, setNewKey] = useState("");

  const [modelName, setModelName] = useState("");
  const [modelApi, setModelApi] = useState("");
  const [modelThinking, setModelThinking] = useState(false);

  const showToast = (message: string, type: ToastState["type"] = "success") => {
    setToast({ message, type, visible: true });
    window.setTimeout(() => setToast((t) => ({ ...t, visible: false })), 3200);
  };
  const errMsg = (err: unknown, fallback: string) => (err instanceof ApiError ? err.message : fallback);

  const load = () => {
    setLoading(true);
    Promise.all([listLlmProviders(), listLlmPresets()])
      .then(([rows, presetRows]) => {
        setProviders(rows);
        setPresets(presetRows);
        setDrafts(
          Object.fromEntries(rows.map((p) => [p.id, { baseUrl: p.baseUrl, apiKey: "" }])),
        );
      })
      .catch((err) => showToast(errMsg(err, "模型配置加载失败"), "error"))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openNewProvider = (kind: LlmProviderKind) => {
    const preset = presets.find((p) => p.kind === kind);
    setNewKind(kind);
    setNewName(preset?.label || "");
    setNewUrl(preset?.defaultBaseUrl || "");
    setNewKey("");
    setProviderModal(true);
  };

  const saveProviderCreds = async (provider: LlmProvider) => {
    const draft = drafts[provider.id] || { baseUrl: provider.baseUrl, apiKey: "" };
    setSavingId(provider.id);
    try {
      const updated = await patchLlmProvider(provider.id, {
        baseUrl: draft.baseUrl,
        ...(draft.apiKey.trim() ? { apiKey: draft.apiKey.trim() } : {}),
      });
      setProviders((prev) => prev.map((p) => (p.id === provider.id ? updated : p)));
      setDrafts((prev) => ({ ...prev, [provider.id]: { baseUrl: updated.baseUrl, apiKey: "" } }));
      showToast(`已保存「${updated.name}」接入配置`);
    } catch (err) {
      showToast(errMsg(err, "保存失败"), "error");
    } finally {
      setSavingId(null);
    }
  };

  const submitProvider = async () => {
    try {
      const created = await createLlmProvider({
        name: newName.trim() || presets.find((p) => p.kind === newKind)?.label || "自定义接入",
        kind: newKind,
        baseUrl: newUrl.trim(),
        apiKey: newKey.trim() || undefined,
      });
      setProviders((prev) => [...prev, created]);
      setDrafts((prev) => ({ ...prev, [created.id]: { baseUrl: created.baseUrl, apiKey: "" } }));
      setProviderModal(false);
      showToast("已新增接入，可继续添加模型");
    } catch (err) {
      showToast(errMsg(err, "新增接入失败"), "error");
    }
  };

  const submitModel = async () => {
    if (!modelModal) return;
    if (!modelName.trim() || !modelApi.trim()) {
      showToast("请填写显示名称和接口模型名", "error");
      return;
    }
    try {
      const created = await createLlmModel(modelModal.id, {
        name: modelName.trim(),
        apiModel: modelApi.trim(),
        thinking: modelThinking,
      });
      setProviders((prev) =>
        prev.map((p) => (p.id === modelModal.id ? { ...p, models: [...p.models, created] } : p)),
      );
      setModelModal(null);
      showToast(`已接入模型「${created.name}」`);
    } catch (err) {
      showToast(errMsg(err, "添加模型失败"), "error");
    }
  };

  const toggleThinking = async (model: WriterLlmModel) => {
    try {
      const updated = await patchLlmModel(model.id, { thinking: !model.thinking });
      setProviders((prev) =>
        prev.map((p) =>
          p.id === model.providerId ? { ...p, models: p.models.map((m) => (m.id === model.id ? { ...m, ...updated } : m)) } : p,
        ),
      );
      showToast(updated.thinking ? `已开启「${updated.name}」思维链` : `已关闭「${updated.name}」思维链`, "info");
    } catch (err) {
      showToast(errMsg(err, "更新思维链失败"), "error");
    }
  };

  const toggleEnabled = async (model: WriterLlmModel) => {
    try {
      const updated = await patchLlmModel(model.id, { enabled: !model.enabled });
      setProviders((prev) =>
        prev.map((p) =>
          p.id === model.providerId ? { ...p, models: p.models.map((m) => (m.id === model.id ? { ...m, ...updated } : m)) } : p,
        ),
      );
    } catch (err) {
      showToast(errMsg(err, "更新启用状态失败"), "error");
    }
  };

  const setDefault = async (model: WriterLlmModel) => {
    try {
      await patchLlmModel(model.id, { isDefault: true });
      load();
      showToast(`已将「${model.name}」设为默认撰写模型`);
    } catch (err) {
      showToast(errMsg(err, "设置默认模型失败"), "error");
    }
  };

  const testOne = async (model: WriterLlmModel) => {
    setTestingId(model.id);
    try {
      const result = await testLlmModel(model.id);
      showToast(
        result.ok ? `${model.name} 连通正常（${result.latencyMs}ms）${result.preview ? `：${result.preview}` : ""}` : result.message,
        result.ok ? "success" : "error",
      );
    } catch (err) {
      showToast(errMsg(err, "连通测试失败"), "error");
    } finally {
      setTestingId(null);
    }
  };

  const presetOf = (kind: LlmProviderKind) => presets.find((p) => p.kind === kind);

  return (
    <div>
      <PageHeader
        title="模型配置"
        description="配置各平台 API 秘钥，接入通义千问、硅基流动、自定义 OpenAI 兼容网关或本机 Ollama / vLLM。撰写工作台只展示已启用且秘钥就绪的模型。"
        actions={
          <button
            type="button"
            onClick={() => openNewProvider("custom")}
            className="flex h-9 cursor-pointer items-center gap-1.5 rounded-md bg-primary-500 px-3 text-sm font-medium text-background-50 hover:bg-primary-600"
          >
            <i className="ri-add-line"></i>
            新增接入
          </button>
        }
      />

      <div className="mb-4 flex flex-wrap gap-2">
        {presets.map((p) => (
          <button
            key={p.kind}
            type="button"
            onClick={() => openNewProvider(p.kind)}
            className="flex h-8 cursor-pointer items-center gap-1.5 rounded-md border border-background-300 bg-background-100 px-2.5 text-xs text-foreground-700 hover:border-primary-300 hover:text-primary-600"
          >
            <i className={`${KIND_META[p.kind]?.icon || "ri-cpu-line"} text-sm`}></i>
            {p.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex items-center gap-2 py-16 text-sm text-foreground-500">
          <i className="ri-loader-4-line animate-spin"></i>
          正在加载模型配置…
        </div>
      ) : (
        <div className="space-y-4">
          {providers.map((provider) => {
            const meta = KIND_META[provider.kind] || KIND_META.custom;
            const draft = drafts[provider.id] || { baseUrl: provider.baseUrl, apiKey: "" };
            const preset = presetOf(provider.kind);
            return (
              <section key={provider.id} className="rounded-lg border border-background-300 bg-background-100">
                <div className="flex flex-wrap items-start gap-3 border-b border-background-300 px-4 py-3">
                  <span className={`flex h-9 w-9 items-center justify-center rounded-md bg-gradient-to-br ${meta.tone} text-background-50`}>
                    <i className={`${meta.icon} text-base`}></i>
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-sm font-semibold text-foreground-900">{provider.name}</h3>
                      <span className={`rounded px-1.5 py-0.5 text-[10px] ${provider.ready ? "bg-primary-50 text-primary-600" : "bg-accent-50 text-accent-700"}`}>
                        {provider.ready ? "秘钥已就绪" : preset?.keyRequired ? "待填秘钥" : "待填地址"}
                      </span>
                    </div>
                    <p className="mt-1 text-[11px] leading-relaxed text-foreground-500">{provider.note || preset?.hint}</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      if (!window.confirm(`删除接入「${provider.name}」及其下全部模型？`)) return;
                      deleteLlmProvider(provider.id)
                        .then(() => {
                          setProviders((prev) => prev.filter((p) => p.id !== provider.id));
                          showToast("已删除接入", "info");
                        })
                        .catch((err) => showToast(errMsg(err, "删除失败"), "error"));
                    }}
                    className="h-8 cursor-pointer rounded-md px-2 text-xs text-foreground-500 hover:bg-background-200 hover:text-accent-700"
                  >
                    删除接入
                  </button>
                </div>

                <div className="grid gap-3 border-b border-background-200 px-4 py-3 md:grid-cols-3">
                  <label className="md:col-span-2">
                    <span className={labelCls}>Base URL</span>
                    <input
                      value={draft.baseUrl}
                      onChange={(e) =>
                        setDrafts((prev) => ({ ...prev, [provider.id]: { ...draft, baseUrl: e.target.value } }))
                      }
                      placeholder={preset?.defaultBaseUrl || "https://.../v1"}
                      className={inputCls}
                    />
                  </label>
                  <label>
                    <span className={labelCls}>API 秘钥 {provider.hasKey ? `（${provider.apiKeyMasked}）` : ""}</span>
                    <input
                      type="password"
                      autoComplete="new-password"
                      value={draft.apiKey}
                      onChange={(e) =>
                        setDrafts((prev) => ({ ...prev, [provider.id]: { ...draft, apiKey: e.target.value } }))
                      }
                      placeholder={provider.hasKey ? "不修改请留空" : preset?.keyRequired ? "粘贴 API Key" : "本地模型可留空"}
                      className={inputCls}
                    />
                  </label>
                  <div className="flex items-end md:col-span-3">
                    <button
                      type="button"
                      onClick={() => saveProviderCreds(provider)}
                      disabled={savingId === provider.id}
                      className="flex h-9 cursor-pointer items-center gap-1.5 rounded-md bg-primary-500 px-3 text-xs font-medium text-background-50 hover:bg-primary-600 disabled:opacity-60"
                    >
                      <i className={`${savingId === provider.id ? "ri-loader-4-line animate-spin" : "ri-save-line"}`}></i>
                      保存秘钥与地址
                    </button>
                  </div>
                </div>

                <div className="px-4 py-3">
                  <div className="mb-2 flex items-center justify-between">
                    <div className="text-xs font-medium text-foreground-700">模型列表</div>
                    <button
                      type="button"
                      onClick={() => {
                        setModelName("");
                        setModelApi(preset?.sampleModels[0]?.api_model || "");
                        setModelThinking(false);
                        setModelModal(provider);
                      }}
                      className="flex h-7 cursor-pointer items-center gap-1 rounded-md px-2 text-[11px] text-primary-600 hover:bg-primary-50"
                    >
                      <i className="ri-add-line"></i>
                      添加模型
                    </button>
                  </div>
                  {provider.models.length === 0 ? (
                    <p className="py-3 text-xs text-foreground-500">尚未添加模型。接口模型名如 qwen-plus、deepseek-v4-pro、llama3.1:8b。</p>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full min-w-[640px] text-left text-xs">
                        <thead className="text-[11px] text-foreground-500">
                          <tr>
                            <th className="py-1.5 font-medium">显示名</th>
                            <th className="py-1.5 font-medium">接口模型名</th>
                            <th className="py-1.5 font-medium">思维链</th>
                            <th className="py-1.5 font-medium">撰写可选</th>
                            <th className="py-1.5 font-medium">默认</th>
                            <th className="py-1.5 font-medium"></th>
                          </tr>
                        </thead>
                        <tbody>
                          {provider.models.map((model) => (
                            <tr key={model.id} className="border-t border-background-200">
                              <td className="py-2 font-medium text-foreground-800">{model.name}</td>
                              <td className="py-2 font-mono text-[11px] text-foreground-600">{model.apiModel}</td>
                              <td className="py-2">
                                <button
                                  type="button"
                                  onClick={() => toggleThinking(model)}
                                  className={`h-6 cursor-pointer rounded-full px-2 text-[10px] ${
                                    model.thinking ? "bg-accent-100 text-accent-700" : "bg-secondary-100 text-secondary-600"
                                  }`}
                                >
                                  {model.thinking ? "已开启" : "已关闭"}
                                </button>
                              </td>
                              <td className="py-2">
                                <button
                                  type="button"
                                  onClick={() => toggleEnabled(model)}
                                  className={`h-6 cursor-pointer rounded-full px-2 text-[10px] ${
                                    model.enabled ? "bg-primary-50 text-primary-600" : "bg-secondary-100 text-secondary-500"
                                  }`}
                                >
                                  {model.enabled ? "启用" : "停用"}
                                </button>
                              </td>
                              <td className="py-2">
                                {model.isDefault ? (
                                  <span className="text-primary-600">默认</span>
                                ) : (
                                  <button type="button" onClick={() => setDefault(model)} className="cursor-pointer text-foreground-500 hover:text-primary-600">
                                    设为默认
                                  </button>
                                )}
                              </td>
                              <td className="py-2 text-right">
                                <button
                                  type="button"
                                  onClick={() => testOne(model)}
                                  disabled={testingId === model.id}
                                  className="mr-2 cursor-pointer text-primary-600 hover:underline disabled:opacity-50"
                                >
                                  {testingId === model.id ? "测试中…" : "测试连通"}
                                </button>
                                <button
                                  type="button"
                                  onClick={() => {
                                    if (!window.confirm(`删除模型「${model.name}」？`)) return;
                                    deleteLlmModel(model.id)
                                      .then(() => {
                                        setProviders((prev) =>
                                          prev.map((p) =>
                                            p.id === provider.id ? { ...p, models: p.models.filter((m) => m.id !== model.id) } : p,
                                          ),
                                        );
                                      })
                                      .catch((err) => showToast(errMsg(err, "删除失败"), "error"));
                                  }}
                                  className="cursor-pointer text-foreground-400 hover:text-accent-700"
                                >
                                  删除
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </section>
            );
          })}
        </div>
      )}

      <Modal open={providerModal} title="新增模型接入" subtitle="填写秘钥与 Base URL，本地模型可不安秘钥" onClose={() => setProviderModal(false)}>
        <div className="space-y-3">
          <label>
            <span className={labelCls}>接入类型</span>
            <select
              value={newKind}
              onChange={(e) => {
                const kind = e.target.value as LlmProviderKind;
                openNewProvider(kind);
              }}
              className={inputCls}
            >
              {presets.map((p) => (
                <option key={p.kind} value={p.kind}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span className={labelCls}>显示名称</span>
            <input value={newName} onChange={(e) => setNewName(e.target.value)} className={inputCls} />
          </label>
          <label>
            <span className={labelCls}>Base URL</span>
            <input value={newUrl} onChange={(e) => setNewUrl(e.target.value)} className={inputCls} />
          </label>
          <label>
            <span className={labelCls}>API 秘钥</span>
            <input type="password" autoComplete="new-password" value={newKey} onChange={(e) => setNewKey(e.target.value)} className={inputCls} />
          </label>
          <p className="text-[11px] leading-relaxed text-foreground-500">{presetOf(newKind)?.hint}</p>
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={() => setProviderModal(false)} className="h-9 rounded-md px-3 text-sm text-foreground-600 hover:bg-background-200">
              取消
            </button>
            <button type="button" onClick={submitProvider} className="h-9 rounded-md bg-primary-500 px-3 text-sm text-background-50 hover:bg-primary-600">
              保存接入
            </button>
          </div>
        </div>
      </Modal>

      <Modal open={!!modelModal} title={`添加模型 · ${modelModal?.name || ""}`} subtitle="接口模型名必须与平台控制台一致" onClose={() => setModelModal(null)}>
        <div className="space-y-3">
          <label>
            <span className={labelCls}>显示名称</span>
            <input value={modelName} onChange={(e) => setModelName(e.target.value)} placeholder="如 Qwen Plus" className={inputCls} />
          </label>
          <label>
            <span className={labelCls}>接口模型名</span>
            <input value={modelApi} onChange={(e) => setModelApi(e.target.value)} placeholder="如 qwen-plus / llama3.1:8b / ep-xxxx" className={inputCls} />
          </label>
          <label className="flex items-center gap-2 text-sm text-foreground-700">
            <input type="checkbox" checked={modelThinking} onChange={(e) => setModelThinking(e.target.checked)} />
            开启思维链（推理模型）
          </label>
          <p className="text-[11px] text-foreground-500">撰写目录、产品匹配建议关闭思维链，避免只返回思考过程、正文为空。</p>
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={() => setModelModal(null)} className="h-9 rounded-md px-3 text-sm text-foreground-600 hover:bg-background-200">
              取消
            </button>
            <button type="button" onClick={submitModel} className="h-9 rounded-md bg-primary-500 px-3 text-sm text-background-50 hover:bg-primary-600">
              添加
            </button>
          </div>
        </div>
      </Modal>

      <Toast message={toast.message} type={toast.type} visible={toast.visible} />
    </div>
  );
}
