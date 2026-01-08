#!/usr/bin/env python3
import yaml
import sys
import argparse
from pathlib import Path

def find_next_index(current_ports):
    """
    Determine the next available index based on existing ports.
    Ports are in 331xx and 349xx ranges → index = xx part.
    """
    used_indexes = set()
    for port in current_ports:
        if port.startswith('331') or port.startswith('349'):
            try:
                index = int(port[3:])  # e.g., '33105' → 5, '34912' → 12
                used_indexes.add(index)
            except ValueError:
                continue
    if not used_indexes:
        return 1
    return max(used_indexes) + 1

def update_tcp_ports_in_patch(data, namespace):
    """
    Automatically find the next index and add ports for the given namespace.
    Adds:
      3310N: {namespace}/dremio-client:31010
      3490N: {namespace}/dremio-client:32010
    where N is the next available index.
    """
    # Collect existing ports
    current_ports = set()
    patch_found = False

    if 'patches' in data:
        for patch_item in data['patches']:
            if isinstance(patch_item, dict) and 'patch' in patch_item:
                patch_content = patch_item['patch'].strip()
                if patch_content.startswith('- op: add') and 'path: /spec/values/tcp' in patch_content:
                    patch_found = True
                    lines = [line.rstrip() for line in patch_content.splitlines()]
                    value_start = False
                    for line in lines:
                        if line.strip().startswith('value:'):
                            value_start = True
                            continue
                        if value_start and ':' in line and not line.startswith('-'):
                            key = line.split(':', 1)[0].strip()
                            if key.isdigit():
                                current_ports.add(key)

    next_index = find_next_index(current_ports)
    print(f"Determined next available index: {next_index}")

    host_port_1 = 33100 + next_index
    host_port_2 = 34900 + next_index
    target_1 = f"{namespace}/dremio-client:31010"
    target_2 = f"{namespace}/dremio-client:32010"

    new_entries = {
        str(host_port_1): target_1,
        str(host_port_2): target_2,
    }

    if patch_found:
        # Update existing patch
        for patch_item in data['patches']:
            if isinstance(patch_item, dict) and 'patch' in patch_item:
                patch_content = patch_item['patch'].strip()
                if patch_content.startswith('- op: add') and 'path: /spec/values/tcp' in patch_content:
                    current_value = {}
                    lines = [line.rstrip() for line in patch_content.splitlines()]
                    value_start = False
                    for line in lines:
                        if line.strip().startswith('value:'):
                            value_start = True
                            continue
                        if value_start and ':' in line and not line.startswith('-'):
                            key_part = line.split(':', 1)
                            if len(key_part) == 2:
                                key = key_part[0].strip()
                                val = key_part[1].strip()
                                if key.isdigit():
                                    current_value[key] = val

                    current_value.update(new_entries)

                    # Rebuild sorted value block
                    new_value_lines = ['  value:']
                    for port in sorted(current_value.keys(), key=int):
                        new_value_lines.append(f"    {port}: {current_value[port]}")

                    new_patch_lines = [
                        '- op: add',
                        '  path: /spec/values/tcp',
                    ] + new_value_lines

                    patch_item['patch'] = '\n'.join(new_patch_lines) + '\n'
                    print(f"Updated existing tcp patch with ports {host_port_1} and {host_port_2} for namespace '{namespace}'")
                    break
    else:
        # Create new patch
        new_patch = {
            'patch': f"""- op: add
  path: /spec/values/tcp
  value:
    {host_port_1}: {target_1}
    {host_port_2}: {target_2}
"""
        }
        if 'patches' not in data:
            data['patches'] = []
        data['patches'].append(new_patch)
        print(f"Created new tcp patch for namespace '{namespace}' with ports {host_port_1} and {host_port_2}")

    return data

def main():
    parser = argparse.ArgumentParser(
        description="Automatically update kustomization.yaml with next available TCP ports for a namespace"
    )
    parser.add_argument(
        "namespace",
        help="Exact namespace name to use (e.g., dremio-prod-3, dremio-cluster-b)"
    )
    parser.add_argument(
        "--file",
        default="kustomization.yaml",
        help="Path to kustomization.yaml (default: kustomization.yaml)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show changes without writing to file"
    )

    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"Error: {file_path} not found", file=sys.stderr)
        sys.exit(1)

    with open(file_path, 'r') as f:
        data = yaml.safe_load(f) or {}

    updated_data = update_tcp_ports_in_patch(data, args.namespace)

    if args.dry_run:
        print("\n--- Dry Run: Updated kustomization.yaml ---")
        yaml.dump(updated_data, sys.stdout, sort_keys=False, indent=2)
    else:
        with open(file_path, 'w') as f:
            yaml.dump(updated_data, f, sort_keys=False, indent=2)
        print(f"Successfully updated {file_path}")

if __name__ == "__main__":
    main()
