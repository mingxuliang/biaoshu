import { useEffect, useState } from "react";
import { listWriterLayoutPresets } from "@/lib/api";
import {
  layoutFontFamilies,
  layoutFontNamePt,
  layoutFontSizes,
  type LayoutConfig,
  type LayoutHeading,
} from "@/mocks/writerSteps";

const TENDER_KEYS = ["bodyFont", "bodySizePt", "fontSize", "indentPt", "indentChars"] as const;
const LEVELS = [
  { key: "h1", label: "一级标题" },
  { key: "h2", label: "二级标题" },
  { key: "h3", label: "三级标题" },
] as const;

const ptToName = (pt?: number) =>
  Object.entries(layoutFontNamePt).find(([, value]) => value === pt)?.[0] ?? "";

interface Props {
  layout: LayoutConfig;
  onChange: (next: LayoutConfig) => void;
  inputCls: string;
}

/** Word 导出排版：模板、中西文字体、分级标题、页眉页码、封面和目录。 */
export default function LayoutAdvanced({ layout, onChange, inputCls }: Props) {
  const [presets, setPresets] = useState<Record<string, Record<string, unknown>>>({});

  useEffect(() => {
    let cancelled = false;
    listWriterLayoutPresets()
      .then((rows) => {
        if (!cancelled) setPresets(rows);
      })
      .catch(() => {
        /* 模板拉取失败时仍可手动设置各项 */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const applyPreset = (name: string) => {
    const preset = presets[name] as Partial<LayoutConfig> | undefined;
    if (!preset) {
      onChange({ ...layout, preset: undefined });
      return;
    }
    const kept: Partial<LayoutConfig> = {};
    if (layout.fromTender) {
      for (const key of TENDER_KEYS) {
        if (layout[key] !== undefined) (kept as Record<string, unknown>)[key] = layout[key];
      }
    }
    onChange({
      ...(JSON.parse(JSON.stringify(preset)) as LayoutConfig),
      ...kept,
      fromTender: layout.fromTender,
    });
  };

  const setHeading = (key: "h1" | "h2" | "h3", patch: Partial<LayoutHeading>) => {
    onChange({
      ...layout,
      headings: { ...layout.headings, [key]: { ...layout.headings?.[key], ...patch } },
    });
  };

  const labelCls = "mb-1 block text-[11px] font-medium text-foreground-600";
  const selectCls = `${inputCls} cursor-pointer`;

  return (
    <div className="mt-3 space-y-3 rounded-lg border border-background-200 bg-background-100 p-3">
      <div className="flex flex-wrap items-center gap-3">
        <span className="flex items-center gap-1 text-xs font-semibold text-foreground-800">
          <span className="inline-block h-3.5 w-1 rounded-sm bg-primary-500"></span>
          Word 排版模板
        </span>
        <select
          value={layout.preset ?? ""}
          onChange={(e) => applyPreset(e.target.value)}
          className={`${selectCls} !w-44`}
        >
          <option value="">自定义</option>
          {Object.keys(presets).map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
        <span className="text-[11px] text-foreground-500">选模板会带入整套字体、标题、页码；招标书识别出的正文格式保留</span>
      </div>

      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
        <div>
          <label className={labelCls}>中文字体</label>
          <select
            value={layout.bodyFont ?? "宋体"}
            onChange={(e) => onChange({ ...layout, bodyFont: e.target.value })}
            className={selectCls}
          >
            {(layoutFontFamilies.includes(layout.bodyFont ?? "宋体")
              ? layoutFontFamilies
              : [layout.bodyFont as string, ...layoutFontFamilies]
            ).map((font) => (
              <option key={font}>{font}</option>
            ))}
          </select>
        </div>
        <div>
          <label className={labelCls}>英文数字字体</label>
          <select
            value={layout.bodyLatinFont ?? ""}
            onChange={(e) => onChange({ ...layout, bodyLatinFont: e.target.value || undefined })}
            className={selectCls}
          >
            <option value="">与中文一致</option>
            <option>Times New Roman</option>
            <option>Arial</option>
            <option>Calibri</option>
          </select>
        </div>
        <div>
          <label className={labelCls}>段间距（段后，pt）</label>
          <input
            type="number"
            min={0}
            max={60}
            value={layout.paragraphAfter ?? 0}
            onChange={(e) => onChange({ ...layout, paragraphAfter: Math.max(0, Math.min(60, Number(e.target.value) || 0)) })}
            className={inputCls}
          />
        </div>
      </div>

      <div>
        <div className="mb-1.5 text-[11px] font-medium text-foreground-600">分级标题样式</div>
        <div className="space-y-1.5">
          {LEVELS.map((level) => {
            const spec = layout.headings?.[level.key] ?? {};
            return (
              <div key={level.key} className="grid grid-cols-[64px_1fr_84px_52px_84px] items-center gap-2">
                <span className="text-xs text-foreground-600">{level.label}</span>
                <select
                  value={spec.font ?? layout.headingFont ?? "黑体"}
                  onChange={(e) => setHeading(level.key, { font: e.target.value })}
                  className={selectCls}
                >
                  {layoutFontFamilies.map((font) => (
                    <option key={font}>{font}</option>
                  ))}
                </select>
                <select
                  value={ptToName(spec.sizePt) || ""}
                  onChange={(e) => setHeading(level.key, { sizePt: layoutFontNamePt[e.target.value] })}
                  className={selectCls}
                >
                  <option value="">默认</option>
                  {layoutFontSizes.map((name) => (
                    <option key={name}>{name}</option>
                  ))}
                </select>
                <label className="flex cursor-pointer items-center gap-1 text-xs text-foreground-600">
                  <input
                    type="checkbox"
                    checked={spec.bold ?? true}
                    onChange={(e) => setHeading(level.key, { bold: e.target.checked })}
                  />
                  加粗
                </label>
                <select
                  value={spec.align ?? "left"}
                  onChange={(e) => setHeading(level.key, { align: e.target.value as LayoutHeading["align"] })}
                  className={selectCls}
                >
                  <option value="left">左对齐</option>
                  <option value="center">居中</option>
                  <option value="right">右对齐</option>
                </select>
              </div>
            );
          })}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
        <div>
          <label className={labelCls}>页眉文字（{"{project}"} 代表项目名）</label>
          <input
            value={layout.header ?? ""}
            onChange={(e) => onChange({ ...layout, header: e.target.value })}
            placeholder="留空则不设页眉"
            className={inputCls}
          />
        </div>
        <div>
          <label className={labelCls}>页码</label>
          <select
            value={layout.pageNumber ?? "none"}
            onChange={(e) => onChange({ ...layout, pageNumber: e.target.value as LayoutConfig["pageNumber"] })}
            className={selectCls}
          >
            <option value="none">不加页码</option>
            <option value="simple">数字页码</option>
            <option value="full">第 X 页 共 Y 页</option>
          </select>
        </div>
        <div>
          <label className={labelCls}>纸张方向</label>
          <select
            value={layout.orientation ?? "portrait"}
            onChange={(e) => onChange({ ...layout, orientation: e.target.value as LayoutConfig["orientation"] })}
            className={selectCls}
          >
            <option value="portrait">纵向</option>
            <option value="landscape">横向</option>
          </select>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-4 text-xs text-foreground-700">
        <label className="flex cursor-pointer items-center gap-1.5">
          <input
            type="checkbox"
            checked={Boolean(layout.cover?.enabled)}
            onChange={(e) =>
              onChange({
                ...layout,
                cover: { title: "{project}", subtitle: "投标文件", ...layout.cover, enabled: e.target.checked },
              })
            }
          />
          生成封面页
        </label>
        <label className="flex cursor-pointer items-center gap-1.5">
          <input
            type="checkbox"
            checked={Boolean(layout.toc?.enabled)}
            onChange={(e) => onChange({ ...layout, toc: { levels: 3, ...layout.toc, enabled: e.target.checked } })}
          />
          生成自动目录（用 Word 打开后更新域）
        </label>
        <label className="flex cursor-pointer items-center gap-1.5">
          <input
            type="checkbox"
            checked={Boolean(layout.justify)}
            onChange={(e) => onChange({ ...layout, justify: e.target.checked })}
          />
          正文两端对齐
        </label>
      </div>
    </div>
  );
}
