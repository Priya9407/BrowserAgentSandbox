"""
hidden_detector.py

Detects hidden HTML elements that may contain prompt injection attacks.

The detector uses Playwright to inspect the browser's
computed CSS instead of relying only on raw HTML.

Author: Frontier
"""

from playwright.sync_api import Page


class HiddenContentDetector:
    def __init__(self):
        pass

    def detect(self, page: Page):
        """
        Returns

        {
            "hidden_found": bool,
            "elements": [...]
        }
        """

        js = """
        () => {

            const elements = [...document.querySelectorAll("*")];

            const hidden = [];

            for (const el of elements) {

                const style = window.getComputedStyle(el);

                const rect = el.getBoundingClientRect();

                const reasons = [];

                // -----------------------
                // display:none
                // -----------------------

                if (style.display === "none")
                    reasons.push("display:none");

                // -----------------------
                // visibility:hidden
                // -----------------------

                if (style.visibility === "hidden")
                    reasons.push("visibility:hidden");

                // -----------------------
                // opacity:0
                // -----------------------

                if (parseFloat(style.opacity) === 0)
                    reasons.push("opacity:0");

                // -----------------------
                // font-size:0
                // -----------------------

                if (parseFloat(style.fontSize) === 0)
                    reasons.push("font-size:0");

                // -----------------------
                // width/height
                // -----------------------

                if (rect.width === 0 || rect.height === 0)
                    reasons.push("zero-size");

                // -----------------------
                // Off-screen
                // -----------------------

                if (
                    rect.x < -500 ||
                    rect.y < -500
                )
                    reasons.push("off-screen");

                // -----------------------
                // Hidden via clip-path
                // -----------------------

                if (
                    style.clipPath !== "none"
                )
                    reasons.push("clip-path");

                // -----------------------
                // Transform
                // -----------------------

                if (
                    style.transform.includes("scale(0)")
                )
                    reasons.push("scale(0)");

                // -----------------------

                if (reasons.length > 0) {

                    hidden.push({

                        tag: el.tagName,

                        id: el.id,

                        className: el.className,

                        text: el.innerText,

                        html: el.outerHTML,

                        reasons: reasons

                    });

                }

            }

            return {

                hidden_found: hidden.length > 0,

                count: hidden.length,

                elements: hidden

            };

        }
        """

        return page.evaluate(js)
