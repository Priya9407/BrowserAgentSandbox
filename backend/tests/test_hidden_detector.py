from pathlib import Path

from playwright.sync_api import sync_playwright

from app.policy.hidden_detector import HiddenContentDetector


detector = HiddenContentDetector()


with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)

    page = browser.new_page()

    project_root = Path(__file__).resolve().parents[2]

    page.goto((project_root / "test-pages" / "hidden.html").as_uri())

    result = detector.detect(page)

    print(result)

    browser.close()
