import json

from judicial_mcp import cli


def test_stats_and_index_commands(built_db, monkeypatch, capsys):
    monkeypatch.setenv("JUDICIAL_MCP_DATA", str(built_db.data_dir))
    cli.main(["stats"])
    stats = json.loads(capsys.readouterr().out)
    assert stats["judgments"] == 1

    cli.main(["index"])
    assert json.loads(capsys.readouterr().out) == {"indexed": True}


def test_extract_command_is_idempotent(built_db, monkeypatch, capsys):
    monkeypatch.setenv("JUDICIAL_MCP_DATA", str(built_db.data_dir))
    cli.main(["extract"])
    result = json.loads(capsys.readouterr().out)
    assert result["extracted"] == 0  # everything already extracted


def test_ocr_command_with_nothing_pending(built_db, monkeypatch, capsys):
    monkeypatch.setenv("JUDICIAL_MCP_DATA", str(built_db.data_dir))
    monkeypatch.setattr("judicial_mcp.pdf.ocr.ocr_pages", lambda path, pages: ())
    monkeypatch.setattr("judicial_mcp.pdf.ocr.ocr_available", lambda: True)
    cli.main(["ocr"])
    assert json.loads(capsys.readouterr().out)["total_candidates"] == 0
