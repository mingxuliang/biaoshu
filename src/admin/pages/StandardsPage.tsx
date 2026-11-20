import { useEffect, useState } from "react";
import PageHeader from "@/pages/console/components/PageHeader";
import { listStandards, uploadStandard, type StandardCatalogRow } from "../api";

export default function StandardsPage() {
  const [rows, setRows] = useState<StandardCatalogRow[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const reload = () => {
    listStandards()
      .then(setRows)
      .catch((err: Error) => setError(err.message));
  };

  useEffect(() => {
    reload();
  }, []);

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      await uploadStandard(file);
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="规范库"
        description="平台公共规范，供预审检索条文。扫描件需要 MinerU，入库在后台进行。"
        actions={
          <label className="cursor-pointer rounded bg-primary-600 px-3 py-1.5 text-sm text-white">
            {busy ? "上传中…" : "上传 PDF"}
            <input
              type="file"
              accept="application/pdf"
              className="hidden"
              disabled={busy}
              onChange={(e) => {
                void onFile(e.target.files?.[0]);
                e.target.value = "";
              }}
            />
          </label>
        }
      />
      {error ? <p className="mb-3 text-sm text-accent-600">{error}</p> : null}
      <div className="overflow-hidden rounded-lg border border-background-300 bg-background-50">
        <table className="w-full text-left text-sm">
          <thead className="bg-background-100 text-xs text-foreground-500">
            <tr>
              <th className="px-3 py-2">编号</th>
              <th className="px-3 py-2">文件</th>
              <th className="px-3 py-2">专业</th>
              <th className="px-3 py-2">状态</th>
              <th className="px-3 py-2">条文</th>
              <th className="px-3 py-2">说明</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-3 py-8 text-center text-foreground-500">
                  还没有规范。
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr key={row.id} className="border-t border-background-200">
                  <td className="px-3 py-2">{row.code || "—"}</td>
                  <td className="px-3 py-2">{row.name}</td>
                  <td className="px-3 py-2">{row.specialty}</td>
                  <td className="px-3 py-2">{row.status}</td>
                  <td className="px-3 py-2">{row.clauseCount}</td>
                  <td className="px-3 py-2 text-xs text-foreground-500">{row.note}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
