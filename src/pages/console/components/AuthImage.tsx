import { useEffect, useState } from "react";
import { useAuth } from "@/context/AuthContext";

interface AuthImageProps {
  src?: string;
  alt?: string;
  className?: string;
}

/** 用登录 token 拉取受保护图片；blob:/data: 本地预览地址原样显示。 */
export default function AuthImage({ src, alt = "", className }: AuthImageProps) {
  const { token } = useAuth();
  const [blobUrl, setBlobUrl] = useState("");

  useEffect(() => {
    if (!src) {
      setBlobUrl("");
      return;
    }
    if (src.startsWith("blob:") || src.startsWith("data:")) {
      setBlobUrl(src);
      return;
    }
    let objectUrl = "";
    let cancelled = false;
    const headers: HeadersInit = {};
    if (token) headers.Authorization = `Bearer ${token}`;
    fetch(src, { headers })
      .then((res) => {
        if (!res.ok) throw new Error(String(res.status));
        return res.blob();
      })
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setBlobUrl(objectUrl);
      })
      .catch(() => {
        if (!cancelled) setBlobUrl("");
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [src, token]);

  if (!blobUrl) {
    return (
      <div className={`flex items-center justify-center bg-background-200 text-foreground-400 ${className || ""}`}>
        <i className="ri-image-line"></i>
      </div>
    );
  }
  return <img src={blobUrl} alt={alt} className={className} />;
}
