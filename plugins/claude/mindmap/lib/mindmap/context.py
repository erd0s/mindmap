"""Bounded automatic views; the stored graph and explicit exports stay complete."""
from __future__ import annotations

import json
import re
from typing import Any

PROMPT_CONTEXT_BYTES = 8192
SESSION_CONTEXT_BYTES = 8192
STOP_CONTEXT_BYTES = 3072
# Budgets include JSON escaping on the wire, not just Python character counts.
ENVELOPE_RESERVE = 128


def wire_size(text: str) -> int:
    return len(json.dumps(text, ensure_ascii=False).encode("utf-8"))


def bounded_text(text: str, budget: int) -> str:
    if wire_size(text) <= budget:
        return text
    suffix = "\n[Additional diagnostic text omitted.]"
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if wire_size(text[:middle] + suffix) <= budget:
            low = middle
        else:
            high = middle - 1
    return text[:low] + suffix


def automatic_map(snapshot: dict[str, Any], budget: int, focus: str = "") -> str:
    """Select whole rows, explicitly disclosing omitted concepts and fields.

    Rows are a partial view, never a pruned replacement tree. Parent identifiers
    stay exact even when their rows do not fit. Retrieve snapshot before editing
    an omitted concept, checking a relationship, or restoring a deleted branch.
    """
    from .store import MAX_ROOT_ITEMS, MAX_TREE_DEPTH, MAX_TITLE_LENGTH

    items = snapshot["items"]
    children = {item["parent_id"] for item in items}
    words = set(re.findall(r"\w{3,}", focus.casefold()))

    def priority(item: dict[str, Any]) -> tuple:
        text = " ".join(str(item.get(k) or "") for k in ("title", "summary", "resume"))
        matches = len(words.intersection(re.findall(r"\w{3,}", text.casefold())))
        return (item["state"] != "settled", matches, item["id"] not in children,
                item["updated_at"], item["id"])

    roots = sum(item["parent_id"] is None for item in items)
    parents = {item["id"]: item["parent_id"] for item in items}
    overdeep = False
    for item in items:
        cursor = item["id"]
        for _ in range(MAX_TREE_DEPTH):
            cursor = parents.get(cursor)
            if cursor is None:
                break
        else:
            if cursor is not None:
                overdeep = True
                break
    preface = [
        f"Mindmap {'is active' if snapshot['project']['active'] else 'tracking is stopped'} for {snapshot['project']['route_path']}.",
        "PARTIAL CAUSAL TREE / FRONTIER: selected rows, not a complete tree; parent rows may be omitted.",
        "Summaries and resumes are previews, not replacement values. Omitted fields retain their stored values.",
        "Retrieve the full snapshot for exact IDs, revisions, relationships, text and USER-DELETED BRANCHES before editing omitted concepts or restoring anything.",
        "Continue the matching frontier; for a genuinely new concept, parent it to the frontier it grew from, not to the root merely because this is a new session.",
    ]
    if roots > MAX_ROOT_ITEMS or overdeep:
        preface.append("LEGACY MAP OUTSIDE COMPRESSION BOUNDS: do not expand; retrieve the snapshot and reconcile first.")
    # Counts precede optional rows, so even a further host preview cannot make
    # the selected sample look complete. No graph mutations occur here.
    warnings = snapshot["semantic_warnings"]
    deleted = snapshot["user_deleted_branches"]
    chosen: list[str] = []

    def render(count: int) -> str:
        return "\n".join([
            *preface,
            f"Concepts shown: {count}/{len(items)}; omitted: {len(items)-count}. "
            f"Warning details omitted: {len(warnings)}; user-deleted details omitted: {len(deleted)}.",
            "Do not recreate user-deleted concepts without an explicit user request and restore:true.",
            *chosen,
        ])

    for item in sorted(items, key=priority, reverse=True):
        # Keep exact identity/revision/parent/state; bound only optional prose.
        row = {key: item[key] for key in ("id", "parent_id", "revision", "state", "kind")}
        for key, limit in (("title", MAX_TITLE_LENGTH), ("summary", 180), ("resume", 180)):
            value = str(item[key])
            row[key] = value if len(value) <= limit else value[:limit] + "… [preview]"
        chosen.append(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
        if wire_size(render(len(chosen))) > budget:
            chosen.pop()
    text = render(len(chosen))
    # Unusually long legacy route names cannot displace the omission contract.
    if wire_size(text) > budget:
        return f"PARTIAL MAP: all {len(items)} concepts omitted by the context budget. Retrieve the full snapshot, including warnings and USER-DELETED BRANCHES."
    return text
