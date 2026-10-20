#!/bin/sh
# The image starts as root so a fresh model-cache volume can be given to ocr.
# The server process itself is uid 10001. setpriv execs, so it stays PID 1.
set -eu
chown -R ocr:ocr /var/cache/huggingface
exec setpriv --reuid=ocr --regid=ocr --init-groups python -m ocr_service
