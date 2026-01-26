#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Verify that the README logo matches the current Notubiz organisation logo.
"""

import re
import sys
from pathlib import Path

from providers.notubiz_client import get_notubiz_client


README_PATH = Path(__file__).resolve().parents[1] / "README.md"


def extract_logo_url(readme_text: str) -> str:
    """Extract the first Markdown image URL from the README."""
    match = re.search(r"!\[[^\]]*\]\(([^)]+)\)", readme_text)
    if not match:
        raise ValueError("No Markdown image URL found in README.")
    return match.group(1).strip()


def get_org_logo_url() -> str:
    """Fetch the organisation logo URL from Notubiz."""
    client = get_notubiz_client()
    org_id = client.get_organization_id()
    if not org_id:
        raise ValueError("No Notubiz organisation ID available.")

    for org in client.get_organizations():
        attrs = org.get("@attributes", {})
        candidate_id = attrs.get("id") or org.get("id")
        if str(candidate_id) == str(org_id):
            logo_url = org.get("logo")
            if not logo_url:
                raise ValueError(f"Organisation {org_id} has no logo URL.")
            return logo_url

    raise ValueError(f"Organisation ID {org_id} not found in Notubiz.")


def main() -> int:
    readme_text = README_PATH.read_text(encoding="utf-8")
    readme_logo = extract_logo_url(readme_text)
    notubiz_logo = get_org_logo_url()

    if readme_logo != notubiz_logo:
        print("README logo does not match Notubiz organisation logo.")
        print(f"README:  {readme_logo}")
        print(f"Notubiz: {notubiz_logo}")
        return 1

    print("README logo matches Notubiz organisation logo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
