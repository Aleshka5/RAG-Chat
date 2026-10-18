import type { ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";

function navClass(isActive: boolean): string {
  return `rounded-full px-3 py-1.5 text-sm ${isActive ? "bg-pine text-sheet" : "text-ink hover:bg-white/70"}`;
}

export function Layout({ children }: { children: ReactNode }) {
  const location = useLocation();
  const chatActive = location.pathname === "/chat" || location.pathname.startsWith("/chat/");
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-line bg-paper/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3">
          <div>
            <p className="serif text-xl leading-none">Документы</p>
            <p className="mt-1 text-xs text-muted">Вопросы по вашим PDF</p>
          </div>
          <nav className="flex gap-1" aria-label="Разделы">
            <NavLink to="/files" className={({ isActive }) => navClass(isActive)}>
              Файлы
            </NavLink>
            <NavLink to="/chat" className={() => navClass(chatActive)}>
              Чат
            </NavLink>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
    </div>
  );
}
