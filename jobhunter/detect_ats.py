"""Helper: work out which ATS a company's careers page uses.

    python -m jobhunter.detect_ats https://jobs.lever.co/acme

Prints the `ats` and `token` lines to paste into config/companies.yaml.
"""

from __future__ import annotations

import sys

from .sources.ats import FETCHERS, detect


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("Usage: python -m jobhunter.detect_ats <careers-url> [<careers-url> ...]")
        return 1

    for url in args:
        ats, token = detect(url)
        print(f"\n{url}")
        if ats and token:
            print("  Add this to config/companies.yaml:")
            print(f"    - name: {token}")
            print(f"      ats: {ats}")
            print(f"      token: {token}")
        else:
            print("  Not a recognized ATS careers page.")
            print(f"  Supported: {', '.join(sorted(FETCHERS))}")
            print("  Tip: open the company's 'Careers' page and check where the")
            print("       job links point — that host usually reveals the ATS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
