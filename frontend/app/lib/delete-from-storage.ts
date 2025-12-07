import { useCookie } from "nuxt/app";

export function deleteFromStorage(key: string) {
  if (typeof window === "undefined") {
    const cookie = useCookie(key);
    cookie.value = null;
  }

  localStorage.removeItem(key);
}
