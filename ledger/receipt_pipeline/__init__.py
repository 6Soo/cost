"""Lossless local-receipt extraction helpers."""

from .validator import ReceiptBatchError, validate_batch

__all__ = ["ReceiptBatchError", "validate_batch"]
