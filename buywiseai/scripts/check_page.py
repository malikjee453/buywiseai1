"""Diagnose why a product page yields no price.

  python scripts/check_page.py https://www.daraz.pk/products/...        # live fetch, polite + robots-aware
  python scripts/check_page.py --html saved_page.html [--domain daraz.pk]  # offline: test parsers on a saved page

Prints the outcome reason (ok / ok_daraz_json / robots / http_403 / no_price_in_page / ...) and which
parser matched, so you can see exactly where a platform fails. Does not bypass robots.txt or blocking.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from buywise.utils.meta_fetch import fetch_product_meta_ex, parse_daraz_embedded, parse_product_meta  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?")
    ap.add_argument("--html", help="path to a saved page to parse offline")
    ap.add_argument("--domain", default="", help="e.g. daraz.pk (enables the Daraz fallback in offline mode)")
    a = ap.parse_args()
    if a.html:
        html = Path(a.html).read_text(encoding="utf-8", errors="replace")
        print("json-ld / og meta :", parse_product_meta(html))
        if "daraz" in a.domain:
            print("daraz embedded    :", parse_daraz_embedded(html))
        return
    if not a.url:
        ap.error("give a URL or --html")
    meta, reason = fetch_product_meta_ex(a.url)
    print("reason:", reason, "| price:", meta)


if __name__ == "__main__":
    main()
