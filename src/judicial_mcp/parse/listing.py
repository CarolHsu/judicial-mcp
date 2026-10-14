"""Parse the judgment listing page into detail-page ids."""

from __future__ import annotations

import re

from judicial_mcp.config import JUDGMENT_FID

_ID_RE = re.compile(rf"docdata\.aspx\?fid={JUDGMENT_FID}&(?:amp;)?id=(\d+)")


def parse_listing(html: str) -> tuple[int, ...]:
    """Return unique judgment ids in page order."""
    return tuple(dict.fromkeys(int(m) for m in _ID_RE.findall(html)))
