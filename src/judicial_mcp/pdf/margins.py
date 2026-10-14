"""Drop margin line numbers using the position of text on the page.

Court filings and justices' opinions print line numbers in a column beside the
body text (1..26 per page, or running numbers like 909, 910 across the whole
document). They sit entirely left (or right) of where the body text starts, so
a digits-only fragment outside the body's horizontal extent is a line number.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import TypeVar

T = TypeVar("T")

_DIGITS_ONLY_RE = re.compile(r"^\s*\d{1,4}\s*$")
_BODY_TEXT_RE = re.compile(r"[一-鿿]")
_TOLERANCE = 0.005  # fraction of page width


def drop_margin_numbers(
    items: Sequence[T],
    text_of: Callable[[T], str],
    x_range_of: Callable[[T], tuple[float, float]],
    page_width: float,
) -> list[T]:
    """Remove digits-only items lying fully outside the horizontal extent of the body text."""
    body = [x_range_of(i) for i in items if _BODY_TEXT_RE.search(text_of(i))]
    if not body:
        return list(items)
    left = min(x0 for x0, _ in body)
    right = max(x1 for _, x1 in body)
    tolerance = _TOLERANCE * page_width

    def is_margin_number(item: T) -> bool:
        if not _DIGITS_ONLY_RE.match(text_of(item)):
            return False
        x0, x1 = x_range_of(item)
        return x1 <= left + tolerance or x0 >= right - tolerance

    return [i for i in items if not is_margin_number(i)]
