#!/usr/bin/env python3
import sys
from urllib.parse import urlparse

def is_valid_hostname(hostname: str) -> bool:
    """
    Validate a hostname according to RFC 1123 using urllib.parse.
    - Labels: 1-63 chars, letters (a-z, A-Z), digits (0-9), hyphens (-).
    - Labels must not start/end with hyphens.
    - Total length <= 255 chars.
    - No consecutive dots, no leading/trailing dots.
    """
    # Check total length (max 255 chars)
    if len(hostname) > 255:
        return False

    # Remove trailing dot if present (e.g., FQDNs in DNS)
    hostname = hostname.rstrip('.')

    # Check for empty hostname or invalid structure
    if not hostname or hostname.startswith('.') or '..' in hostname:
        return False

    # Use urllib.parse to extract hostname (add scheme to make it a URL)
    # This helps normalize and split the hostname
    try:
        parsed = urlparse(f'http://{hostname}')
        if not parsed.hostname:
            return False
        hostname = parsed.hostname.lower()  # Normalize to lowercase (RFC 1123 is case-insensitive)
    except ValueError:
        return False

    # Split into labels
    labels = hostname.split('.')

    # Validate each label
    for label in labels:
        # Check label length (1-63 chars)
        if len(label) < 1 or len(label) > 63:
            return False

        # Check allowed characters (letters, digits, hyphens)
        for char in label:
            if not (char.isalnum() or char == '-'):
                return False

        # Check that label does not start or end with hyphen
        if label.startswith('-') or label.endswith('-'):
            return False

    # Ensure at least one label (non-empty hostname)
    return len(labels) > 0

def main():
    if len(sys.argv) != 2:
        print("Usage: python validate_hostname_urllib.py <hostname>")
        sys.exit(1)

    hostname = sys.argv[1]
    if is_valid_hostname(hostname):
        print(f"Hostname '{hostname}' is valid.")
    else:
        print(f"Hostname '{hostname}' is invalid.")

if __name__ == "__main__":
    main()
