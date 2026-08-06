import { create } from 'zustand';

export type ToastTone = 'pending' | 'success' | 'error';

export interface Toast {
  id: string;
  tone: ToastTone;
  title: string;
  /** Optional second line. Long provider error strings land here. */
  detail?: string;
}

interface ToastStore {
  toasts: Toast[];
  /** Adds a toast and returns its id, so a caller can later `update` it. */
  push: (toast: Omit<Toast, 'id'>) => string;
  /** Re-points an existing toast in place — used to turn a `pending` toast
   *  into its outcome without the row disappearing and reappearing. */
  update: (id: string, toast: Omit<Toast, 'id'>) => void;
  dismiss: (id: string) => void;
}

let counter = 0;

/**
 * Transient action feedback, app-wide.
 *
 * There was no such thing before: each page hand-rolled an inline success or
 * error block, which works when the result of the action is on the page and
 * fails when it is not — the downloader's whole outcome is a file appearing in
 * the browser's download tray, and the page said nothing at all.
 *
 * The rule this follows, and the reason it is not sprinkled everywhere:
 * **a toast announces the outcome of an action whose result is not visible
 * where the user is looking.** A form validation error still belongs beside
 * the field it refers to, not in the corner of the screen.
 *
 * Not persisted, unlike themeStore/timezoneStore — a toast that survived a
 * reload would be announcing something that already finished.
 */
export const useToastStore = create<ToastStore>()((set) => ({
  toasts: [],
  push: (toast) => {
    const id = `toast-${(counter += 1)}`;
    set((state) => ({ toasts: [...state.toasts, { ...toast, id }] }));
    return id;
  },
  update: (id, toast) =>
    set((state) => ({
      toasts: state.toasts.map((existing) =>
        existing.id === id ? { ...toast, id } : existing
      ),
    })),
  dismiss: (id) =>
    set((state) => ({ toasts: state.toasts.filter((toast) => toast.id !== id) })),
}));
