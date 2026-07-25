from pathlib import Path
from playwright.sync_api import sync_playwright


def test_playwright():

    # Locate shopping.html automatically
    project_root = Path(__file__).resolve().parents[2]

    html_path = project_root / "test-pages" / "shopping.html"

    url = html_path.as_uri()

    print(f"Opening: {url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=500)

        page = browser.new_page()

        page.goto(url)

        print("Page loaded")

        # Check if button exists
        button = page.locator("#buy")

        assert button.count() == 1

        print("Button Found")

        # Click button
        button.click()

        print("Button Clicked")

        page.screenshot(path="playwright_test.png")

        print("Screenshot Saved")

        browser.close()

        print("Test Passed")


if __name__ == "__main__":
    test_playwright()
