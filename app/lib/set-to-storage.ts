import { useCookie } from "nuxt/app";

export function setToStorage(key: string, value: unknown) {
  if (typeof window === "undefined") {
    const cookie = useCookie(key, {
      path: "/",
      secure: true,
      sameSite: "strict",
      maxAge: 60 * 60 * 24 * 31,
    });
    cookie.value = JSON.stringify(value);
  } else {
    localStorage.set(key, JSON.stringify(value));
  }
}
