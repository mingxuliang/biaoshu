/** 生产构建可设 VITE_HIDE_WRITER=1，隐藏撰写工作台入口与路由。 */
export const hideWriter =
  import.meta.env.VITE_HIDE_WRITER === "1" || import.meta.env.VITE_HIDE_WRITER === "true";
