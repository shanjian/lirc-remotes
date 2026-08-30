#!/usr/bin/env python3
"""Convert this repo's lirc2xml files into irplus (Android) XML.

The XML here is a lirc2xml dump: <lircremotes><remote><code><ccf>.
irplus wants:      <irplus><device><button>.

Every <code> carries a Pronto hex payload in its <ccf> child, which maps
directly onto irplus's PRONTO_HEX format, so no timing math is needed.

Usage:
    ./to_irplus.py sony/RM-470.xml            # -> sony/RM-470.irplus.xml
    ./to_irplus.py sony                       # one vendor, in place
    ./to_irplus.py .                          # everything, in place
    ./to_irplus.py . -o irplus                # everything, into a separate tree
"""

import argparse
import os
import re
import sys
import glob
import xml.etree.ElementTree as ET
from xml.sax.saxutils import quoteattr, escape

# lirc2xml produced files that are not valid XML: bare & in attributes, raw
# <, > and " inside name="..." values, and stray control bytes. Repair all
# three before parsing, since no XML parser (irplus's included) accepts them.
SUFFIX = ".irplus.xml"

BROKEN_ATTR = [
    re.compile(r'(<code name=")(.*)(" codeno="[^"]*"\s*/?>)'),
    re.compile(r'(<remote name=")(.*)("\s*>)'),
]

# An & that does not already begin a character or entity reference.
BARE_AMP = re.compile(r'&(?!(?:amp|lt|gt|quot|apos|#[0-9]+|#x[0-9a-fA-F]+);)')

# Characters XML 1.0 forbids outright, control bytes other than tab/CR/LF.
ILLEGAL_CHARS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


def repair(text):
    """Make a malformed lirc2xml document parseable."""
    text = ILLEGAL_CHARS.sub("", text)
    # Do & first so the escapes introduced below are not double-escaped.
    text = BARE_AMP.sub("&amp;", text)

    def fix(m):
        value = m.group(2)
        for char, entity in (("<", "&lt;"), (">", "&gt;"), ('"', "&quot;")):
            value = value.replace(char, entity)
        return m.group(1) + value + m.group(3)

    for pattern in BROKEN_ATTR:
        text = pattern.sub(fix, text)
    return text


def label_for(name):
    """KEY_VOLUMEUP -> VOLUMEUP; leave anything else alone."""
    return name[4:] if name.startswith("KEY_") and len(name) > 4 else name


def devices_in(path):
    """Yield (model, [(label, pronto), ...]) for each remote in one file."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        root = ET.fromstring(repair(fh.read()))

    stem = os.path.splitext(os.path.basename(path))[0]
    remotes = root.findall("remote")
    for index, remote in enumerate(remotes):
        buttons = []
        seen = set()
        for code in remote.findall("code"):
            ccf = code.find("ccf")
            if ccf is None or not (ccf.text or "").strip():
                continue
            pronto = " ".join(ccf.text.split()).upper()
            label = label_for(code.get("name", ""))
            if not label or label in seen:
                # irplus keys its grid by label; duplicates collide.
                continue
            seen.add(label)
            buttons.append((label, pronto))
        if not buttons:
            continue
        # Prefer the file name as the model, since that is what the repo is
        # organised by; disambiguate when a file holds several remotes.
        model = stem if len(remotes) == 1 else "%s %s" % (stem, remote.get("name", index))
        yield model, buttons


def render(manufacturer, devices, columns):
    out = ["<?xml version=\"1.0\" encoding=\"UTF-8\"?>", "<irplus>"]
    for model, buttons in devices:
        out.append(
            '  <device manufacturer=%s model=%s columns="%d" format="PRONTO_HEX">'
            % (quoteattr(manufacturer), quoteattr(model), columns)
        )
        for label, pronto in buttons:
            out.append("    <button label=%s>%s</button>" % (quoteattr(label), escape(pronto)))
        out.append("  </device>")
    out.append("</irplus>")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Convert lirc2xml files to irplus XML.")
    ap.add_argument("path", help="an .xml file, a vendor directory, or . for the whole repo")
    ap.add_argument("-o", "--output", help="output file (single input) or directory tree "
                                           "(default: beside each source file)")
    ap.add_argument("-c", "--columns", type=int, default=4, help="buttons per row in irplus (default: 4)")
    args = ap.parse_args()

    if os.path.isdir(args.path):
        sources = sorted(
            p for p in glob.glob(os.path.join(args.path, "**", "*.xml"), recursive=True)
            # Never re-convert our own output.
            if not p.endswith(SUFFIX)
        )
        single = None
    else:
        sources = [args.path]
        single = args.output if args.output and not os.path.isdir(args.output) else None
    out_dir = args.output if args.output and not single else None

    converted = failed = skipped = 0
    for source in sources:
        manufacturer = os.path.basename(os.path.dirname(os.path.abspath(source)))
        try:
            devices = list(devices_in(source))
        except Exception as exc:
            print("FAIL %s: %s" % (source, exc), file=sys.stderr)
            failed += 1
            continue
        if not devices:
            skipped += 1
            continue

        stem = os.path.splitext(os.path.basename(source))[0] + SUFFIX
        if single:
            target = single
        elif out_dir:
            target = os.path.join(out_dir, manufacturer, stem)
        else:
            # Alongside the source, e.g. sony/RM-470.xml -> sony/RM-470.irplus.xml
            target = os.path.join(os.path.dirname(source), stem)
        os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(render(manufacturer, devices, args.columns))
        converted += 1

    print("converted %d, skipped %d (no usable codes), failed %d"
          % (converted, skipped, failed), file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
