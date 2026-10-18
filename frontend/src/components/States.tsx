export function LoadingBlock({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 rounded-2xl border border-line bg-sheet px-4 py-6 text-muted" role="status">
      <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-r-transparent" />
      <span>{label}</span>
    </div>
  );
}

export function EmptyBlock({ title, text }: { title: string; text: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-line bg-sheet px-5 py-8">
      <h2 className="serif text-2xl">{title}</h2>
      <p className="mt-2 max-w-xl text-muted">{text}</p>
    </div>
  );
}

export function ErrorBlock({ text, onRetry }: { text: string; onRetry?: () => void }) {
  return (
    <div className="rounded-2xl border border-red-200 bg-red-50 px-5 py-6 text-red-950" role="alert">
      <p>{text}</p>
      {onRetry ? (
        <button
          type="button"
          className="mt-3 rounded-full bg-ink px-4 py-2 text-sm text-sheet"
          onClick={onRetry}
        >
          Повторить
        </button>
      ) : null}
    </div>
  );
}
