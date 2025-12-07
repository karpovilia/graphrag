import { jsonParse } from "@krainovsd/js-helpers";
import { useCookie } from "nuxt/app";

export function getFromStorage<T = unknown>(key: string): T | null {
  if (typeof window === "undefined") {
    const cookie = useCookie(key);

    return cookie.value ? jsonParse<T>(cookie.value) : null;
  }

  return jsonParse<T>(localStorage.get(key));
}
