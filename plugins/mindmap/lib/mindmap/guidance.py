"""Automatic guidance reads the validator's current constants."""
from . import store as validator


def record_limits() -> dict[str, int]:
    return {
        "checkpoint_summary_chars": validator.MAX_CHECKPOINT_SUMMARY_LENGTH,
        "id_chars": validator.MAX_ITEM_ID_LENGTH,
        "title_chars": validator.MAX_TITLE_LENGTH,
        "concept_summary_chars": validator.MAX_ITEM_SUMMARY_LENGTH,
        "resume_chars": validator.MAX_RESUME_LENGTH,
        "new_concepts_per_record": validator.MAX_NEW_ITEMS_PER_RECORD,
        "roots": validator.MAX_ROOT_ITEMS,
        "depth": validator.MAX_TREE_DEPTH,
        "canonical_payload_utf8_bytes": validator.MAX_RECORD_PAYLOAD_BYTES,
    }


def limits_line() -> str:
    v = record_limits()
    return (
        f"Limits: checkpoint summary {v['checkpoint_summary_chars']} chars; title {v['title_chars']}; "
        f"concept summary {v['concept_summary_chars']}; resume {v['resume_chars']}; id {v['id_chars']}; "
        f"new concepts/record {v['new_concepts_per_record']}; roots {v['roots']}; depth {v['depth']}; "
        f"canonical payload {v['canonical_payload_utf8_bytes']} UTF-8 bytes."
    )


def record_schema() -> dict:
    return {
        "required": ["summary", "operations"],
        "optional": {"concept_model": "causal-tree-v2"},
        "limits": record_limits(),
        "operations": {
            "upsert": {"required": ["id"], "new_item_required": ["title"],
                       "optional": ["title", "summary", "resume", "state", "kind", "parent_id", "sort_order", "expected_revision", "restore"]},
            "settle": {"required": ["id", "expected_revision"], "optional": ["title", "summary", "resume"]},
            "remove": {"required": ["id", "expected_revision"], "optional": ["reparent_to"]},
        },
        "states": sorted(validator.VALID_STATES), "kinds": sorted(validator.VALID_KINDS),
        "rules": [
            "Unknown fields are rejected. Summary must be nonempty; operations may be empty.",
            "Use exact expected_revision for every existing item; omit for new items. One operation per id.",
            "Omitted fields retain their values; resume empty string explicitly clears it.",
            "Removing a parent requires reparent_to. The complete resulting graph must be acyclic and within limits.",
            "Restore a user-deleted id only on explicit user request using a new-item upsert with restore:true.",
            "Numbered chronology ids/titles are rejected. There is no lifetime concept-count ceiling.",
            "The entire payload is one immediate SQLite transaction; invalid operations roll it all back.",
            "Exact retries do not acknowledge later tool work. A correction after intervening work must be a deliberate different payload.",
        ],
    }
