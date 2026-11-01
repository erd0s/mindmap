"""Bounded graph reads. No transcript, session history, or full snapshot export."""
from __future__ import annotations

import base64
import hashlib
import json
import re
from typing import Any

from .errors import MindmapError
from .store import Store, semantic_warnings

PAGE_BYTES = 16384
ROOT_OVERVIEW_BYTES = 1024


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def graph_data(store: Store, project_id: int, *, fingerprint: bool = False) -> dict[str, Any]:
    with store.read_transaction() as db:
        project, items = store._project_and_items(db, project_id)
        # Only decode the latest update per item. Older provenance stays in the
        # deliberate snapshot export; state-transition timestamps are aggregated
        # inside SQLite rather than shipping event history into Python.
        updates = {}
        for row in db.execute('''
            SELECT item_id, payload_json FROM events WHERE id IN (
              SELECT max(id) FROM events WHERE project_id = ?
                AND event_type = 'item.updated' GROUP BY item_id)
        ''', (project_id,)):
            updates[row['item_id']] = json.loads(row['payload_json'])
        changes, change_keys = {}, {}
        for row in db.execute('''
            SELECT item_id, created_at, idempotency_key FROM events WHERE id IN (
              SELECT max(id) FROM events
              WHERE project_id = ? AND event_type = 'item.updated'
                AND coalesce(CASE WHEN json_extract(payload_json, '$.operation.op') = 'settle'
                    THEN 'settled' END, json_extract(payload_json, '$.operation.state'))
                    != json_extract(payload_json, '$.previous_state')
              GROUP BY item_id)
        ''', (project_id,)):
            changes[row['item_id']] = row['created_at']
            change_keys[row['item_id']] = (row['idempotency_key'] or '').rpartition(':')[0]
        # Use the same causal warning semantics as snapshots, including same
        # record parent/child transitions whose event clocks can differ by 1 ms.
        record_keys = {}
        for row in db.execute('''
            SELECT item_id, idempotency_key FROM events WHERE id IN (
              SELECT max(id) FROM events WHERE project_id = ?
                AND event_type IN ('item.created','item.updated','item.restored') GROUP BY item_id)
        ''', (project_id,)):
            key = row['idempotency_key'] or ''
            record_keys[row['item_id']] = key.rpartition(':')[0]
        by_id = {item['id']: item for item in items}
        for item in items:
            parent = by_id.get(item['parent_id'])
            if parent and change_keys.get(item['id']) and change_keys.get(item['id']) == record_keys.get(parent['id']):
                changes[item['id']] = parent['updated_at']
        deleted = store._user_deleted_branches(db, project_id)
        recent = dict(db.execute('SELECT item_id, source_session_pk FROM items WHERE project_id = ?', (project_id,)))
    warnings = semantic_warnings(items, updates, changes)
    material = {'items': items, 'warnings': warnings, 'deleted': deleted}
    return {**material, 'project': project, 'recent': recent,
            'snapshot': hashlib.sha256(encode(material).encode()).hexdigest() if fingerprint else None}


