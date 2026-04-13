#!/var/lib/server3-browser-brain/venv/bin/python
from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish a static HTML file into FileGator.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--remote-dir", required=True)
    parser.add_argument("--source-path", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    source_path = args.source_path.resolve()
    if not source_path.exists():
        raise SystemExit(f"source file not found: {source_path}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(args.base_url, wait_until="domcontentloaded", timeout=60000)
            page.fill('input[name="username"]', args.username)
            page.fill('input[name="password"]', args.password)
            page.click('button:has-text("Log in")')
            page.wait_for_timeout(2000)

            body = page.locator("body")
            if args.remote_dir not in body.inner_text():
                page.click("text=New")
                page.wait_for_timeout(500)
                page.click("text=Folder")
                page.wait_for_timeout(500)
                page.fill('input[placeholder="MyFolder"]', args.remote_dir)
                page.click('button:has-text("Create")')
                page.wait_for_timeout(1500)

            page.click(f"text={args.remote_dir}")
            page.wait_for_timeout(1500)
            page.locator('input[type="file"]').first.set_input_files(str(source_path))
            page.wait_for_timeout(4000)
            body_text = page.locator("body").inner_text()
            expected_line = f"/{args.remote_dir}/{source_path.name}"
            if expected_line not in body_text and source_path.name not in body_text:
                raise RuntimeError(f"upload could not be verified for {expected_line}")
        finally:
            browser.close()
    print(f"uploaded {source_path.name} to /{args.remote_dir}/{source_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
