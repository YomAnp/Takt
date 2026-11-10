import dialogPolyfill from "dialog-polyfill";
import "dialog-polyfill/dist/dialog-polyfill.css";
import { useEffect, useId, useRef, type ReactNode } from "react";
import { X } from "lucide-react";
import { useTelegramBack } from "../lib/telegram";

export function Sheet({
  title,
  children,
  close,
  canClose = true,
}: {
  title: string;
  children: ReactNode;
  close(): void;
  canClose?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useTelegramBack(canClose ? close : null, 10);
  useEffect(() => {
    const element = dialog.current;
    const previous = document.activeElement as HTMLElement | null;
    if (element && typeof element.showModal !== "function")
      dialogPolyfill.registerDialog(element);
    element?.showModal();
    document.body.classList.add("has-sheet");
    return () => {
      element?.close();
      document.body.classList.remove("has-sheet");
      previous?.focus();
    };
  }, []);
  return (
    <dialog
      ref={dialog}
      className="sheet"
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        if (canClose) close();
      }}
      onClick={(event) => {
        if (event.target !== event.currentTarget) return;
        const bounds = event.currentTarget.getBoundingClientRect();
        if (
          event.clientX < bounds.left ||
          event.clientX > bounds.right ||
          event.clientY < bounds.top ||
          event.clientY > bounds.bottom
        )
          if (canClose) close();
      }}
    >
      <div className="sheet-head">
        <h2 id={titleId}>{title}</h2>
        <button
          className="icon-button"
          aria-label="Закрыть"
          disabled={!canClose}
          onClick={close}
        >
          <X aria-hidden="true" size={21} />
        </button>
      </div>
      {children}
    </dialog>
  );
}
