import DOMPurify from "dompurify";
import { marked } from "marked";

export function mdFormat(text: string) {
  return DOMPurify.sanitize(marked.parse(text, { async: false }));
}
