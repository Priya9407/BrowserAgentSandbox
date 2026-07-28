"""
source_classifier.py

Instruction-Source Classifier — the core of the provenance layer.

Answers ONE question per action:
  Where did the agent's cited reasoning come from?

Output (Origin enum):
  USER_TASK            — reasoning traces back to what the human typed
  VISIBLE_PAGE_CONTENT — reasoning cites text visible on the page
  HIDDEN_PAGE_CONTENT  — reasoning cites text hidden from the user

The key insight (repeat to every judge):
  We don't classify WHAT an instruction says.
  We classify WHERE it came from.
  A page can phrase an injection as politely as it wants —
  if it didn't originate from the user's task, it doesn't
  get to trigger a real-world action.
"""

from difflib import SequenceMatcher
from app.policy.models import Origin


# Minimum overlap ratio to consider a match
_MATCH_THRESHOLD = 0.55


def _normalise(text: str) -> str:
    """Lowercase + collapse whitespace for comparison."""
    return " ".join(text.lower().split())


def _overlap_ratio(a: str, b: str) -> float:
    """
    Longest-common-subsequence ratio between two strings.
    Returns 0.0–1.0.  Uses Python's difflib so there are
    no extra dependencies.
    """
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _contains_substring(needle: str, haystack: str) -> bool:
    """True if needle (or any 6+-word window of it) appears in haystack."""
    if not needle or not haystack:
        return False
    if needle in haystack:
        return True
    # sliding window — catches partial citations
    words = needle.split()
    window = 6
    for i in range(len(words) - window + 1):
        chunk = " ".join(words[i : i + window])
        if chunk in haystack:
            return True
    return False


class SourceClassifier:
    """
    Classifies the origin of an agent action's cited_source_text.

    Usage
    -----
    classifier = SourceClassifier()
    origin = classifier.classify(
        cited_source_text = action.cited_source_text,
        user_task         = "Buy the cheapest laptop under ₹50000",
        visible_page_text = page_text["visible"],   # plain text visible to user
        hidden_page_text  = page_text["hidden"],    # text from hidden DOM elements
    )
    """

    def classify(
        self,
        cited_source_text: str,
        user_task: str,
        visible_page_text: str = "",
        hidden_page_text: str = "",
    ) -> Origin:
        cited = _normalise(cited_source_text)
        task = _normalise(user_task)
        visible = _normalise(visible_page_text)
        hidden = _normalise(hidden_page_text)

        # ------------------------------------------------------------------
        # 1. Does the cited text overlap sufficiently with the user's task?
        #    Check this first — the user task is the ground truth.
        # ------------------------------------------------------------------
        if self._matches_user_task(cited, task):
            return Origin.USER_TASK

        # ------------------------------------------------------------------
        # 2. Does the cited text appear in HIDDEN page content?
        #    Check hidden BEFORE visible — text in a hidden element may also
        #    appear in the full DOM dump; we want the stricter classification.
        # ------------------------------------------------------------------
        if hidden and self._found_in_page(cited, hidden):
            return Origin.HIDDEN_PAGE_CONTENT

        # ------------------------------------------------------------------
        # 3. Does it appear in VISIBLE page content?
        # ------------------------------------------------------------------
        if visible and self._found_in_page(cited, visible):
            return Origin.VISIBLE_PAGE_CONTENT

        # ------------------------------------------------------------------
        # 4. Fallback — the agent cited something not present on the page.
        #    Most likely it paraphrased the user task.  Treat as USER_TASK
        #    (safe default — the policy engine's risk layer still applies).
        # ------------------------------------------------------------------
        return Origin.USER_TASK

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _matches_user_task(self, cited: str, task: str) -> bool:
        """
        True when the cited text is clearly rooted in the user's own words.
        Uses both substring containment and fuzzy overlap so paraphrases
        are also caught.
        """
        if _contains_substring(cited, task) or _contains_substring(task, cited):
            return True
        if _overlap_ratio(cited, task) >= _MATCH_THRESHOLD:
            return True
        return False

    def _found_in_page(self, cited: str, page_text: str) -> bool:
        """
        True when the cited text is traceable to content on the page.
        """
        if _contains_substring(cited, page_text):
            return True
        if _overlap_ratio(cited, page_text) >= _MATCH_THRESHOLD:
            return True
        return False
