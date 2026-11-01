"""Authoritative record limits, shared by validation and model guidance."""
MAX_NEW_ITEMS_PER_RECORD = 20
MAX_ROOT_ITEMS = 4
MAX_TREE_DEPTH = 10
MAX_CHECKPOINT_SUMMARY_LENGTH = 500
MAX_TITLE_LENGTH = 160
MAX_ITEM_SUMMARY_LENGTH = 1200
MAX_RESUME_LENGTH = 600
MAX_ID_LENGTH = 100
MAX_RECORD_PAYLOAD_BYTES = 100_000
MIN_SORT_ORDER = -(2**31)
MAX_SORT_ORDER = 2**31 - 1


def compact_guidance() -> str:
    return (
        f"Limits (characters, before trimming): checkpoint summary 1..{MAX_CHECKPOINT_SUMMARY_LENGTH}; "
        f"concept title 1..{MAX_TITLE_LENGTH}, summary {MAX_ITEM_SUMMARY_LENGTH}, resume {MAX_RESUME_LENGTH}, "
        f"id 1..{MAX_ID_LENGTH}. Canonical UTF-8 JSON <= {MAX_RECORD_PAYLOAD_BYTES} bytes; "
        f"<= {MAX_NEW_ITEMS_PER_RECORD} new concepts/record, {MAX_ROOT_ITEMS} roots, depth {MAX_TREE_DEPTH}. "
        "One operation/id; exact positive expected_revision for existing IDs, omit for new IDs. "
        f"Optional sort_order: integer {MIN_SORT_ORDER}..{MAX_SORT_ORDER}."
    )
