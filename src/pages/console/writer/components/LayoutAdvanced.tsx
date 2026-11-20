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
  { key: "h4", label: "四级标题" },
] as const;

const ptToName = (pt?: number) =>
  Object.entries(layoutFontNamePt).find(([, value]) => value === pt)?.[0] ?? "";

interface Props {
  layout: LayoutConfig;
  onChange: (next: LayoutConfig) => void;
  inputCls: string;
}

/** Word 导出排版：模板、中西文字体、分级标题（含四级）、缩进、页眉页脚、封面和目录。 */
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

  const setHeading = (key: "h1" | "h2" | "h3" | "h4", patch: Partial<LayoutHeading>) => {
    onChange({
      ...layout,
      headings: { ...layout.headings, [key]: { ...layout.headings?.[key], ...patch } },
    });
  };

  const setCover = (patch: Partial<NonNullable<LayoutConfig["cover"]>>) => {
    onChange({ ...layout, cover: { ...layout.cover, ...patch } });
  };

  const setTable = (patch: Partial<NonNullable<LayoutConfig["table"]>>) => {
    onChange({ ...layout, table: { ...layout.table, ...patch } });
  };

  const setCaption = (patch: Partial<NonNullable<LayoutConfig["caption"]>>) => {
    onChange({ ...layout, caption: { ...layout.caption, ...patch } });
  };

  const labelCls = "mb-1 block text-[11px] font-medium text-foreground-600";
  const selectCls = `${inputCls} cursor-pointer`;
  const fontOptions = (current?: string) =>
    current && !layoutFontFamilies.includes(current) ? [current, ...layoutFontFamilies] : layoutFontFamilies;

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
            {fontOptions(layout.bodyFont).map((font) => (
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
            <option>Cambria</option>
            <option>Courier New</option>
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

      {/* 缩进：首行缩进走上方「正文字号/首行缩进 2 字」的默认值；这里是补充的悬挂缩进和左缩进 */}
      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
        <div>
          <label className={labelCls}>悬挂缩进（pt，列表/条款常用，设置后覆盖首行缩进）</label>
          <input
            type="number"
            min={0}
            max={80}
            value={layout.hangingIndentPt ?? 0}
            onChange={(e) =>
              onChange({ ...layout, hangingIndentPt: Math.max(0, Math.min(80, Number(e.target.value) || 0)) || undefined })
            }
            placeholder="0 表示不设置"
            className={inputCls}
          />
        </div>
        <div>
          <label className={labelCls}>左缩进（pt，整段向右移）</label>
          <input
            type="number"
            min={0}
            max={120}
            value={layout.leftIndentPt ?? 0}
            onChange={(e) =>
              onChange({ ...layout, leftIndentPt: Math.max(0, Math.min(120, Number(e.target.value) || 0)) || undefined })
            }
            placeholder="0 表示不设置"
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
                  {fontOptions(spec.font).map((font) => (
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

      {/* 页眉页脚 */}
      <div className="rounded-lg border border-background-200 bg-background-50 p-3">
        <div className="mb-2 text-[11px] font-medium text-foreground-600">页眉页脚</div>
        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
          <div>
            <label className={labelCls}>页眉文字（{"{project}"} 代表项目名）</label>
            <input
              value={layout.header ?? ""}
              onChange={(e) => onChange({ ...layout, header: e.target.value })}
              placeholder="留空则不设页眉"
              className={inputCls}
            />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className={labelCls}>页眉字体</label>
              <select
                value={layout.headerFont ?? layout.bodyFont ?? "仿宋"}
                onChange={(e) => onChange({ ...layout, headerFont: e.target.value })}
                className={selectCls}
              >
                {fontOptions(layout.headerFont).map((font) => (
                  <option key={font}>{font}</option>
                ))}
              </select>
            </div>
            <div>
              <label className={labelCls}>页眉字号</label>
              <select
                value={ptToName(layout.headerSizePt) || ""}
                onChange={(e) => onChange({ ...layout, headerSizePt: layoutFontNamePt[e.target.value] })}
                className={selectCls}
              >
                <option value="">默认 9pt</option>
                {layoutFontSizes.map((name) => (
                  <option key={name}>{name}</option>
                ))}
              </select>
            </div>
          </div>
        </div>
        <div className="mt-2.5 grid grid-cols-1 gap-2.5 sm:grid-cols-2">
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
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className={labelCls}>页脚字体</label>
              <select
                value={layout.footerFont ?? layout.bodyFont ?? "仿宋"}
                onChange={(e) => onChange({ ...layout, footerFont: e.target.value })}
                className={selectCls}
              >
                {fontOptions(layout.footerFont).map((font) => (
                  <option key={font}>{font}</option>
                ))}
              </select>
            </div>
            <div>
              <label className={labelCls}>页脚字号</label>
              <select
                value={ptToName(layout.footerSizePt) || ""}
                onChange={(e) => onChange({ ...layout, footerSizePt: layoutFontNamePt[e.target.value] })}
                className={selectCls}
              >
                <option value="">默认 9pt</option>
                {layoutFontSizes.map((name) => (
                  <option key={name}>{name}</option>
                ))}
              </select>
            </div>
          </div>
        </div>
        <div className="mt-2.5 flex flex-wrap items-center gap-4 text-xs text-foreground-700">
          <label className="flex cursor-pointer items-center gap-1.5">
            <input
              type="checkbox"
              checked={layout.headerBorder ?? false}
              onChange={(e) => onChange({ ...layout, headerBorder: e.target.checked })}
            />
            页眉下加分隔线
          </label>
          <label className="flex cursor-pointer items-center gap-1.5">
            <input
              type="checkbox"
              checked={layout.differentFirstPage ?? false}
              onChange={(e) => onChange({ ...layout, differentFirstPage: e.target.checked })}
            />
            首页不显示页眉页脚
          </label>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
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
        <div>
          <label className={labelCls}>表头底色 / 表格字号</label>
          <div className="flex items-center gap-2">
            <input
              type="color"
              value={`#${layout.table?.headerFill ?? "D9D9D9"}`}
              onChange={(e) => setTable({ headerFill: e.target.value.replace("#", "").toUpperCase() })}
              className="h-8 w-9 cursor-pointer rounded border border-background-300 bg-background-50"
            />
            <select
              value={ptToName(layout.table?.fontSizePt) || ""}
              onChange={(e) => setTable({ fontSizePt: layoutFontNamePt[e.target.value] })}
              className={selectCls}
            >
              <option value="">默认</option>
              {layoutFontSizes.map((name) => (
                <option key={name}>{name}</option>
              ))}
            </select>
          </div>
        </div>
        <div>
          <label className={labelCls}>表格边框色 / 粗细（pt）</label>
          <div className="flex items-center gap-2">
            <input
              type="color"
              value={`#${layout.table?.borderColor ?? "808080"}`}
              onChange={(e) => setTable({ borderColor: e.target.value.replace("#", "").toUpperCase() })}
              className="h-8 w-9 cursor-pointer rounded border border-background-300 bg-background-50"
            />
            <input
              type="number"
              min={0.25}
              max={3}
              step={0.25}
              value={layout.table?.borderSizePt ?? 0.5}
              onChange={(e) => setTable({ borderSizePt: Math.max(0.25, Math.min(3, Number(e.target.value) || 0.5)) })}
              className={inputCls}
            />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
        <div>
          <label className={labelCls}>图表题注字体 / 字号</label>
          <div className="flex items-center gap-2">
            <select value={layout.caption?.font ?? "黑体"} onChange={(e) => setCaption({ font: e.target.value })} className={selectCls}>
              {fontOptions(layout.caption?.font).map((font) => (
                <option key={font}>{font}</option>
              ))}
            </select>
            <select
              value={ptToName(layout.caption?.sizePt) || ""}
              onChange={(e) => setCaption({ sizePt: layoutFontNamePt[e.target.value] })}
              className={selectCls}
            >
              <option value="">默认</option>
              {layoutFontSizes.map((name) => (
                <option key={name}>{name}</option>
              ))}
            </select>
          </div>
        </div>
        <div>
          <label className={labelCls}>题注段后间距（pt）</label>
          <input
            type="number"
            min={0}
            max={40}
            value={layout.caption?.spaceAfter ?? 0}
            onChange={(e) => setCaption({ spaceAfter: Math.max(0, Math.min(40, Number(e.target.value) || 0)) })}
            className={inputCls}
          />
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

      {layout.cover?.enabled && (
        <div className="rounded-lg border border-background-200 bg-background-50 p-3">
          <div className="mb-2 text-[11px] font-medium text-foreground-600">封面字体字号</div>
          <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
            <div>
              <label className={labelCls}>主标题字体 / 字号（pt）</label>
              <div className="flex items-center gap-2">
                <select
                  value={layout.cover?.titleFont ?? "黑体"}
                  onChange={(e) => setCover({ titleFont: e.target.value })}
                  className={selectCls}
                >
                  {fontOptions(layout.cover?.titleFont).map((font) => (
                    <option key={font}>{font}</option>
                  ))}
                </select>
                <input
                  type="number"
                  min={12}
                  max={72}
                  value={layout.cover?.titleSizePt ?? 32}
                  onChange={(e) => setCover({ titleSizePt: Math.max(12, Math.min(72, Number(e.target.value) || 32)) })}
                  className={inputCls}
                />
              </div>
            </div>
            <div>
              <label className={labelCls}>副标题（如「技术投标书」）字体 / 字号</label>
              <div className="flex items-center gap-2">
                <select
                  value={layout.cover?.subtitleFont ?? "黑体"}
                  onChange={(e) => setCover({ subtitleFont: e.target.value })}
                  className={selectCls}
                >
                  {fontOptions(layout.cover?.subtitleFont).map((font) => (
                    <option key={font}>{font}</option>
                  ))}
                </select>
                <input
                  type="number"
                  min={12}
                  max={72}
                  value={layout.cover?.subtitleSizePt ?? 44}
                  onChange={(e) => setCover({ subtitleSizePt: Math.max(12, Math.min(72, Number(e.target.value) || 44)) })}
                  className={inputCls}
                />
              </div>
            </div>
            <div>
              <label className={labelCls}>投标单位信息字体 / 字号</label>
              <div className="flex items-center gap-2">
                <select
                  value={layout.cover?.infoFont ?? "仿宋"}
                  onChange={(e) => setCover({ infoFont: e.target.value })}
                  className={selectCls}
                >
                  {fontOptions(layout.cover?.infoFont).map((font) => (
                    <option key={font}>{font}</option>
                  ))}
                </select>
                <input
                  type="number"
                  min={9}
                  max={36}
                  value={layout.cover?.infoSizePt ?? 16}
                  onChange={(e) => setCover({ infoSizePt: Math.max(9, Math.min(36, Number(e.target.value) || 16)) })}
                  className={inputCls}
                />
              </div>
            </div>
          </div>
          <div className="mt-2.5 grid grid-cols-1 gap-2.5 sm:grid-cols-3">
            <div>
              <label className={labelCls}>投标单位</label>
              <input value={layout.cover?.company ?? ""} onChange={(e) => setCover({ company: e.target.value })} className={inputCls} />
            </div>
            <div>
              <label className={labelCls}>编制日期</label>
              <input value={layout.cover?.date ?? ""} onChange={(e) => setCover({ date: e.target.value })} className={inputCls} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
