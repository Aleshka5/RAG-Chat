import { useEffect, useRef, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";

const JITTER_FLOOR = 6;
const TRAVEL_THRESHOLD = 24;
const TOP_AT = 8;
const HIDE_BELOW = 96;

export function Layout({ children }: { children: ReactNode }) {
  const location = useLocation();
  const previousPath = useRef<string | null>(null);

  useEffect(() => {
    const root = document.documentElement;
    root.dataset.header = "top";

    let last = Math.max(0, window.scrollY);
    let acc = 0;
    let frame = 0;

    function headerHasFocus(): boolean {
      const active = document.activeElement;
      if (!active) return false;
      const header = document.querySelector(".header");
      return header !== null && header.contains(active);
    }

    function apply(): void {
      frame = 0;
      const y = Math.max(0, window.scrollY);

      if (y < TOP_AT) {
        root.dataset.header = "top";
        last = y;
        acc = 0;
        return;
      }
      if (headerHasFocus()) {
        root.dataset.header = "condensed";
        last = y;
        acc = 0;
        return;
      }

      const delta = y - last;
      if (Math.abs(delta) < JITTER_FLOOR) return;
      acc = Math.sign(delta) === Math.sign(acc) ? acc + delta : delta;
      last = y;

      if (acc > TRAVEL_THRESHOLD && y > HIDE_BELOW) root.dataset.header = "hidden";
      else if (acc < -TRAVEL_THRESHOLD) root.dataset.header = "condensed";
    }

    function onScroll(): void {
      if (frame === 0) frame = window.requestAnimationFrame(apply);
    }

    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      if (frame !== 0) window.cancelAnimationFrame(frame);
      delete root.dataset.header;
    };
  }, []);

  useEffect(() => {
    const main = document.getElementById("main");
    const heading = main?.querySelector("h1");
    const live = document.getElementById("route-announcer");
    if (live && heading) live.textContent = heading.textContent ?? "";
    const changed = previousPath.current !== null && previousPath.current !== location.pathname;
    previousPath.current = location.pathname;
    if (!(heading instanceof HTMLElement)) return;
    heading.tabIndex = -1;
    if (changed) heading.focus();
  }, [location.pathname]);

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <p id="route-announcer" className="sr-only" aria-live="polite" />
      <header className="header">
        <a className="brand" href="https://filenkov.store">
          <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
            <path
              d="M16 3 L29 16 L16 29 L3 16 Z"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.75"
            />
            <circle cx="16" cy="16" r="3.2" fill="var(--accent)" />
          </svg>
          <span className="brand-name">Filenkov</span>
        </a>
        <nav className="service-nav" aria-label="Sections">
          <NavLink to="/files">Files</NavLink>
          <NavLink to="/chat">Chat</NavLink>
        </nav>
      </header>
      <main className="main" id="main" tabIndex={-1}>
        {children}
      </main>
      <footer className="footer">
        <span>Filenkov · Documents</span>
        <span>Sign in with Google · httpOnly cookie on .filenkov.store</span>
      </footer>
    </div>
  );
}
