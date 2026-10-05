import { useState } from "react";
import { applyTheme, savedTheme, type Theme } from "./theme";

export function ThemeControl() {
  const [theme, setTheme] = useState<Theme>(savedTheme);
  return <label className="theme-control">Theme
    <select aria-label="Color theme" value={theme} onChange={(event) => {
      const next = event.target.value as Theme;
      setTheme(next);
      applyTheme(next);
    }}>
      <option value="system">System</option><option value="light">Light</option><option value="dark">Dark</option>
    </select>
  </label>;
}
