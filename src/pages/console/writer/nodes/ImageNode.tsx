import type { ReactElement } from "react";
import AuthImage from "../../components/AuthImage";
import {
  $applyNodeReplacement,
  DecoratorNode,
  type DOMConversionMap,
  type DOMConversionOutput,
  type DOMExportOutput,
  type EditorConfig,
  type LexicalNode,
  type NodeKey,
  type SerializedLexicalNode,
  type Spread,
} from "lexical";

export type SerializedImageNode = Spread<
  {
    src: string;
    alt: string;
  },
  SerializedLexicalNode
>;

function convertImageElement(domNode: Node): DOMConversionOutput | null {
  if (!(domNode instanceof HTMLImageElement)) return null;
  const src = domNode.getAttribute("src") || "";
  if (!src) return null;
  return { node: $createImageNode(src, domNode.getAttribute("alt") || "") };
}

export class ImageNode extends DecoratorNode<ReactElement> {
  __src: string;
  __alt: string;

  static getType(): string {
    return "image";
  }

  static clone(node: ImageNode): ImageNode {
    return new ImageNode(node.__src, node.__alt, node.__key);
  }

  constructor(src: string, alt = "", key?: NodeKey) {
    super(key);
    this.__src = src;
    this.__alt = alt;
  }

  static importJSON(serialized: SerializedImageNode): ImageNode {
    return $createImageNode(serialized.src, serialized.alt);
  }

  exportJSON(): SerializedImageNode {
    return { type: "image", version: 1, src: this.__src, alt: this.__alt };
  }

  static importDOM(): DOMConversionMap | null {
    return {
      img: () => ({ conversion: convertImageElement, priority: 0 }),
    };
  }

  exportDOM(): DOMExportOutput {
    const img = document.createElement("img");
    img.setAttribute("src", this.__src);
    img.setAttribute("alt", this.__alt);
    return { element: img };
  }

  createDOM(_config: EditorConfig): HTMLElement {
    const wrap = document.createElement("div");
    wrap.className = "editor-image-wrap";
    return wrap;
  }

  updateDOM(): false {
    return false;
  }

  decorate(): ReactElement {
    return (
      <figure className="my-3 flex flex-col items-center">
        <AuthImage
          src={this.__src}
          alt={this.__alt}
          eager
          fallbackText="图片加载失败"
          className="max-h-72 w-auto max-w-full object-contain"
        />
        {this.__alt ? (
          <figcaption className="mt-1 text-center text-[11px] text-foreground-500">{this.__alt}</figcaption>
        ) : null}
      </figure>
    );
  }

  isInline(): false {
    return false;
  }

  getSrc(): string {
    return this.__src;
  }

  getAlt(): string {
    return this.__alt;
  }
}

export function $createImageNode(src: string, alt = ""): ImageNode {
  return $applyNodeReplacement(new ImageNode(src, alt));
}

export function $isImageNode(node: LexicalNode | null | undefined): node is ImageNode {
  return node instanceof ImageNode;
}
