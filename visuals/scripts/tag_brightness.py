#!/usr/bin/env python3
"""Tag shots as 'light' or 'dark' based on average brightness.

Reads brightness values from the shot catalog, computes the global mean,
and tags each shot above/below that threshold. Results are written back
to the catalog as a 'brightness_tag' field.

Usage:
  python visuals/scripts/tag_brightness.py
  python visuals/scripts/tag_brightness.py --catalog path/to/shot_catalog.json
  python visuals/scripts/tag_brightness.py --dry-run
"""

import argparse, json
from pathlib import Path

DEFAULT_CATALOG = (
    Path(__file__).parent.parent.parent
    / "projects/funeral_parade_of_roses/data/shot_catalog.json"
)


def main():
    ap = argparse.ArgumentParser(description="Tag shots as light or dark")
    ap.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    ap.add_argument("--dry-run", action="store_true", help="Print tags without saving")
    args = ap.parse_args()

    catalog_path = Path(args.catalog)
    catalog = json.loads(catalog_path.read_text())

    brightness_values = [v["brightness"] for v in catalog.values()]
    mean_brightness = sum(brightness_values) / len(brightness_values)

    light_count = 0
    dark_count = 0

    for key, shot in catalog.items():
        if shot["brightness"] >= mean_brightness:
            shot["brightness_tag"] = "light"
            light_count += 1
        else:
            shot["brightness_tag"] = "dark"
            dark_count += 1

    print(f"Mean brightness: {mean_brightness:.4f}")
    print(f"Light: {light_count}  Dark: {dark_count}")

    if args.dry_run:
        print("(dry run — not saved)")
        return

    catalog_path.write_text(json.dumps(catalog, indent=2))
    print(f"Saved to {catalog_path}")


if __name__ == "__main__":
    main()
