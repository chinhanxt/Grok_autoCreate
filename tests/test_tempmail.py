import re
import pytest
from core.tempmail import TempMailClient


def test_otp_regex_extraction():
    sample_texts = [
        "Your xAI verification code is 806901. Valid for 10 minutes.",
        "Mã xác thực của bạn là: 112466",
        "Use 982341 to complete your signup on Grok."
    ]
    for text in sample_texts:
        match = re.search(r"\b(\d{6})\b", text)
        assert match is not None
        assert len(match.group(1)) == 6
