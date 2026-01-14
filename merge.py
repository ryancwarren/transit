#!/usr/bin/env python3
"""
Update kustomization.yaml - only modifies global /spec/values/tcp or nodePorts/tcp patches
Safely preserves all other patches (including targeted multi-op patches)
"""

import sys
from pathlib import Path
from typing import Dict, Any

from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString

yaml = YAML()
yaml.indent(mapping=2, sequence=4, offset=2)
yaml.width = 8192
yaml.preserve_quotes = True


# ── Configuration ───────────────────────────────────────────────────────────────

CONFIG = {
    "tcp": {
        "path": "/spec/values/tcp",
        "name": "global TCP host ports",
        "value_fmt": "{ns}/{svc}:{cp}"
    },
    "nodeport": {
        "path": "/spec/values/controller/service/nodePorts/tcp",
        "name": "global NodePorts tcp",
        "value_fmt": "{cp}"
    }
}


def is_target_patch(patch_item: Any, target_path: str) -> bool:
    """Check if this is a plain global add patch we want to manage"""
    if not isinstance(patch_item, dict) or 'patch' not in patch_item:
        return False
    
    # Must NOT have target: selector
    if 'target' in patch_item:
        return False
    
    content = str(patch_item['patch']).strip()
    
    # Should contain exactly our op + path
    if f'- op: add' not in content or f'path: {target_path}' not in content:
        return False
    
    # Avoid multi-op patches
    if content.count('- op:') > 1:
        return False
        
    return True


def find_managed_patch_index(patches: list, target_path: str) -> int:
    for i, item in enumerate(patches):
        if is_target_patch(item, target_path):
            return i
    return -1


def extract_port_mappings(patch_str: str) -> Dict[str, str]:
    """Robust parsing of port:target from literal block"""
    mappings = {}
    lines = patch_str.splitlines()
    capturing = False

    for line in lines:
        s = line.rstrip()
        if 'value: |' in s:
            capturing = True
            continue
            
        if capturing and ':' in s:
            content = s.lstrip()
            if not content or not content[0].isdigit():
                continue
                
            try:
                key_part, value_part = content.split(':', 1)
                key = key_part.strip()
                value = value_part.split('#')[0].strip()  # remove inline comment if any
                if key.isdigit():
                    mappings[key] = value
            except:
                pass
    return mappings


def build_new_patch_content(path: str, mappings: Dict[str, str]) -> LiteralScalarString:
    lines = [
        "- op: add",
        f"  path: {path}",
        "  value: |"
    ]
    for port in sorted(mappings.keys(), key=int):
        lines.append(f"    {port}: {mappings[port]}")
    if not mappings:
        lines.append("    {}")
    return LiteralScalarString("\n".join(lines))


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Safely update global TCP/NodePort patches in kustomization.yaml\n"
                    "(preserves all targeted / multi-op patches)",
        formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument("--file", default="kustomization.yaml",
                        help="Path to kustomization.yaml")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without modifying file")

    subparsers = parser.add_subparsers(dest="type", required=True,
                                       title="command", description="Choose patch type")

    # TCP
    p_tcp = subparsers.add_parser("tcp", help="Manage /spec/values/tcp")
    p_tcp.add_argument("host_port", type=int)
    p_tcp.add_argument("namespace")
    p_tcp.add_argument("service")
    p_tcp.add_argument("container_port", type=int)
    p_tcp.add_argument("--second", nargs=2, type=int, metavar=("PORT", "CONTAINER"),
                       help="Optional second mapping")

    # NodePort
    p_np = subparsers.add_parser("nodeport", help="Manage nodePorts/tcp")
    p_np.add_argument("node_port", type=int)
    p_np.add_argument("container_port", type=int)
    p_np.add_argument("--second", nargs=2, type=int, metavar=("PORT", "CONTAINER"),
                      help="Optional second mapping")

    args = parser.parse_args()

    cfg = CONFIG[args.type]

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"Error: File not found → {file_path}", file=sys.stderr)
        return 1

    data = yaml.load(file_path) or {}
    patches = data.setdefault('patches', [])

    idx = find_managed_patch_index(patches, cfg["path"])

    # Current mappings
    current = {}
    if idx >= 0:
        current = extract_port_mappings(str(patches[idx]['patch']))

    # New entries
    new = {}

    if args.type == "tcp":
        new[str(args.host_port)] = cfg["value_fmt"].format(
            ns=args.namespace, svc=args.service, cp=args.container_port)
        if args.second:
            p, c = args.second
            new[str(p)] = cfg["value_fmt"].format(ns=args.namespace, svc=args.service, cp=c)
    else:
        new[str(args.node_port)] = str(args.container_port)
        if args.second:
            p, c = args.second
            new[str(p)] = str(c)

    # Overlap check for nodeport
    if args.type == "nodeport":
        overlap = set(new.keys()) & set(current.keys())
        if overlap:
            print("Error: Refusing to overwrite existing nodePort(s):", file=sys.stderr)
            for k in sorted(overlap, key=int):
                print(f"  {k} already maps to {current[k]}", file=sys.stderr)
            return 2

    # Apply update (tcp = merge, nodeport = safe add after check)
    current.update(new)

    # Build new patch
    new_patch_text = build_new_patch_content(cfg["path"], current)
    new_entry = {'patch': new_patch_text}

    if idx >= 0:
        patches[idx] = new_entry
        action = "Updated"
    else:
        patches.append(new_entry)
        action = "Created new"

    print(f"{action} global {cfg['name']} patch")
    print(f"  Added/updated: {list(new.keys())}")

    if args.dry_run:
        print("\nPreview of the whole file (dry-run):")
        print("─"*80)
        yaml.dump(data, sys.stdout)
        print("─"*80)
    else:
        yaml.dump(data, file_path)
        print(f"File saved: {file_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
