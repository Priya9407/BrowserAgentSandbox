"""
risk_taxonomy.py

Defines all supported browser risk categories.

Every browser action must belong to exactly one category.
These categories are later used by the Policy Engine to
decide whether to ALLOW, DENY or ESCALATE the action.
"""

from enum import Enum


class RiskCategory(str, Enum):
    """
    Browser action categories ordered from
    lowest risk to highest risk.
    """

    # -------------------------
    # Low Risk
    # -------------------------

    NAVIGATION = "navigation"

    # Clicking links
    # Opening menus
    # Going to another page

    # -------------------------
    # Medium Risk
    # -------------------------

    FORM_FILL = "form_fill"

    # Entering text
    # Search boxes
    # Contact forms

    # -------------------------
    # High Risk
    # -------------------------

    CREDENTIAL = "credential"

    # Username
    # Password
    # OTP
    # API Keys

    PAYMENT = "payment"

    # Checkout
    # Buy now
    # Payment gateway

    DOWNLOAD = "download"

    # Download PDF
    # Download ZIP
    # Download EXE

    SEND = "send"

    # Send email
    # Submit form
    # Send message

    FILE_UPLOAD = "file_upload"

    # Upload resume
    # Upload image
    # Upload document

    DELETE = "delete"

    # Delete account
    # Delete file
    # Remove project

    UNKNOWN = "unknown"


LOW_RISK = {
    RiskCategory.NAVIGATION,
}


MEDIUM_RISK = {
    RiskCategory.FORM_FILL,
}


HIGH_RISK = {
    RiskCategory.CREDENTIAL,
    RiskCategory.DOWNLOAD,
    RiskCategory.FILE_UPLOAD,
}


CRITICAL_RISK = {
    RiskCategory.PAYMENT,
    RiskCategory.SEND,
    RiskCategory.DELETE,
}


def get_risk_level(category: RiskCategory) -> str:
    """
    Converts category into
    LOW / MEDIUM / HIGH / CRITICAL.
    """

    if category in LOW_RISK:
        return "LOW"

    if category in MEDIUM_RISK:
        return "MEDIUM"

    if category in HIGH_RISK:
        return "HIGH"

    if category in CRITICAL_RISK:
        return "CRITICAL"

    return "UNKNOWN"
