# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "gpsoauth>=1.1.0",
#     "cryptography>=43.0",
# ]
# ///
"""One-time authentication helper for Google Find Hub.

This script opens Chrome and walks you through Google login.
After completion, Auth/secrets.json is created with the session tokens
needed for headless operation.

Usage:
    uv run scripts/authenticate.py
"""

import shutil
import sys
from pathlib import Path

# Ensure the project root is on sys.path for GoogleFindMyTools
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))


def main() -> None:
    """Run the Google authentication flow."""
    print("=" * 60)
    print("Google Find Hub — One-Time Authentication")
    print("=" * 60)
    print()

    # Check Chrome is installed
    chrome = shutil.which("google-chrome") or shutil.which("chrome") or shutil.which("chromium")
    if not chrome:
        # Also check common Windows paths
        common_paths = [
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        ]
        for p in common_paths:
            if p.exists():
                chrome = str(p)
                break

    if chrome:
        print(f"Chrome found: {chrome}")
    else:
        print("WARNING: Chrome not found in PATH. The auth flow may fail.")
        print("Install Google Chrome or ensure it's in your PATH.")
    print()

    try:
        from Auth.auth_flow import request_oauth_account_token_flow
    except ImportError:
        print(
            "ERROR: GoogleFindMyTools is not available.\n"
            "Clone https://github.com/leonboe1/GoogleFindMyTools\n"
            "and add its directory to PYTHONPATH."
        )
        sys.exit(1)

    print("Opening Chrome for Google login...")
    print()

    try:
        request_oauth_account_token_flow()
    except Exception as e:
        print(f"\nAuthentication failed: {e}")
        sys.exit(1)

    # Verify secrets were created
    secrets_path = project_root / "Auth" / "secrets.json"
    if secrets_path.exists():
        print()
        print("Authentication successful!")
        print(f"Session tokens saved to {secrets_path}")
        print()
        print("Next steps:")
        print("  1. Copy .env.example to .env and configure Discord webhooks")
        print("  2. Start the tracker: find-hub-tracker start")
    else:
        print()
        print("WARNING: Auth/secrets.json was not created.")
        print("The authentication flow may not have completed successfully.")
        sys.exit(1)

    # Try listing devices
    print()
    print("Attempting to list discovered devices...")
    try:
        from NovaApi.ListDevices.nbe_list_devices import request_device_list
        from ProtoDecoders.decoder import get_canonic_ids, parse_device_list_protobuf

        hex_result = request_device_list()
        device_list = parse_device_list_protobuf(hex_result)
        devices = get_canonic_ids(device_list)
        print(f"\nFound {len(devices)} device(s):")
        for name, cid in devices:
            print(f"  - {name} ({cid})")
    except Exception as e:
        print(f"Could not list devices: {e}")
        print("This is normal if the auth tokens need a moment to propagate.")


if __name__ == "__main__":
    main()
