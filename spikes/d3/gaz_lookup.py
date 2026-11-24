"""Temporary: print the Gazetteer rows that could stand for the towns the build could not place."""
import sys
from pathlib import Path

ASK = {
    "PA": ["Gwynedd", "Whiteland", "Immaculata", "Grantham", "Upper Allen", "Center Valley", "Upper Saucon", "La Plume", "Factoryville", "Benton"],
    "NJ": ["Convent", "Morris", "Union"],
    "WI": ["Waukesha", "Superior"],
    "MA": ["Franklin", "Amherst"],
    "KY": ["Lexington"],
    "NY": ["Annandale", "Red Hook", "Purchase", "Harrison"],
    "MD": ["Lexington Park", "California", "Great Mills"],
    "VA": ["Sweet Briar", "Amherst"],
    "GA": ["Berry", "Rome"],
}
for path in sys.argv[1:]:
    print("==", Path(path).name)
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        cells = line.split("\t")
        if len(cells) < 4 or cells[0] not in ASK:
            continue
        if any(word.lower() in cells[3].lower() for word in ASK[cells[0]]):
            print("\t".join(c.strip() for c in cells[:4] + cells[-2:]))
