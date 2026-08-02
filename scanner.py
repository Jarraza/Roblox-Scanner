#!/usr/bin/env python3
"""Roblox price tracker

For every limited Rolimons has listed, read the current lowest resale price
from Roblox's public catalog endpoint and report it next to the Rolimons
value (falling back to RAP for items Rolimons hasn't assigned a value).

Pipeline (two reads):
    1. Rolimons itemdetails                 -> {asset_id: (name, rap, value)}
    2. catalog items/{id}/details           -> lowestResalePrice (per item)

Both endpoints key off the integer asset id, and the catalog details response
carries the resale floor inline, This tool only reads and reports public data.

Usage:
    python scanner.py                      # scan the whole catalogue once
    python scanner.py --limit 50           # first 50 items only
    python scanner.py --min-discount 20    # only show >=20% under reference
    python scanner.py --csv out.csv        # also write results to CSV
    python scanner.py --valued-only        # skip items Rolimons hasn't valued
    python scanner.py --loop               # re-scan continuously until Ctrl+C
    python scanner.py --loop --interval 30 # loop, waiting 30s between cycles
    python scanner.py --rolimons-refresh 0 # re-pull Rolimons values every cycle
    python scanner.py --loop --limit 50 --interval 30 --min-discount 15
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

ROLIMONS_URL = "https://api.rolimons.com/items/v1/itemdetails"
CATALOG_URL = "https://catalog.roblox.com/v1/catalog/items/{id}/details?itemType=asset"

_UA = "roblox-scanner/1.0 (+https://github.com/Jarraza/Roblox-Scanner)"

# Rolimons itemdetails positional layout: [name, acronym, rap, value, ...]
_NAME_IDX = 0
_RAP_IDX = 2
_VALUE_IDX = 3



# HTTP 

def _get_json(url: str, *, timeout: float) -> dict:
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", _UA)
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))



# Rolimons itemdetails fetch

def fetch_rolimons(*, timeout: float, valued_only: bool) -> dict[int, tuple[str, int, int]]:
    """Return limiteds as {asset_id: (name, rap, value)}.

    Every entry in Rolimons' itemdetails is a limited, so this is the full
    catalogue (~2.5k). `value` is -1 when Rolimons hasn't assigned one;
    `valued_only` drops those, otherwise they're kept (RAP is used as the
    comparison reference downstream).
    """
    data = _get_json(ROLIMONS_URL, timeout=timeout)
    if not data.get("success", False):
        raise RuntimeError("rolimons itemdetails returned success=false")

    out: dict[int, tuple[str, int, int]] = {}
    for raw_id, arr in data.get("items", {}).items():
        try:
            asset_id = int(raw_id)
            name = str(arr[_NAME_IDX])
            rap = int(arr[_RAP_IDX])
            value = int(arr[_VALUE_IDX])
        except (ValueError, IndexError, TypeError):
            continue
        if valued_only and value <= 0:
            continue
        if rap <= 0 and value <= 0:  # nothing to compare against
            continue
        out[asset_id] = (name, rap, value)
    return out



# catalog resale fetch

def lowest_resale(asset_id: int, *, timeout: float) -> int | None:
    """Lowest current resale price for one item, or None if none listed.

    Prefers `lowestResalePrice` (the reseller floor for off-sale limiteds);
    falls back to `lowestPrice` when resale isn't populated.
    """
    data = _get_json(CATALOG_URL.format(id=asset_id), timeout=timeout)
    for field in ("lowestResalePrice", "lowestPrice"):
        price = data.get(field)
        if isinstance(price, (int, float)) and price > 0:
            return int(price)
    return None



# Data model

@dataclass(slots=True)
class Row:
    asset_id: int
    name: str
    rap: int
    value: int
    lowest: int | None

    @property
    def reference(self) -> tuple[int, str] | None:
        """(reference_price, source) — Rolimons value if set, else RAP."""
        if self.value > 0:
            return self.value, "value"
        if self.rap > 0:
            return self.rap, "rap"
        return None

    @property
    def discount(self) -> float | None:
        ref = self.reference
        if not self.lowest or ref is None:
            return None
        return 1.0 - self.lowest / ref[0]


def scan(
    items: dict[int, tuple[str, int, int]],
    *,
    timeout: float,
    delay: float,
    limit: int | None,
) -> list[Row]:
    rows: list[Row] = []
    entries = list(items.items())
    if limit:
        entries = entries[:limit]

    total = len(entries)
    for i, (asset_id, (name, rap, value)) in enumerate(entries, 1):
        try:
            low = lowest_resale(asset_id, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code == 429:  # rate limited — back off and retry once
                time.sleep(5.0)
                try:
                    low = lowest_resale(asset_id, timeout=timeout)
                except (urllib.error.HTTPError, urllib.error.URLError, ValueError, OSError):
                    low = None
            else:
                low = None  # 400/403/404 etc — skip this item
        except (urllib.error.URLError, ValueError, OSError):
            low = None

        rows.append(Row(asset_id, name, rap, value, low))
        print(f"\r  {i}/{total} scanned", end="", file=sys.stderr, flush=True)
        time.sleep(delay)

    print(file=sys.stderr)
    return rows



# Output  

def print_table(rows: list[Row], min_discount: float) -> None:
    listed = [r for r in rows if r.lowest is not None and r.discount is not None]
    listed.sort(key=lambda r: -(r.discount or 0))

    hdr = f"{'ASSET ID':>10}  {'ITEM':<30} {'RAP':>8} {'VALUE':>8} {'LOWEST':>8} {'DISC':>7}"
    print("\n" + hdr)
    print("-" * len(hdr))
    for r in listed:
        d = r.discount
        if d is None or d * 100 < min_discount:
            continue
        ref = r.reference
        src = ref[1] if ref else ""
        name = r.name[:29] if len(r.name) > 29 else r.name
        value_cell = str(r.value) if r.value > 0 else "-"
        disc = f"{d * 100:>5.1f}%" + ("~" if src == "rap" else " ")
        print(f"{r.asset_id:>10}  {name:<30} {r.rap:>8} {value_cell:>8} {r.lowest:>8} {disc:>7}")

    unlisted = sum(1 for r in rows if r.lowest is None)
    print(f"\n{len(listed)} listed, {unlisted} unlisted, {len(rows)} scanned total.")
    if any(r.reference and r.reference[1] == "rap" for r in listed):
        print("(~ = discount measured against RAP; item has no Rolimons value)")


def write_csv(rows: list[Row], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            ["asset_id", "name", "rap", "rolimons_value", "lowest_resale", "reference", "discount_pct"]
        )
        for r in rows:
            ref = r.reference
            disc = f"{r.discount * 100:.1f}" if r.discount is not None else ""
            w.writerow(
                [
                    r.asset_id,
                    r.name,
                    r.rap,
                    r.value if r.value > 0 else "",
                    r.lowest or "",
                    ref[1] if ref else "",
                    disc,
                ]
            )



# Entrypoint and argparse

def main() -> None:
    ap = argparse.ArgumentParser(description="Read-only Rolimons vs lowest-resale tracker")
    ap.add_argument("--limit", type=int, default=None, help="scan only the first N items")
    ap.add_argument("--delay", type=float, default=0.3, help="seconds between catalog calls")
    ap.add_argument("--timeout", type=float, default=15.0, help="per-request timeout")
    ap.add_argument("--min-discount", type=float, default=0.0, help="only show >= this %% under reference")
    ap.add_argument("--valued-only", action="store_true", help="skip items with no Rolimons value")
    ap.add_argument("--csv", metavar="PATH", help="also write full results to CSV")
    ap.add_argument("--loop", action="store_true", help="re-scan continuously instead of exiting once")
    ap.add_argument("--interval", type=float, default=60.0, help="seconds to wait between loop cycles")
    ap.add_argument("--rolimons-refresh", type=float, default=300.0, help="seconds between Rolimons value refreshes while looping")
    args = ap.parse_args()

    def load_items() -> dict[int, tuple[str, int, int]]:
        print("fetching Rolimons catalogue...", file=sys.stderr)
        items = fetch_rolimons(timeout=args.timeout, valued_only=args.valued_only)
        print(f"  {len(items)} limiteds to scan", file=sys.stderr)
        return items

    items = load_items()
    last_refresh = time.monotonic()
    cycle = 0

    try:
        while True:
            cycle += 1
            if args.loop:
                # refresh Rolimons values periodically
                if time.monotonic() - last_refresh >= args.rolimons_refresh:
                    items = load_items()
                    last_refresh = time.monotonic()
                print(f"\n=== cycle {cycle} · {time.strftime('%H:%M:%S')} ===", file=sys.stderr)

            rows = scan(items, timeout=args.timeout, delay=args.delay, limit=args.limit)
            print_table(rows, args.min_discount)
            if args.csv:
                write_csv(rows, args.csv)
                print(f"wrote {args.csv}", file=sys.stderr)

            if not args.loop:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nstopped.", file=sys.stderr)


if __name__ == "__main__":
    main()