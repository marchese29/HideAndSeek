import { create } from 'zustand';

export type ToastSeverity = 'info' | 'warning';

export interface Toast {
  id: string;
  message: string;
  severity: ToastSeverity;
}

interface ToastState {
  current: Toast | null;
  queue: Toast[];
}

interface ToastActions {
  push: (input: { message: string; severity?: ToastSeverity }) => void;
  dismiss: (id: string) => void;
  clear: () => void;
}

let nextId = 0;

export const useToastStore = create<ToastState & ToastActions>((set) => ({
  current: null,
  queue: [],

  push: ({ message, severity = 'info' }) => {
    const toast: Toast = {
      id: `toast-${++nextId}`,
      message,
      severity,
    };
    set((state) => {
      if (state.current === null) return { current: toast };
      return { queue: [...state.queue, toast] };
    });
  },

  dismiss: (id) => {
    set((state) => {
      if (state.current?.id !== id) return state;
      if (state.queue.length === 0) return { current: null };
      const [next, ...rest] = state.queue;
      return { current: next, queue: rest };
    });
  },

  clear: () => {
    set({ current: null, queue: [] });
  },
}));
