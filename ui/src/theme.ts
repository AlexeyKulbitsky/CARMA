export type Theme = "system" | "light" | "dark";

const key = "carma.theme";

export function savedTheme(): Theme {
  try {
    const value = localStorage.getItem(key);
    return value === "light" || value === "dark" ? value : "system";
  } catch { return "system"; }
}

export function applyTheme(theme: Theme) {
  if (theme === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
  try { localStorage.setItem(key, theme); } catch { /* Storage may be unavailable in an embedded window. */ }
}