def read_page(store: Store, project_id: int, *, item_id: str | None = None,
              parent: str | None = None, roots: bool = False, notices: bool = False,
              cursor: str | None = None) -> dict[str, Any]:
    if sum((item_id is not None, parent is not None, roots, notices)) > 1:
        raise MindmapError('Choose one of --id, --parent, --roots, or --notices.')
    data = graph_data(store, project_id, fingerprint=True)
    selector = [item_id, parent, roots, notices]
    offset = 0
    if cursor:
        try:
            saved = json.loads(base64.urlsafe_b64decode(cursor))
            if saved['snapshot'] != data['snapshot'] or saved['selector'] != selector:
                raise MindmapError('Map or selection changed; refresh without --cursor.')
            offset = saved['offset']
            if type(offset) is not int or offset < 0:
                raise ValueError('offset')
        except (ValueError, KeyError, TypeError) as exc:
            raise MindmapError('Invalid cursor; refresh without --cursor.') from exc
    if notices:
        records = ([{'type': 'warning', **w} for w in data['warnings']] +
                   [{'type': 'user_deleted', **d} for d in data['deleted']])
    else:
        records = [i for i in data['items'] if
                   (item_id is None or i['id'] == item_id) and
                   (parent is None or i['parent_id'] == parent) and
                   (not roots or i['parent_id'] is None)]
    records = sorted(records, key=lambda i: (i.get('id', i.get('item_id', '')), i.get('type', '')))
    result = {'snapshot': data['snapshot'], 'total': len(records), 'records': [],
              'warnings': len(data['warnings']), 'user_deleted': len(data['deleted']),
              'next_cursor': None}
    for record in records[offset:]:
        next_offset = offset + len(result['records']) + 1
        continuation = base64.urlsafe_b64encode(encode({
            'snapshot': data['snapshot'], 'selector': selector, 'offset': next_offset,
        }).encode()).decode() if next_offset < len(records) else None
        candidate = {**result, 'records': [*result['records'], record], 'next_cursor': continuation}
        if len(encode(candidate).encode()) + 1 > PAGE_BYTES:
            if not result['records']:
                raise MindmapError('Legacy record exceeds page budget; use deliberate snapshot export.')
            break
        result = candidate
    return result


_STOP_WORDS = set('the a an and or to of in for with this that it is on do please continue work start sync status stop mindmap manage'.split())


def selected_units(data: dict[str, Any], prompt: str, session_pk: int | None):
    """Yield whole units, relevant concepts first, with stable ancestor context."""
    items = data['items']
    by_id = {i['id']: i for i in items}
    words = set(re.findall(r'[\w-]{3,}', prompt.casefold())) - _STOP_WORDS
    def score(item: dict[str, Any]) -> tuple:
        explicit = bool(re.search(r'(?<![\w-])' + re.escape(item['id'].casefold()) + r'(?![\w-])', prompt.casefold()))
        match = len(words & set(re.findall(r'[\w-]{3,}', ' '.join(str(item[k]) for k in ('title', 'summary', 'resume')).casefold())))
        recent = session_pk is not None and data['recent'].get(item['id']) == session_pk
        return (explicit, match, recent, item['state'] != 'settled', item['updated_at'])
    ranked = sorted(items, key=lambda i: i['id'])
    ranked.sort(key=score, reverse=True)
    # Small maps already expose their roots in the complete selected records.
    # Larger maps reserve compact discovery without repeating resume fields.
    parents = {i['parent_id'] for i in items}
    roots = sorted((i for i in items if i['parent_id'] is None), key=lambda i: i['id'])[:4] if len(items) > 4 else []
    overview_bytes = 0
    for item in roots:
        overview = {k: item[k] for k in ('id', 'title', 'state', 'revision')}
        unit = 'ROOT ' + encode(overview)
        # Count escaping in the enclosing hook JSON too. Root discovery must
        # leave room for a requested concept, even with four maximum-size roots.
        if overview_bytes + len(encode(unit).encode()) + 1 > ROOT_OVERVIEW_BYTES:
            del overview['title']
            unit = 'ROOT ' + encode({**overview, 'title_omitted': True})
        unit_bytes = len(encode(unit).encode()) + 1
        if overview_bytes + unit_bytes <= ROOT_OVERVIEW_BYTES:
            overview_bytes += unit_bytes
            yield '', unit
    emitted = set()
    for item in ranked:
        chain = []
        current = item
        visited = set()
        while current and current['id'] not in emitted and current['id'] not in visited:
            visited.add(current['id'])
            chain.append(current)
            current = by_id.get(current['parent_id'])
        for concept in chain:
            emitted.add(concept['id'])
            yield concept['id'], encode({k: concept[k] for k in
                         ('id', 'parent_id', 'revision', 'title', 'state', 'kind', 'summary', 'resume')} |
                         {'frontier': concept['state'] != 'settled' and concept['id'] not in parents})
