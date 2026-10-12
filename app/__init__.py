# -*- coding: utf-8 -*-
"""Cost pipeline, lightweight: card file to a booked ledger entry.

Seven modules, one database, no network and no model calls.

    db          the store, and the only place SQL lives for the schema
    normalize   amounts, dates, merchants, currencies
    import_card one upload, parsed once, header- or shape-driven
    review      receive, batch summary, owner decisions
    rules       what a rule may match and what it may change
    classify    rule, then decision, then clear pattern, else needs_review
    ledger      preview with a digest, commit once, atomically

The public surface is a `Pipeline` in `__init__`, so a caller holds one object
rather than threading seven stores around.
"""

from __future__ import annotations

from .classify import classify_batch, classify_transaction
from .db import Store, StoreError, utc_now
from .import_card import ParsedFile, ParsedRow, ParseError, parse_card_file
from .ledger import commit, preview
from .review import get_batch, receive, save_decision
from .rules import list_rules, normalize_rule, rule_matches, save_rule

__all__ = ["Pipeline", "Store", "StoreError", "ParseError",
           "receive", "classify_batch", "get_batch", "save_decision",
           "preview", "commit", "save_rule", "list_rules", "parse_card_file",
           "rule_matches", "classify_transaction"]


class Pipeline:
    """The whole flow over one database.

    Built on a connection the caller already owns:

        store = Pipeline(conn)                  # the web app's own database
        store = Pipeline(Store.open(path))      # only if the caller chose the path
    """

    def __init__(self, conn_or_store):
        self.store = (conn_or_store if isinstance(conn_or_store, Store)
                      else Store(conn_or_store))

    # import
    def receive(self, content: bytes, filename: str) -> dict:
        return receive(self.store, content, filename)

    def classify_batch(self, batch_id: str, *, trip_resolver=None, review_from=None, transaction_ids=None) -> dict:
        return classify_batch(self.store, batch_id, trip_resolver=trip_resolver,review_from=review_from, transaction_ids=transaction_ids)

    def get_batch(self, batch_id: str) -> dict:
        return get_batch(self.store, batch_id)

    def save_decision(self, transaction_id: str, expected_revision: int, **kwargs) -> dict:
        return save_decision(self.store, transaction_id, expected_revision,
                             **kwargs)

    # rules
    def save_rule(self, draft: dict) -> dict:
        return save_rule(self.store, draft)

    def list_rules(self, *, status: str = "active") -> list:
        return list_rules(self.store, status=status)

    # ledger
    def preview(self, batch_id: str, *, trip_validator=None,
                tab_validator=None, review_from=None,
                entry_metadata=None, additional_holds=None, group_original=None) -> dict:
        return preview(self.store, batch_id, trip_validator=trip_validator,
                       tab_validator=tab_validator,review_from=review_from,
                       entry_metadata=entry_metadata, additional_holds=additional_holds,
                       group_original=group_original)

    def commit(self, batch_id: str, preview_digest: str, request_id: str,
               *, projection=None, trip_validator=None,
               tab_validator=None,review_from=None,
               entry_metadata=None, additional_holds=None, group_original=None, automatic_record=False) -> dict:
        return commit(self.store, batch_id, preview_digest, request_id,
                      projection=projection, trip_validator=trip_validator,
                      tab_validator=tab_validator,review_from=review_from,
                      entry_metadata=entry_metadata, additional_holds=additional_holds,
                      group_original=group_original, automatic_record=automatic_record)

    # history
    def changes(self, subject: str = "") -> list:
        return self.store.changes(subject)
