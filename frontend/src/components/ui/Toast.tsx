import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { IconAlertCircle, IconCheckCircle, IconInfo } from "../icons";

interface ToastItem { id: number; message: string; tone: "success" | "danger" | "info" }
type ToastFn = (message: string, tone?: ToastItem["tone"]) => void;
const ToastContext = createContext<ToastFn | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const counter = useRef(0);

  const push = useCallback<ToastFn>((message, tone = "info") => {
    const id = ++counter.current;
    setItems(list => [...list, { id, message, tone }]);
    setTimeout(() => setItems(list => list.filter(item => item.id !== id)), 4500);
  }, []);

  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="ui-toast-viewport" role="status" aria-live="polite">
        {items.map(item => (
          <div key={item.id} className={`ui-toast ui-tone-${item.tone}`}>
            {item.tone === "success" ? <IconCheckCircle size={16} /> : item.tone === "danger" ? <IconAlertCircle size={16} /> : <IconInfo size={16} />}
            <span>{item.message}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastFn {
  const value = useContext(ToastContext);
  if (!value) throw new Error("useToast must be used inside ToastProvider");
  return value;
}
