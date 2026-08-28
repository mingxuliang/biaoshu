import { memo, useEffect, useRef, useState } from "react";
import { useAuth } from "@/context/AuthContext";

interface AuthImageProps {
  src?: string;
  alt?: string;
  className?: string;
  eager?: boolean;
}

const blobCache = new Map<string, string>();
const inflight = new Map<string, Promise<string>>();

function loadAuthBlob(src: string, token: string | null): Promise<string> {
  const cached = blobCache.get(src);
  if (cached) return Promise.resolve(cached);
  const pending = inflight.get(src);
  if (pending) return pending;
  const headers: HeadersInit = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  const req = fetch(src, { headers, cache: "force-cache" })
    .then((res) => {
      if (!res.ok) throw new Error(String(res.status));
      return res.blob();
    })
    .then((blob) => {
      const url = URL.createObjectURL(blob);
      blobCache.set(src, url);
      inflight.delete(src);
      return url;
    })
    .catch((err) => {
      inflight.delete(src);
      throw err;
    });
  inflight.set(src, req);
  return req;
}

function AuthImage({ src, alt = "", className, eager = false }: AuthImageProps) {
  const { token } = useAuth();
  const hostRef = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(eager);
  const [blobUrl, setBlobUrl] = useState(() => (src && blobCache.get(src)) || "");

  useEffect(() => {
    if (eager || visible) return;
    const node = hostRef.current;
    if (!node) return;
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          io.disconnect();
        }
      },
      { rootMargin: "160px" },
    );
    io.observe(node);
    return () => io.disconnect();
  }, [eager, visible]);

  useEffect(() => {
    if (!src) {
      setBlobUrl("");
      return;
    }
    if (src.startsWith("blob:") || src.startsWith("data:")) {
      setBlobUrl(src);
      return;
    }
    const hit = blobCache.get(src);
    if (hit) {
      setBlobUrl(hit);
      return;
    }
    if (!visible) return;
    let cancelled = false;
    loadAuthBlob(src, token)
      .then((url) => {
        if (!cancelled) setBlobUrl(url);
      })
      .catch(() => {
        if (!cancelled) setBlobUrl("");
      });
    return () => {
      cancelled = true;
    };
  }, [src, token, visible]);

  if (!blobUrl) {
    return (
      <div
        ref={hostRef}
        className={`flex items-center justify-center bg-background-200 text-foreground-400 ${className || ""}`}
      >
        <i className="ri-image-line"></i>
      </div>
    );
  }
  return <img src={blobUrl} alt={alt} className={className} loading={eager ? "eager" : "lazy"} />;
}

export default memo(AuthImage);
