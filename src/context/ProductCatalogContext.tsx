import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  createProductFeature,
  createProductLibrary,
  deleteProductFeature,
  deleteProductLibrary,
  listProductFeatures,
  listProductLibraries,
  listProductSourceDocs,
  mergeProductFeatures,
  patchProductFeature,
  resolveProductPair,
  updateProductLibrary,
  uploadProductFeatureImages,
  type ProductFeatureIn,
  type ProductLibraryIn,
} from "@/lib/api";
import type { ProductItem, ProductLibrary, ProductParseJob } from "@/mocks/products";

interface ProductCatalogValue {
  libraries: ProductLibrary[];
  items: ProductItem[];
  jobs: ProductParseJob[];
  loading: boolean;
  getLibrary: (id: string | undefined) => ProductLibrary | undefined;
  itemsOf: (libraryId: string) => ProductItem[];
  jobsOf: (libraryId: string) => ProductParseJob[];
  refreshLibraries: () => Promise<void>;
  loadLibraryContents: (libraryId: string) => Promise<void>;
  addLibrary: (input: ProductLibraryIn) => Promise<ProductLibrary>;
  updateLibrary: (id: string, patch: ProductLibraryIn) => Promise<void>;
  deleteLibrary: (id: string) => Promise<void>;
  createItem: (libraryId: string, payload: ProductFeatureIn, images?: { file: File; caption: string; kind: string }[]) => Promise<ProductItem>;
  updateItem: (id: string, payload: Partial<ProductFeatureIn>, images?: { file: File; caption: string; kind: string }[]) => Promise<ProductItem>;
  deleteItem: (id: string) => Promise<void>;
  mergeItems: (keepId: string, otherId: string) => Promise<void>;
  resolveItems: (libraryId: string, keepId: string, dropId: string, action: "merge" | "keep_both") => Promise<void>;
}

const ProductCatalogContext = createContext<ProductCatalogValue | null>(null);

export function ProductCatalogProvider({ children }: { children: ReactNode }) {
  const [libraries, setLibraries] = useState<ProductLibrary[]>([]);
  const [items, setItems] = useState<ProductItem[]>([]);
  const [jobs, setJobs] = useState<ProductParseJob[]>([]);
  const [activeLibraryId, setActiveLibraryId] = useState<string>("");
  const [loading, setLoading] = useState(false);

  const refreshLibraries = useCallback(async () => {
    const list = await listProductLibraries();
    setLibraries(list);
  }, []);

  useEffect(() => {
    refreshLibraries().catch(() => {
      setLibraries([]);
    });
  }, [refreshLibraries]);

  const loadLibraryContents = useCallback(async (libraryId: string) => {
    setActiveLibraryId(libraryId);
    setLoading(true);
    try {
      const [feats, docs] = await Promise.all([listProductFeatures(libraryId), listProductSourceDocs(libraryId)]);
      setItems(feats);
      setJobs(docs);
    } finally {
      setLoading(false);
    }
  }, []);

  const getLibrary = useCallback((id: string | undefined) => libraries.find((l) => l.id === id), [libraries]);
  const itemsOf = useCallback(
    (libraryId: string) => (libraryId === activeLibraryId ? items : items.filter((p) => p.libraryId === libraryId)),
    [activeLibraryId, items],
  );
  const jobsOf = useCallback(
    (libraryId: string) => (libraryId === activeLibraryId ? jobs : jobs.filter((j) => j.libraryId === libraryId)),
    [activeLibraryId, jobs],
  );

  const addLibrary = useCallback(
    async (input: ProductLibraryIn) => {
      const created = await createProductLibrary(input);
      await refreshLibraries();
      return created;
    },
    [refreshLibraries],
  );

  const updateLibrary = useCallback(
    async (id: string, patch: ProductLibraryIn) => {
      await updateProductLibrary(id, patch);
      await refreshLibraries();
    },
    [refreshLibraries],
  );

  const deleteLibrary = useCallback(
    async (id: string) => {
      await deleteProductLibrary(id);
      if (activeLibraryId === id) {
        setItems([]);
        setJobs([]);
        setActiveLibraryId("");
      }
      await refreshLibraries();
    },
    [activeLibraryId, refreshLibraries],
  );

  const createItem = useCallback(
    async (libraryId: string, payload: ProductFeatureIn, images?: { file: File; caption: string; kind: string }[]) => {
      let feat = await createProductFeature(libraryId, payload);
      if (images?.length) {
        feat = await uploadProductFeatureImages(
          feat.id,
          images.map((i) => i.file),
          images.map((i) => i.caption),
          images.map((i) => i.kind),
        );
      }
      await loadLibraryContents(libraryId);
      await refreshLibraries();
      return feat;
    },
    [loadLibraryContents, refreshLibraries],
  );

  const updateItem = useCallback(
    async (id: string, payload: Partial<ProductFeatureIn>, images?: { file: File; caption: string; kind: string }[]) => {
      let feat = await patchProductFeature(id, payload);
      if (images?.length) {
        feat = await uploadProductFeatureImages(
          feat.id,
          images.map((i) => i.file),
          images.map((i) => i.caption),
          images.map((i) => i.kind),
        );
      }
      await loadLibraryContents(feat.libraryId);
      await refreshLibraries();
      return feat;
    },
    [loadLibraryContents, refreshLibraries],
  );

  const deleteItem = useCallback(
    async (id: string) => {
      const current = items.find((p) => p.id === id);
      await deleteProductFeature(id);
      if (current) {
        await loadLibraryContents(current.libraryId);
        await refreshLibraries();
      } else {
        setItems((prev) => prev.filter((p) => p.id !== id));
      }
    },
    [items, loadLibraryContents, refreshLibraries],
  );

  const mergeItems = useCallback(
    async (keepId: string, otherId: string) => {
      const feat = await mergeProductFeatures(keepId, otherId);
      await loadLibraryContents(feat.libraryId);
      await refreshLibraries();
    },
    [loadLibraryContents, refreshLibraries],
  );

  const resolveItems = useCallback(
    async (libraryId: string, keepId: string, dropId: string, action: "merge" | "keep_both") => {
      await resolveProductPair(libraryId, keepId, dropId, action);
      await loadLibraryContents(libraryId);
      await refreshLibraries();
    },
    [loadLibraryContents, refreshLibraries],
  );

  const value = useMemo(
    () => ({
      libraries,
      items,
      jobs,
      loading,
      getLibrary,
      itemsOf,
      jobsOf,
      refreshLibraries,
      loadLibraryContents,
      addLibrary,
      updateLibrary,
      deleteLibrary,
      createItem,
      updateItem,
      deleteItem,
      mergeItems,
      resolveItems,
    }),
    [
      libraries,
      items,
      jobs,
      loading,
      getLibrary,
      itemsOf,
      jobsOf,
      refreshLibraries,
      loadLibraryContents,
      addLibrary,
      updateLibrary,
      deleteLibrary,
      createItem,
      updateItem,
      deleteItem,
      mergeItems,
      resolveItems,
    ],
  );

  return <ProductCatalogContext.Provider value={value}>{children}</ProductCatalogContext.Provider>;
}

export function useProductCatalog() {
  const ctx = useContext(ProductCatalogContext);
  if (!ctx) throw new Error("useProductCatalog must be used within ProductCatalogProvider");
  return ctx;
}
