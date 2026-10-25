import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchContentBlob, resolveContentPath } from "../api/files";
import { AccessBlockedError, AuthRedirectError, PreviewUnavailableError } from "../api/client";
import { formatScore } from "../shared/format";
import { useSessionStore } from "../stores/sessionStore";
import type { ImageHit as ImageHitRecord } from "../types";
import { ObjectUrlImage } from "./ObjectUrlImage";

export function ImageHitList({ images }: { images: ImageHitRecord[] }) {
  if (images.length === 0) return null;
  return (
    <ul className="image-list">
      {images.map((image) => (
        <li key={`${image.file_id}-${image.content_path}`}>
          <ImageHit image={image} />
        </li>
      ))}
    </ul>
  );
}

function ImageHit({ image }: { image: ImageHitRecord }) {
  const unavailable = useSessionStore((state) => state.unavailableFileIds.includes(image.file_id));
  const markPreviewUnavailable = useSessionStore((state) => state.markPreviewUnavailable);
  const [blob, setBlob] = useState<Blob | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (unavailable) return;
    const controller = new AbortController();
    let active = true;
    setBlob(null);
    setFailed(false);
    void (async () => {
      try {
        const next = await fetchContentBlob(resolveContentPath(image.file_id, image.content_path), controller.signal);
        if (!active) return;
        setBlob(next);
      } catch (error) {
        if (!active || controller.signal.aborted) return;
        if (error instanceof AuthRedirectError || error instanceof AccessBlockedError) return;
        if (error instanceof PreviewUnavailableError) markPreviewUnavailable(image.file_id);
        setFailed(true);
      }
    })();
    return () => {
      active = false;
      controller.abort();
    };
  }, [image.content_path, image.file_id, markPreviewUnavailable, unavailable]);

  const missing = unavailable || failed;
  return (
    <article className="image-hit">
      <div className="image-hit-thumb">{blob && !missing ? <ObjectUrlImage blob={blob} alt="" /> : null}</div>
      <div>
        <p className="choice-title truncate">{image.file_name}</p>
        <p className="meta nums">Score {formatScore(image.score)}</p>
        {missing ? (
          <p className="hint-danger">Preview unavailable</p>
        ) : (
          <Link className="link" to={`/files/${image.file_id}`}>
            Open
          </Link>
        )}
      </div>
    </article>
  );
}
