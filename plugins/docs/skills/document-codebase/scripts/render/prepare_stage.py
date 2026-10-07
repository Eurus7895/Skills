#!/usr/bin/env python3
# GENERATED FILE -- DO NOT EDIT.
# Source: shared/scripts/render/prepare_stage.py
# Regenerate: python3 tools/materialize.py
"""Create an isolated render tree while preserving authored documentation."""

import argparse
import os
import shutil
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    source, out = os.path.realpath(args.source), os.path.realpath(args.out)
    if source == out or out.startswith(source + os.sep) or source.startswith(out + os.sep):
        sys.stderr.write("FAIL  source and staging directories must not contain each other\n")
        return 2
    if os.path.exists(args.out):
        shutil.rmtree(args.out)
    if os.path.isdir(args.source):
        shutil.copytree(args.source, args.out)
        print("staged existing documentation from %s" % args.source)
    else:
        os.makedirs(args.out)
        print("created empty documentation staging directory")
    return 0


if __name__ == "__main__":
    sys.exit(main())
