#!/usr/bin/env python3
"""
Update kustomization.yaml port patches with ruamel.yaml
- tcp:      merge / append / update existing mappings
- nodeport: strict - reject if any requested nodePort already exists
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString

yaml = YAML()
yaml.indent(mapping=2, sequence=4, offset=2)
yaml.width = 8192
yaml.preserve_quotes = True


# ── Configuration ───────────────────────────────────────────────────────────────

PATCH_CONFIG = {
    "tcp": {
        "path": "/spec/values/tcp",
        "name": "TCP host port mapping",
        "merge_behavior": "merge_update",  # append + update if exists
        "key_arg_name": "host_port",
        "value_args": ["namespace", "service", "container_port"],
        "value_pattern": "{namespace}/{service}:{container_port}",
        "second_flags": ["--second-host", "--second-container"],
    },
    "nodeport": {
        "path": "/spec/values/controller/service/nodePorts/tcp",
        "name": "NodePort",
        "merge_behavior": "exclusive",     # reject if any overlap
        "key_arg_name": "node_port",
        "value_args": ["container_port"],
        "value_pattern": "{container_port}",
        "second_flags": ["--second-node", "--second-container"],
    }
}


def find_patch_index(patches: List[dict], target_path: str) -> int:
    for i, patch_entry in enumerate(patches):
        if not isinstance(patch_entry, dict) or 'patch' not in patch_entry:
            continue
        content = str(patch_entry['patch'])
        if f'path: {target_path}' in content and '- op: add' in content:
            return i
    return -1


def extract_current_mappings(patch_text: str) -> Dict[str, str]:
    mappings = {}
    lines = patch_text.splitlines()
    capturing = False

    for line in lines:
        s = line.rstrip()
        if s.strip() == 'value: |':
            capturing = True
            continue
        if capturing and ':' in s and s.lstrip().startswith(('0','1','2','3','4','5','6','7','8','9')):
            content = s.lstrip()
            try:
                key_part, value_part = content.split(':', 1)
                key = key_part.strip()
                value = value_part.strip()
                if key.isdigit():
                    mappings[key] = value
            except ValueError:
                continue
    return mappings


def build_patch_literal(path: str, mappings: Dict[str, str]) -> LiteralScalarString:
    lines = [
        "- op: add",
        f"  path: {path}",
        "  value: |"
    ]

    for port in sorted(mappings.keys(), key=int):
        lines.append(f"    {port}: {mappings[port]}")

    if not mappings:
        lines.append("    {}  # will be replaced")

    return LiteralScalarString("\n".join(lines))


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Add/update port patches in kustomization.yaml",
        formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument("type", choices=list(PATCH_CONFIG.keys()),
                        help="patch type to modify")

    parser.add_argument("main_port", type=int,
                        help="primary port number")

    parser.add_argument("--file", default="kustomization.yaml",
                        help="target kustomization.yaml file")

    parser.add_argument("--dry-run", action="store_true",
                        help="show result without writing")

    parser.add_argument("--second", nargs=2, type=int, metavar=("PORT", "TARGET_PORT"),
                        help="optional second mapping (port targetPort)")

    args, unknown = parser.parse_known_args()

    cfg = PATCH_CONFIG[args.type]

    # Add required positional arguments according to patch type
    for arg_name in cfg["value_args"]:
        if arg_name == "container_port":
            parser.add_argument(arg_name, type=int, required=True)
        else:
            parser.add_argument(arg_name, required=True)

    # Re-parse with full arguments
    args = parser.parse_args()

    value_args_values = [getattr(args, name) for name in cfg["value_args"]]

    file_path = Path(args.file)
    if not file_path.is_file():
        print(f"Error: File not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    data = yaml.load(file_path) or {}

    # Prepare new mappings
    new_mappings = {}
    main_key = str(args.main_port)

    if args.type == "tcp":
        ns, svc, cp = value_args_values
        new_mappings[main_key] = f"{ns}/{svc}:{cp}"
    else:
        cp = value_args_values[0]
        new_mappings[main_key] = str(cp)

    if args.second:
        sec_port, sec_target = args.second
        sec_key = str(sec_port)
        if args.type == "tcp":
            new_mappings[sec_key] = f"{ns}/{svc}:{sec_target}"
        else:
            new_mappings[sec_key] = str(sec_target)

    # Find existing patch
    patches = data.setdefault('patches', [])
    patch_idx = find_patch_index(patches, cfg["path"])

    current = {}
    if patch_idx >= 0:
        current = extract_current_mappings(str(patches[patch_idx]['patch']))

    # Apply merge strategy
    if cfg["merge_behavior"] == "exclusive":
        overlap = set(new_mappings.keys()) & set(current.keys())
        if overlap:
            print("Error: Cannot add nodePort(s) - the following already exist:", file=sys.stderr)
            for p in sorted(overlap, key=int):
                print(f"  • {p} → {current[p]}", file=sys.stderr)
            sys.exit(2)

    # For tcp → merge (append + update)
    current.update(new_mappings)

    # Build new patch
    new_literal = build_patch_literal(cfg["path"], current)

    new_patch_entry = {'patch': new_literal}

    if patch_idx >= 0:
        patches[patch_idx] = new_patch_entry
        action = "Updated (merged)"
    else:
        patches.append(new_patch_entry)
        action = "Created"

    print(f"{action} {cfg['name']} patch")
    print(f"  Added/updated port(s): {args.main_port}", end="")
    if args.second:
        print(f" + {args.second[0]}", end="")
    print()

    if args.dry_run:
        print("\nResult (dry-run):")
        print("─" * 70)
        yaml.dump(data, sys.stdout)
        print("─" * 70)
    else:
        try:
            yaml.dump(data, file_path)
            print(f"File updated successfully: {file_path}")
        except Exception as e:
            print(f"Failed to write file: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
