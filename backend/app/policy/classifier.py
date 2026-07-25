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

        target = action.target.lower()

        reasoning = action.reasoning.lower()

        text = action.cited_source_text.lower()

        combined = f"{target} {reasoning} {text}"

        # --------------------------
        # PAYMENT
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
        # LOGIN / PASSWORD
        # --------------------------

        credential_keywords = [
            "password",
            "login",
            "signin",
            "sign-in",
            "otp",
            "credential",
            "username",
            "email",
            "api key",
            "token",
        ]

        if any(word in combined for word in credential_keywords):
            return RiskCategory.CREDENTIAL

        # --------------------------
        # DOWNLOAD
        # --------------------------

        download_keywords = ["download", ".exe", ".zip", ".pdf", ".apk", "installer"]

        if any(word in combined for word in download_keywords):
            return RiskCategory.DOWNLOAD

        # --------------------------
        # SEND
        # --------------------------

        send_keywords = [
            "send",
            "submit",
            "post",
            "publish",
            "email",
            "message",
            "share",
        ]

        if any(word in combined for word in send_keywords):
            return RiskCategory.SEND

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
        # FORM FILL
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
        # NAVIGATION
        # --------------------------

        navigation_keywords = [
            "next",
            "previous",
            "home",
            "menu",
            "continue",
            "back",
            "link",
        ]

        if any(word in combined for word in navigation_keywords):
            return RiskCategory.NAVIGATION

        return RiskCategory.UNKNOWN
