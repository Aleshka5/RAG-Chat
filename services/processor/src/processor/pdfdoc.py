from __future__ import annotations

import pymupdf


class CorruptPdf(Exception):
    pass


class OpenedPdf:
    def __init__(self, data: bytes) -> None:
        if not data:
            raise CorruptPdf("empty")
        try:
            self._doc = pymupdf.open(stream=data, filetype="pdf")
        except (pymupdf.FileDataError, pymupdf.EmptyFileError) as exc:
            raise CorruptPdf("unreadable") from exc
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            raise CorruptPdf("unreadable") from exc
        try:
            if self._doc.needs_pass or not self._doc.is_pdf:
                raise CorruptPdf("unreadable")
            if self._doc.page_count < 0:
                raise CorruptPdf("unreadable")
            if self._doc.page_count > 0:
                self._doc.load_page(0)
        except CorruptPdf:
            self._doc.close()
            raise
        except (KeyboardInterrupt, SystemExit):
            self._doc.close()
            raise
        except Exception as exc:
            self._doc.close()
            raise CorruptPdf("unreadable") from exc

    @property
    def page_count(self) -> int:
        return int(self._doc.page_count)

    def page_text(self, page_number: int) -> str:
        try:
            page = self._doc.load_page(page_number - 1)
            text = page.get_text("text")
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            raise CorruptPdf("unreadable") from exc
        return text if isinstance(text, str) else ""

    def render_png(self, page_number: int, dpi: int) -> bytes:
        try:
            page = self._doc.load_page(page_number - 1)
            zoom = dpi / 72.0
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            return pixmap.tobytes("png")
        except CorruptPdf:
            raise
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            raise CorruptPdf("unreadable") from exc

    def close(self) -> None:
        self._doc.close()
