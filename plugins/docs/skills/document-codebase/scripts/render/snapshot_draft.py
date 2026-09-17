#!/usr/bin/env python3
# GENERATED FILE -- DO NOT EDIT.
# Source: shared/scripts/render/snapshot_draft.py
# Regenerate: python3 tools/materialize.py
"""Bind a rendered tree to the document model that generated it."""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from draft_artifact import file_hash, tree_hash  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--draft", required=True)
    parser.add_argument("--doc", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    if not os.path.isdir(args.draft) or not os.path.isfile(args.doc):
        sys.stderr.write("FAIL  rendered draft or document model is missing\n")
        return 2
    manifest = {"render_manifest_version": 1, "draft_hash": tree_hash(args.draft),
                "doc_hash": file_hash(args.doc)}
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print("recorded rendered draft: %s" % manifest["draft_hash"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
