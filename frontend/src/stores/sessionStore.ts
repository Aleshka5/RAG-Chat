import { create } from "zustand";

type SessionState = {
  blocked: boolean;
  unavailableFileIds: string[];
  block: () => void;
  markPreviewUnavailable: (fileId: string) => void;
};

export const useSessionStore = create<SessionState>((set) => ({
  blocked: false,
  unavailableFileIds: [],
  block: () => set({ blocked: true }),
  markPreviewUnavailable: (fileId) =>
    set((state) =>
      state.unavailableFileIds.includes(fileId)
        ? state
        : { unavailableFileIds: [...state.unavailableFileIds, fileId] },
    ),
}));

export function resetSessionStore(): void {
  useSessionStore.setState(useSessionStore.getInitialState(), true);
}
