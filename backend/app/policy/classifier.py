"""
classifier.py

Classifies an AgentAction into a browser risk category.

This is the first stage of the Policy Engine.

Example:

Click #buy
↓

PAYMENT

Click #login
↓

CREDENTIAL

Click #download
↓

DOWNLOAD
"""

from app.schemas.action_schema import AgentAction
from app.policy.risk_taxonomy import RiskCategory


class RiskClassifier:
    def __init__(self):
        pass

    def classify(self, action: AgentAction) -> RiskCategory:

        target = (action.target or "").lower()
        text = (action.cited_source_text or "").lower()
        label = action.semantic_target.label.lower()
        
        # Don't include reasoning, it contains generalized verbs that trigger false positives!
        combined = f"{target} {text} {label}"

        # --------------------------
        # CONSEQUENCE-BASED PRE-CHECK
        # If the action_type itself implies a sensitive consequence,
        # classify based on that before looking at keywords.
        # This catches cases where a "Continue" button actually
        # triggers payment, credential submission, or data send.
        # --------------------------
        if action.action_type in ("fill", "type"):
            # Filling a form field is always at least FORM_FILL;
            # the keyword checks below may escalate it further.
            pass

        # --------------------------
        # PAYMENT  (highest priority — check first)
        # --------------------------

        payment_keywords = [
            "buy",
            "checkout",
            "payment",
            "pay",
            "upi",
            "visa",
            "mastercard",
            "credit",
            "debit",
            "purchase",
            "cart",
            "order",
        ]

        if any(word in combined for word in payment_keywords):
            return RiskCategory.PAYMENT

        # --------------------------
        # CREDENTIAL  (login, password, token)
        # "email" alone is intentionally NOT a credential — contact forms
        # and signup boxes on normal pages contain email fields everywhere,
        # which caused false-positive escalations on everyday pages.
        # --------------------------

        credential_keywords = [
            "password",
            "login",
            "signin",
            "sign-in",
            "otp",
            "credential",
            "username",
            "api key",
            "token",
        ]

        if any(word in combined for word in credential_keywords):
            return RiskCategory.CREDENTIAL

        # --------------------------
        # SEND  (send, email, message, share, publish)
        # Check BEFORE download so "send file" patterns are caught
        # as SEND rather than DOWNLOAD.
        #
        # ⚠️ False-positive guard: normal conversation pages (chats, social
        # feeds, forums) have "Send", "Message", "Share" and "Publish"
        # buttons everywhere. Only classify as SEND when the action is an
        # actual CLICK on a send-like control — typing in a message box or
        # navigating to a message page is not itself a send.
        # --------------------------

        send_keywords = [
            "send",
            "email",
            "message",
            "share",
            "publish",
        ]

        if action.action_type == "click" and any(word in combined for word in send_keywords):
            return RiskCategory.SEND

        # --------------------------
        # DOWNLOAD
        # --------------------------

        download_keywords = ["download", ".exe", ".zip", ".pdf", ".apk", "installer"]

        if any(word in combined for word in download_keywords):
            return RiskCategory.DOWNLOAD

        # --------------------------
        # FILE UPLOAD
        # --------------------------

        upload_keywords = ["upload", "choose file", "browse", "resume", "attachment"]

        if any(word in combined for word in upload_keywords):
            return RiskCategory.FILE_UPLOAD

        # --------------------------
        # DELETE
        # --------------------------

        delete_keywords = ["delete", "remove", "erase", "destroy", "clear"]

        if any(word in combined for word in delete_keywords):
            return RiskCategory.DELETE

        # --------------------------
        # FORM FILL  (input, search, name, address, phone)
        # --------------------------

        form_keywords = [
            "input",
            "textbox",
            "textarea",
            "search",
            "name",
            "address",
            "phone",
        ]

        if any(word in combined for word in form_keywords):
            return RiskCategory.FORM_FILL

        # --------------------------
        # NAVIGATION  (lowest priority — only if no sensitive match)
        # Moved to END so that "Continue", "Next", "Back" etc. are
        # only classified as NAVIGATION when no payment/credential/
        # send/download keyword was present.
        # --------------------------

        navigation_keywords = [
            "next",
            "previous",
            "continue",
            "back",
            "home",
            "menu",
            "link",
        ]

        if any(word in combined for word in navigation_keywords):
            return RiskCategory.NAVIGATION

        # --------------------------
        # FALLBACK: check action_type for consequence-based inference
        # If the action is a fill/type but no keywords matched,
        # it's still a form interaction — classify as FORM_FILL.
        # --------------------------
        if action.action_type in ("fill", "type"):
            return RiskCategory.FORM_FILL

        if action.action_type == "navigate":
            return RiskCategory.NAVIGATION

        return RiskCategory.UNKNOWN
