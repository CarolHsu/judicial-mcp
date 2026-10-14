#!/usr/bin/env bash
# Full ingestion: every step is incremental, so this is safe to re-run after an interruption.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/logs
log() { echo "[$(date '+%F %T')] $*"; }

log "crawl";            uv run judicial-mcp crawl
log "download";         uv run judicial-mcp download
log "extract + index";  uv run judicial-mcp extract
log "ocr image-only pages"; uv run judicial-mcp ocr
log "upgrade site OCR pages with Apple Vision"; uv run judicial-mcp ocr --upgrade-site-ocr
log "final stats";      uv run judicial-mcp stats
log "done"
