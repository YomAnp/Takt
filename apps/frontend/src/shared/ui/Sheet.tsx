import dialogPolyfill from "dialog-polyfill";
import "dialog-polyfill/dist/dialog-polyfill.css";
import { useEffect, useRef, type ReactNode } from "react";
import { X } from "lucide-react";
export function Sheet({
  title,
  children,
  close,
}: {
  title: string;
  children: ReactNode;
  close(): void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (dialog.current && typeof dialog.current.showModal !== "function")
      dialogPolyfill.registerDialog(dialog.current);
    dialog.current?.showModal();
    return () => dialog.current?.close();
  }, []);
  return (
    <dialog
      ref={dialog}
      className="sheet"
      aria-labelledby="sheet-title"
      onCancel={close}
      onClick={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <div className="sheet-head">
        <h2 id="sheet-title">{title}</h2>
        <button className="icon-button" aria-label="Закрыть" onClick={close}>
          <X size={22} />
        </button>
      </div>
      {children}
    </dialog>
  );
}
