import { THEME_CONFIG as THEME, type ThemeName, type ThemeVariableConfig } from "@krainovsd/vue-ui";

export const PAGES = {
  main: "main",
  graph: "graph",
} as const;

export const THEME_CONFIG: Record<ThemeName, ThemeVariableConfig> = {
  light: THEME.light,
  dark: THEME.dark,
};
export const DEFAULT_THEME: ThemeName = "dark";
export const REQUEST_DELAY = 1500;
