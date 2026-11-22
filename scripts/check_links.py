#!/usr/bin/env python3
"""Markdown Relative Link Checker.

Verifies that all relative file links and markdown targets in documentation files
(default: README.md) resolve to existing files on disk.
Fails with exit code 1 if any broken relative link is encountered.
"""

import os
import re
import sys
from pathlib import Path
from typing import List, Tuple

# Matches markdown links [text](target), excluding images ![]() if needed or including them
LINK_PATTERN = re.compile(r'(?<!\!)\[([^\]]+)\]\(([^)]+)\)')


def check_markdown_links(file_path: str) -> List[Tuple[int, str, str, str]]:
    """Scan a markdown file for broken relative links.

    Returns a list of tuples: (line_no, link_text, link_target, error_reason)
    """
    path = Path(file_path)
    if not path.exists():
        return [(0, "", file_path, "Source file does not exist")]

    base_dir = path.parent
    broken_links = []

    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Collect headings for anchor verification if in the same file
    headings = set()
    for line in lines:
        match = re.match(r'^(#{1,6})\s+(.+)$', line.strip())
        if match:
            # Slugify heading
            h_text = match.group(2).strip()
            # GitHub slugify: lowercase, remove punctuation, spaces to hyphens
            slug = re.sub(r'[^\w\s-]', '', h_text.lower()).strip()
            slug = re.sub(r'[-\s]+', '-', slug)
            headings.add(slug)

    for line_idx, line in enumerate(lines, start=1):
        for match in LINK_PATTERN.finditer(line):
            text, target = match.group(1), match.group(2).strip()

            # Ignore web URLs, mailto, etc.
            if target.startswith(("http://", "https://", "mailto:", "ftp://")):
                continue

            # Flag hardcoded absolute file:// URLs as improper in portable repo docs
            if target.startswith("file://"):
                file_url_path = target.replace("file://", "")
                # Strip anchor
                if "#" in file_url_path:
                    file_url_path = file_url_path.split("#", 1)[0]
                if not os.path.exists(file_url_path):
                    broken_links.append((line_idx, text, target, f"Absolute file URL does not exist: {file_url_path}"))
                else:
                    broken_links.append((line_idx, text, target, "Absolute file:// path should be converted to relative path"))
                continue

            # Separate target and anchor
            target_path = target
            anchor = ""
            if "#" in target:
                target_path, anchor = target.split("#", 1)

            # Internal page anchor
            if not target_path and anchor:
                if anchor not in headings:
                    broken_links.append((line_idx, text, target, f"Heading anchor '#{anchor}' not found in document"))
                continue

            # Relative file path
            resolved_path = (base_dir / target_path).resolve()
            if not resolved_path.exists():
                broken_links.append((line_idx, text, target, f"Target file does not exist: {target_path} (resolved: {resolved_path})"))

    return broken_links


def main():
    target_files = sys.argv[1:] if len(sys.argv) > 1 else ["README.md"]
    total_broken = 0

    print(f"[*] Running link checker across: {target_files}")
    for f in target_files:
        print(f"[*] Checking {f}...")
        broken = check_markdown_links(f)
        if broken:
            print(f"[!] Found {len(broken)} broken or invalid link(s) in {f}:")
            for line_no, text, target, reason in broken:
                print(f"    Line {line_no}: [{text}]({target}) -> {reason}")
            total_broken += len(broken)
        else:
            print(f"[✔] All links in {f} are valid.")

    if total_broken > 0:
        print(f"\n[FAILED] Total broken links: {total_broken}")
        sys.exit(1)
    else:
        print("\n[PASSED] All relative links verified successfully.")
        sys.exit(0)


if __name__ == "__main__":
    main()
