#!/usr/bin/env python3
"""Parse best hyperopt params per pair from the hyperopt run log.

Usage: python parse_hyperopt.py /path/to/hyperopt_run.log
Output: "BTC=56,56 ETH=50,50 ..." (ready for validate_hyperopt.py --best)
"""

import re
import sys


def parse(log_path: str) -> dict:
    with open(log_path) as f:
        text = f.read()
    # split into per-pair sections
    sections = re.split(r"=== (?:GUARDED )?HYPEROPT (\w+) start", text)
    result = {}
    # sections: [pre, SYM1, body1, SYM2, body2, ...]
    for i in range(1, len(sections) - 1, 2):
        sym, body = sections[i], sections[i + 1]
        m = re.search(r"Best result:\s*\n\s*\*[^\n]*\n(.*?)(?:\n\s*\n|# Buy parameters)", body, re.S)
        if not m:
            continue
        m_buy = re.search(r'"in_w":\s*(\d+)', body)
        m_sell = re.search(r'"out_w":\s*(\d+)', body)
        if m_buy and m_sell:
            result[sym] = (int(m_buy.group(1)), int(m_sell.group(1)))
    return result


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    res = parse(sys.argv[1])
    if not res:
        print("no Best result blocks found", file=sys.stderr)
        return 1
    print(" ".join(f"{s}={w[0]},{w[1]}" for s, w in sorted(res.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
