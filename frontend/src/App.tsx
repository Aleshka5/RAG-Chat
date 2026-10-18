import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { LoadingBlock } from "./components/States";
import { ChatPage } from "./pages/ChatPage";
import { FilesPage } from "./pages/FilesPage";
import { useSessionStore } from "./stores/sessionStore";

const PreviewPage = lazy(() => import("./pages/PreviewPage"));

export function App() {
  const blocked = useSessionStore((state) => state.blocked);
  if (blocked) {
    return (
      <div className="mx-auto max-w-lg px-4 py-16">
        <div className="rounded-2xl border border-line bg-sheet px-6 py-8" role="alert">
          <h1 className="serif text-3xl">Доступ закрыт</h1>
          <p className="mt-3 text-muted">Запрос не повторяется.</p>
        </div>
      </div>
    );
  }
  return (
    <Layout>
      <Suspense fallback={<LoadingBlock label="Открываем PDF…" />}>
        <Routes>
          <Route path="/" element={<Navigate to="/files" replace />} />
          <Route path="/files" element={<FilesPage />} />
          <Route path="/files/:fileId" element={<PreviewPage />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/chat/:chatId" element={<ChatPage />} />
          <Route path="*" element={<Navigate to="/files" replace />} />
        </Routes>
      </Suspense>
    </Layout>
  );
}
