import os

# Before NumPy, OpenCV, or Paddle initialize their math libraries.
# One OCR process keeps one core. Concurrent pages are separate processes.
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"

from ocr_service.main import main  # noqa: E402

main()
