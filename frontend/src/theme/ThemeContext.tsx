import { createContext, useContext, useEffect, useMemo, useState } from "react";

import { DEFAULT_THEME, isThemeId, type ThemeId } from "./themes";

const STORAGE_KEY = "sv-theme";

interface ThemeContextValue {
  theme: ThemeId;
  setTheme: (theme: ThemeId) => void;
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: DEFAULT_THEME,
  setTheme: () => {},
});

function loadTheme(): ThemeId {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (isThemeId(saved)) return saved;
  // старые значения тумблера «светлая/тёмная»
  if (saved === "dark") return "amber";
  if (saved === "light") return "light";
  return DEFAULT_THEME;
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<ThemeId>(loadTheme);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(STORAGE_KEY, theme);
  }, [theme]);

  const value = useMemo(() => ({ theme, setTheme }), [theme]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext);
}
