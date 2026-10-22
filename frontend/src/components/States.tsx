export function LoadingBlock({ label }: { label: string }) {
  return (
    <p className="empty" role="status">
      {label}
    </p>
  );
}

export function EmptyBlock({ title, text }: { title: string; text: string }) {
  return (
    <div className="empty" role="status">
      <p>{title}</p>
      {text ? <p>{text}</p> : null}
    </div>
  );
}

export function ErrorBlock({ text, onRetry }: { text: string; onRetry?: () => void }) {
  return (
    <div className="error-block" role="alert">
      <p>{text}</p>
      {onRetry ? (
        <button type="button" className="btn" onClick={onRetry}>
          Повторить
        </button>
      ) : null}
    </div>
  );
}
