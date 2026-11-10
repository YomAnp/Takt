import { useEffect, useRef } from "react";

interface Insets {
  top: number;
  bottom: number;
  left: number;
  right: number;
}
export interface TelegramApp {
  initData: string;
  colorScheme?: string;
  themeParams?: {
    bg_color?: string;
    text_color?: string;
    secondary_bg_color?: string;
    button_color?: string;
    button_text_color?: string;
  };
  viewportHeight?: number;
  viewportStableHeight?: number;
  safeAreaInset?: Partial<Insets>;
  contentSafeAreaInset?: Partial<Insets>;
  ready(): void;
  expand(): void;
  isVersionAtLeast?(version: string): boolean;
  setHeaderColor?(value: string): void;
  setBackgroundColor?(value: string): void;
  setBottomBarColor?(value: string): void;
  openTelegramLink?(url: string): void;
  BackButton?: {
    show(): void;
    hide(): void;
    onClick?(callback: () => void): void;
    offClick?(callback: () => void): void;
  };
  HapticFeedback?: {
    impactOccurred(style: "light" | "medium" | "soft"): void;
    notificationOccurred(type: "success" | "error" | "warning"): void;
  };
  onEvent?(name: string, callback: () => void): void;
  offEvent?(name: string, callback: () => void): void;
}
declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramApp };
  }
}
let connected: TelegramApp | undefined;
let baselineHeight = 0;
const backActions = new Map<symbol, { priority: number; run(): void }>();
const themeStorageKey = "takt.theme";
export type ThemePreference = "dark" | "light";

function storedTheme(): ThemePreference {
  try {
    const value = window.localStorage.getItem(themeStorageKey);
    return value === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export function themePreference(): ThemePreference {
  return storedTheme();
}

export function setThemePreference(value: ThemePreference) {
  try {
    window.localStorage.setItem(themeStorageKey, value);
  } catch {
    // Private WebViews may disable storage; the current session still updates.
  }
  document.documentElement.dataset.theme = value;
  document.documentElement.style.colorScheme = value;
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", value === "dark" ? "#0b1110" : "#ffffff");
}
function syncBack() {
  if (!connected?.BackButton) return;
  if (backActions.size) connected.BackButton.show();
  else connected.BackButton.hide();
}
function back() {
  [...backActions.values()].sort((a, b) => b.priority - a.priority)[0]?.run();
}
export function useTelegramBack(handler: (() => void) | null, priority = 0) {
  const action = useRef(handler);
  action.current = handler;
  const enabled = handler !== null;
  useEffect(() => {
    if (!enabled) return;
    const id = Symbol("back");
    backActions.set(id, { priority, run: () => action.current?.() });
    syncBack();
    return () => {
      backActions.delete(id);
      syncBack();
    };
  }, [enabled, priority]);
}
export function applyTelegramTheme(app: TelegramApp) {
  const preference = storedTheme();
  document.documentElement.dataset.theme = preference;
  const background = preference === "dark" ? "#0b1110" : "#ffffff";
  document.documentElement.style.colorScheme = preference;
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", background);
  if (!app.isVersionAtLeast || app.isVersionAtLeast("6.1")) {
    app.setHeaderColor?.(
      app.isVersionAtLeast && !app.isVersionAtLeast("6.9")
        ? "bg_color"
        : background,
    );
    app.setBackgroundColor?.(background);
  }
  if (!app.isVersionAtLeast || app.isVersionAtLeast("7.10"))
    app.setBottomBarColor?.(background);
}
export function syncTelegramViewport(app = connected) {
  const root = document.documentElement;
  const visible = Math.max(
    1,
    app?.viewportHeight || window.visualViewport?.height || window.innerHeight,
  );
  const stable = Math.max(1, app?.viewportStableHeight || window.innerHeight);
  root.style.setProperty("--app-visible-height", visible + "px");
  root.style.setProperty("--app-viewport-height", stable + "px");
  for (const side of ["top", "bottom", "left", "right"] as const) {
    root.style.setProperty(
      "--app-tg-safe-" + side,
      Math.max(0, app?.safeAreaInset?.[side] || 0) + "px",
    );
    root.style.setProperty(
      "--app-tg-content-" + side,
      Math.max(0, app?.contentSafeAreaInset?.[side] || 0) + "px",
    );
  }
  const focused = document.activeElement;
  const editing =
    focused instanceof HTMLInputElement ||
    focused instanceof HTMLTextAreaElement;
  if (!editing) baselineHeight = visible;
  const keyboard =
    editing &&
    Math.max(baselineHeight, stable, window.innerHeight) - visible > 100;
  root.dataset.keyboard = keyboard ? "open" : "closed";
  root.style.setProperty(
    "--app-keyboard-offset",
    (keyboard ? Math.max(0, window.innerHeight - visible) : 0) + "px",
  );
}
export function telegram() {
  const app = window.Telegram?.WebApp;
  connected = app;
  if (app) {
    applyTelegramTheme(app);
    app.ready();
    app.expand();
  }
  syncTelegramViewport(app);
  syncBack();
  return app;
}
export function observeTelegram(app: TelegramApp | undefined) {
  const viewport = () => syncTelegramViewport(app);
  const events = [
    "viewportChanged",
    "safeAreaChanged",
    "contentSafeAreaChanged",
  ];
  events.forEach((name) => app?.onEvent?.(name, viewport));
  if (app?.BackButton?.onClick) app.BackButton.onClick(back);
  else app?.onEvent?.("backButtonClicked", back);
  window.addEventListener("resize", viewport);
  window.visualViewport?.addEventListener("resize", viewport);
  document.addEventListener("focusin", viewport);
  document.addEventListener("focusout", viewport);
  return () => {
    events.forEach((name) => app?.offEvent?.(name, viewport));
    if (app?.BackButton?.offClick) app.BackButton.offClick(back);
    else app?.offEvent?.("backButtonClicked", back);
    window.removeEventListener("resize", viewport);
    window.visualViewport?.removeEventListener("resize", viewport);
    document.removeEventListener("focusin", viewport);
    document.removeEventListener("focusout", viewport);
  };
}
export function haptic(kind: "selection" | "success" = "selection") {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const feedback = window.Telegram?.WebApp?.HapticFeedback;
  try {
    if (kind === "success") feedback?.notificationOccurred("success");
    else feedback?.impactOccurred("light");
  } catch {
    /* Older clients may not support feedback. */
  }
}
export function incomingInvite(): string | null {
  const url = new URL(window.location.href).searchParams.get("invite");
  const start = new URLSearchParams(
    window.Telegram?.WebApp?.initData || "",
  ).get("start_param");
  const token = url || (start?.startsWith("friend_") ? start.slice(7) : null);
  return token && /^[A-Za-z0-9_-]{16,128}$/.test(token) ? token : null;
}
export function clearIncomingInvite() {
  const url = new URL(window.location.href);
  url.searchParams.delete("invite");
  window.history.replaceState(null, "", url);
}
