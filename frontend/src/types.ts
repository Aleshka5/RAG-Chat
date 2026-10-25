export type FileStatus = "uploaded" | "processing" | "ready" | "error" | "deleting";

export type FileErrorCode =
  | "corrupt_pdf"
  | "storage_read_failed"
  | "embedding_failed"
  | "index_write_failed"
  | "metadata_update_failed"
  | "no_extractable_text"
  | "enqueue_failed"
  | "processing_attempts_exceeded";

export type FileProgress = {
  pages_done: number;
  pages_total: number | null;
  chunks_done: number;
  chunks_total: number | null;
};

export type FileRecord = {
  file_id: string;
  file_name: string;
  file_size: number;
  status: FileStatus;
  page_count: number | null;
  content_type?: string | null;
  error: FileErrorCode | string | null;
  progress: FileProgress | null;
  created_at: string;
  updated_at: string;
};

export type FileCard = FileRecord & {
  local?: boolean;
};

export type FileList = {
  items: FileRecord[];
  limit: number;
  offset: number;
  total: number;
};

export type DeleteAccepted = {
  file_id: string;
  status: "deleting";
};

export type Chat = {
  chat_id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type ChatList = {
  items: Chat[];
  limit: number;
  offset: number;
  total: number;
};

export type Source = {
  file_id: string;
  file_name: string;
  page_number: number;
  chunk_index: number;
  snippet: string;
  score: number;
};

export type ImageHit = {
  file_id: string;
  file_name: string;
  score: number;
  content_path: string;
};

export type SearchMode = "documents" | "images";

export type Message = {
  message_id: string;
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  images?: ImageHit[];
  finish_reason?: "retrieval_only";
  created_at: string;
};

export type ChatDetails = Chat & {
  messages: Message[];
  limit: number;
  offset: number;
  total_messages: number;
};
