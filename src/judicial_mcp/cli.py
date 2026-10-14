"""Command line entry point: ingestion steps and the MCP server."""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys

from judicial_mcp.config import Settings, load_settings
from judicial_mcp.db import store
from judicial_mcp.db.connection import connect
from judicial_mcp.db.query import corpus_stats
from judicial_mcp.http import PoliteClient
from judicial_mcp.pdf.extract import METHOD_PENDING, METHOD_SITE_OCR

log = logging.getLogger("judicial_mcp")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="judicial-mcp", description="憲法法庭判決 MCP server")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="run the MCP server (default)")
    serve.add_argument("--http", action="store_true", help="serve Streamable HTTP instead of stdio")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)

    crawl = sub.add_parser("crawl", help="fetch judgment pages and attachment lists")
    crawl.add_argument("--limit", type=int)
    download = sub.add_parser("download", help="download attachment PDFs")
    download.add_argument("--limit", type=int)
    extract = sub.add_parser("extract", help="extract text from downloaded PDFs")
    extract.add_argument("--redo", action="store_true", help="re-extract processed documents (keeps our OCR pages)")
    ocr = sub.add_parser("ocr", help="OCR image-only pages (macOS Apple Vision)")
    ocr.add_argument("--limit-pages", type=int)
    ocr.add_argument("--workers", type=int, default=4, help="parallel OCR processes (default 4)")
    ocr.add_argument("--upgrade-site-ocr", action="store_true", help="also re-OCR pages that only have the site's OCR text")
    sub.add_parser("reparse", help="re-parse saved HTML pages (no network) after parser changes")
    sub.add_parser("index", help="rebuild the full-text index")
    update = sub.add_parser("update", help="crawl + download + extract + index (no OCR)")
    update.add_argument("--limit", type=int)
    sub.add_parser("stats", help="print corpus statistics")
    return parser


def _run_update(conn: sqlite3.Connection, settings: Settings, limit: int | None) -> dict:
    from judicial_mcp import pipeline

    with PoliteClient(settings) as client:
        crawled = pipeline.crawl(conn, settings, client, limit=limit)
        downloaded = pipeline.download(conn, settings, client)
    extracted = pipeline.extract(conn, settings)
    store.rebuild_index(conn)
    return {"crawl": crawled, "download": downloaded, "extract": extracted}


def _ingest(args: argparse.Namespace) -> dict:
    from judicial_mcp import pipeline

    settings = load_settings()
    conn = connect(settings.db_path)
    try:
        if args.command == "crawl":
            with PoliteClient(settings) as client:
                return pipeline.crawl(conn, settings, client, limit=args.limit)
        if args.command == "download":
            with PoliteClient(settings) as client:
                return pipeline.download(conn, settings, client, limit=args.limit)
        if args.command == "extract":
            result = pipeline.extract(conn, settings, redo=args.redo)
            store.rebuild_index(conn)
            return result
        if args.command == "ocr":
            methods = (METHOD_PENDING, METHOD_SITE_OCR) if args.upgrade_site_ocr else (METHOD_PENDING,)
            report = lambda done, total: log.info("ocr %d/%d pages", done, total)  # noqa: E731
            return pipeline.ocr(conn, settings, methods=methods, limit_pages=args.limit_pages, workers=args.workers, progress=report)
        if args.command == "reparse":
            return pipeline.reparse(conn, settings)
        if args.command == "index":
            store.rebuild_index(conn)
            return {"indexed": True}
        if args.command == "update":
            return _run_update(conn, settings, args.limit)
        return corpus_stats(conn)
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,  # stdout is the MCP stdio channel
    )
    if args.command in (None, "serve"):
        from judicial_mcp.server import build_server

        server = build_server(load_settings().db_path)
        if getattr(args, "http", False):
            server.run("streamable-http", host=args.host, port=args.port)
        else:
            server.run()
        return
    result = _ingest(args)
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
