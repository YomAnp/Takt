import { useEffect, useState } from "react";
export function usePageVisible() {
  const [visible, setVisible] = useState(
    () => document.visibilityState !== "hidden",
  );
  useEffect(() => {
    const activate = () => setVisible(document.visibilityState !== "hidden");
    const deactivate = () => setVisible(false);
    document.addEventListener("visibilitychange", activate);
    const app = window.Telegram?.WebApp;
    app?.onEvent?.("activated", activate);
    app?.onEvent?.("deactivated", deactivate);
    return () => {
      document.removeEventListener("visibilitychange", activate);
      app?.offEvent?.("activated", activate);
      app?.offEvent?.("deactivated", deactivate);
    };
  }, []);
  return visible;
}
