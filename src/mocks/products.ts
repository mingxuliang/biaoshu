export type ProductLibraryCategory = "软件系统" | "货物设备" | "综合方案";
export type ProductKind = "软件功能" | "货物产品" | "模块方案";
export type ProductStatus = "待审核" | "已入库" | "已停用";
export type ParseJobStatus = "解析中" | "已完成" | "抽取失败";
export type ProductMergeStatus = "新增" | "并入已有" | "疑似重复" | "参数冲突";

export interface ProductImage {
  id: string;
  caption: string;
  kind: "界面" | "架构" | "流程" | "实物";
  url?: string;
  file?: File;
}

export interface ProductLibrary {
  id: string;
  name: string;
  category: ProductLibraryCategory;
  description: string;
  owner: string;
  createdAt: string;
  updatedAt: string;
  featureCount?: number;
  pendingCount?: number;
  imageCount?: number;
  sourceCount?: number;
}

export interface ProductFeatureSource {
  docId: string;
  filename: string;
}

export interface ProductItem {
  id: string;
  libraryId: string;
  name: string;
  kind: ProductKind;
  module: string;
  params: string;
  intro: string;
  bidCopy: string;
  brand: string;
  model: string;
  unit: string;
  sourceDoc: string;
  status: ProductStatus;
  mergeStatus?: ProductMergeStatus;
  aliases?: string[];
  sources?: ProductFeatureSource[];
  evidence?: { heading?: string; excerpt?: string }[];
  paramsConflict?: string[];
  suspectedIds?: string[];
  images: ProductImage[];
  updatedAt: string;
}

export interface ProductParseJob {
  id: string;
  libraryId: string;
  filename: string;
  status: ParseJobStatus;
  extracted: number;
  merged?: number;
  suspected?: number;
  conflicts?: number;
  sizeLabel: string;
  uploadedAt: string;
  note: string;
  error?: string | null;
}

export const PRODUCT_LIBRARY_CATEGORIES: ProductLibraryCategory[] = ["软件系统", "货物设备", "综合方案"];
export const PRODUCT_KINDS: ProductKind[] = ["软件功能", "货物产品", "模块方案"];
