export interface HeadingNode {
  heading: string;
  sliceCount: number;
  depth: number;
  imageCount: number;
  children: HeadingNode[];
}

const NUM = /^(\d+(?:\.\d+)*)/;
const CN1 = /^[一二三四五六七八九十]+[、.．]/;
const CN2 = /^[（(][一二三四五六七八九十\d]+[)）]/;

export function headingDepth(heading: string): number {
  const text = (heading || "").trim();
  const numbered = text.match(NUM);
  if (numbered) return Math.min(numbered[1].split(".").length, 6);
  if (CN1.test(text)) return 1;
  if (CN2.test(text)) return 2;
  return 1;
}

function fromApi(
  ch: { heading: string; sliceCount: number; imageCount?: number; children?: unknown[] },
  depth: number,
): HeadingNode {
  const children = Array.isArray(ch.children)
    ? (ch.children as Array<{ heading: string; sliceCount: number; imageCount?: number; children?: unknown[] }>).map(
        (c) => fromApi(c, depth + 1),
      )
    : [];
  return {
    heading: ch.heading,
    sliceCount: ch.sliceCount,
    depth,
    imageCount: ch.imageCount ?? 0,
    children,
  };
}

export function nestHeadings(
  chapters: {
    heading: string;
    sliceCount: number;
    level?: string;
    imageCount?: number;
    children?: unknown[];
  }[],
): HeadingNode[] {
  const hasNested = chapters.some((c) => (c.children && c.children.length > 0));
  const mixedLevel = chapters.some((c) => c.level === "二级" || c.level === "三级");
  if (hasNested || mixedLevel) {
    return chapters.map((c) => fromApi(c, 1));
  }
  const roots: HeadingNode[] = [];
  const stack: HeadingNode[] = [];
  for (const ch of chapters) {
    const depth = headingDepth(ch.heading);
    const node: HeadingNode = {
      heading: ch.heading,
      sliceCount: ch.sliceCount,
      depth,
      imageCount: ch.imageCount ?? 0,
      children: [],
    };
    while (stack.length && stack[stack.length - 1].depth >= depth) stack.pop();
    if (!stack.length) roots.push(node);
    else stack[stack.length - 1].children.push(node);
    stack.push(node);
  }
  return roots;
}

export function collectHeadings(node: HeadingNode): string[] {
  return [node.heading, ...node.children.flatMap(collectHeadings)];
}
