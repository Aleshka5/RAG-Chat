import { lazy, Suspense, useEffect } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { LoadingBlock } from "./components/States";
import { ChatPage } from "./pages/ChatPage";
import { FilesPage } from "./pages/FilesPage";
import { useSessionStore } from "./stores/sessionStore";

const PreviewPage = lazy(() => import("./pages/PreviewPage"));

export function App() {
  const blocked = useSessionStore((state) => state.blocked);
  useEffect(() => {
    if (!blocked) return;
    document.title = "Доступ закрыт · Документы · Filenkov";
  }, [blocked]);
  if (blocked) {
    return (
      <Layout>
        <div className="auth-page">
          <div className="panel" role="alert">
            <div className="stack">
              <p className="kicker">Документы</p>
              <h1>Доступ закрыт</h1>
              <p className="muted">Запрос не повторяется.</p>
            </div>
          </div>
        </div>
      </Layout>
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
