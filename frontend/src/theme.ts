export type ThemePref = "system" | "dark" | "light";
const KEY = "aky-theme";

export function getTheme(): ThemePref {
  try {
    const v = localStorage.getItem(KEY);
    return v === "dark" || v === "light" ? v : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(p: ThemePref) {
  const el = document.documentElement;
  if (p === "system") el.removeAttribute("data-theme");
  else el.setAttribute("data-theme", p);
  try {
    if (p === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, p);
  } catch {
    /* gizli sekme */
  }
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", p === "light" ? "#f3f5fa" : "#060a13");
}
