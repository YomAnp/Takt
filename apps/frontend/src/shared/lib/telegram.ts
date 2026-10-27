interface TelegramApp {
  initData: string;
  colorScheme?: string;
  ready(): void;
  expand(): void;
  setHeaderColor?(value: string): void;
  setBackgroundColor?(value: string): void;
  onEvent?(name: string, callback: () => void): void;
  offEvent?(name: string, callback: () => void): void;
}
declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramApp };
  }
}
export function applyTelegramTheme(app: TelegramApp) {
  if (app.colorScheme) {
    document.documentElement.dataset.theme = app.colorScheme;
    const background = app.colorScheme === "dark" ? "#202e27" : "#ffffff";
    app.setHeaderColor?.(background);
    app.setBackgroundColor?.(background);
  }
}
export function telegram() {
  const app = window.Telegram?.WebApp;
  if (app) applyTelegramTheme(app);
  app?.ready();
  app?.expand();
  return app;
}
