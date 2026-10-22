import { create } from "zustand";
import { deleteFile, listFiles, uploadFile } from "../api/files";
import { AccessBlockedError, ApiError, AuthRedirectError } from "../api/client";
import { requestErrorLabel } from "../shared/labels";
import type { FileCard, FileRecord } from "../types";

export const FILES_PAGE_LIMIT = 50;

type Notice = {
  tone: "error" | "info";
  text: string;
  fileId?: string;
};

type FilesState = {
  items: FileCard[];
  limit: number;
  offset: number;
  total: number;
  phase: "idle" | "loading" | "ready" | "error";
  errorMessage: string | null;
  pollError: string | null;
  notice: Notice | null;
  uploading: boolean;
  load: (options?: { silent?: boolean }) => Promise<void>;
  upload: (file: File) => Promise<void>;
  remove: (fileId: string) => Promise<void>;
  setOffset: (offset: number) => void;
  clearNotice: () => void;
};

let loadSeq = 0;
const pendingDeleteIds = new Set<string>();

function applyServerItems(current: FileCard[], incoming: FileRecord[]): FileCard[] {
  const locals = current.filter((item) => item.local);
  const server = incoming.map((item) =>
    pendingDeleteIds.has(item.file_id) ? { ...item, status: "deleting" as const, progress: null } : item,
  );
  return [...locals, ...server];
}

function uploadNotice(error: unknown): Notice {
  if (error instanceof ApiError) {
    const fileId = typeof error.details?.file_id === "string" ? error.details.file_id : undefined;
    return {
      tone: "error",
      text: requestErrorLabel(error.status, error.code, "Could not upload the file"),
      fileId,
    };
  }
  return { tone: "error", text: "Could not upload the file" };
}

export const useFilesStore = create<FilesState>((set, get) => ({
  items: [],
  limit: FILES_PAGE_LIMIT,
  offset: 0,
  total: 0,
  phase: "idle",
  errorMessage: null,
  pollError: null,
  notice: null,
  uploading: false,
  clearNotice: () => set({ notice: null }),
  setOffset: (offset) => {
    set({ offset });
    void get().load();
  },
  load: async (options) => {
    const silent = options?.silent ?? false;
    const seq = ++loadSeq;
    if (!silent && get().items.filter((item) => !item.local).length === 0) {
      set({ phase: "loading", errorMessage: null });
    }
    try {
      const page = await listFiles(get().limit, get().offset);
      if (seq !== loadSeq) return;
      set((state) => ({
        items: applyServerItems(state.items, page.items),
        limit: page.limit,
        offset: page.offset,
        total: page.total,
        phase: "ready",
        errorMessage: null,
        pollError: null,
      }));
    } catch (error) {
      if (seq !== loadSeq) return;
      if (error instanceof AccessBlockedError || error instanceof AuthRedirectError) return;
      if (get().items.filter((item) => !item.local).length === 0) {
        set({ phase: "error", errorMessage: "Could not load the file list", pollError: null });
      } else {
        set({ pollError: "Could not refresh the list" });
      }
    }
  },
  upload: async (file) => {
    const tempId = `local-${crypto.randomUUID()}`;
    const now = new Date().toISOString();
    const optimistic: FileCard = {
      file_id: tempId,
      file_name: file.name,
      file_size: file.size,
      status: "uploaded",
      page_count: null,
      error: null,
      progress: null,
      created_at: now,
      updated_at: now,
      local: true,
    };
    set((state) => ({
      uploading: true,
      notice: null,
      items: [optimistic, ...state.items],
      phase: state.phase === "idle" ? "ready" : state.phase,
    }));
    try {
      const created = await uploadFile(file);
      set((state) => ({
        items: state.items.map((item) => (item.file_id === tempId ? created : item)),
      }));
      await get().load({ silent: true });
    } catch (error) {
      set((state) => ({
        items: state.items.filter((item) => item.file_id !== tempId),
      }));
      if (error instanceof AccessBlockedError || error instanceof AuthRedirectError) return;
      if (error instanceof ApiError && (error.status === 500 || error.code === "enqueue_failed")) {
        await get().load({ silent: true });
      }
      set({ notice: uploadNotice(error) });
    } finally {
      set({ uploading: false });
    }
  },
  remove: async (fileId) => {
    const previous = get().items.find((item) => item.file_id === fileId);
    if (!previous || previous.local) return;
    pendingDeleteIds.add(fileId);
    set((state) => ({
      notice: null,
      items: state.items.map((item) =>
        item.file_id === fileId ? { ...item, status: "deleting", progress: null } : item,
      ),
    }));
    try {
      await deleteFile(fileId);
      pendingDeleteIds.delete(fileId);
      await get().load({ silent: true });
    } catch (error) {
      pendingDeleteIds.delete(fileId);
      if (error instanceof AccessBlockedError || error instanceof AuthRedirectError) return;
      if (error instanceof ApiError && (error.status === 500 || error.code === "enqueue_failed")) {
        set({
          notice: {
            tone: "error",
            text: requestErrorLabel(error.status, error.code, "Could not queue the file"),
          },
        });
        await get().load({ silent: true });
        return;
      }
      set((state) => ({
        items: state.items.map((item) => (item.file_id === fileId ? previous : item)),
        notice: {
          tone: "error",
          text:
            error instanceof ApiError
              ? requestErrorLabel(error.status, error.code, "Could not delete the file")
              : "Could not delete the file",
        },
      }));
    }
  },
}));

export function resetFilesStore(): void {
  loadSeq += 1;
  pendingDeleteIds.clear();
  useFilesStore.setState(useFilesStore.getInitialState(), true);
}
