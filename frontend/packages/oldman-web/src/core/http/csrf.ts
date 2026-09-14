import { getCookie } from "./cookies";

export function isStateChangingMethod(method: string): boolean {
  return !["GET", "HEAD", "OPTIONS", "TRACE"].includes(method.toUpperCase());
}

export function getCsrfToken(cookieName = "csrftoken"): string | null {
  const input = document.querySelector<HTMLInputElement>("input[name=csrfmiddlewaretoken]");
  if (input?.value) return input.value;

  const meta = document.querySelector<HTMLMetaElement>("meta[name=csrf-token]");
  if (meta?.content) return meta.content;

  return getCookie(cookieName);
}
