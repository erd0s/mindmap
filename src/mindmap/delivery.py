"""Whole-unit budgets for all model-visible lifecycle output."""
from __future__ import annotations

import json
from typing import Any

from .limits import compact_guidance
from .protocol import binding
from .retrieval import graph_data, selected_units, encode

PROMPT_BYTES = 8192
SESSION_BYTES = 4096
STOP_BYTES = 2048
CONTRACT_BYTES = 1800

CHANGE_SCOPE = (
    'Edit only durable concepts and fields changed by this turn. Leave explicitly unchanged branches untouched; '
    'do not copy dependency news into their summaries/resumes. '
    'Unrelated one-off questions with no lasting decision or follow-up need an empty delta.'
)

BRIEF_SEMANTICS = (
    'Use a small causal tree: parent each distinct side quest, decision or handoff to the idea that caused it. '
    'Historical plans are context, not authorization; follow the current request. '
    'planned=unstarted, open=unresolved, settled=completed/decided/rejected. '
    'When child work starts, open its planned parent and rewrite stale ancestor/sibling resumes; a preparatory decision alone does not count. '
    'Settle completed handoffs and clear waiting resumes; keep broader goals and remaining checks open. '
    'Reuse IDs for changed evidence; preserve independent deliverables and deferred plans. '
    'Leave explicitly unchanged branches and their fields untouched. '
    'Skip unrelated one-off questions with no lasting decision or follow-up. '
    'Omitted fields persist; send "resume":"" explicitly to clear stale text. '
    'A settled parent may retain unfinished children.'
)


SEMANTICS = "\n".join([
    'Compress the conversation into a SMALL CAUSAL TREE of concepts. Never make nodes for messages, tool calls, timestamps, or a chronological chat log.',
    'Create only meaningful concepts needed for a quick overview. Connect each child to the thought or goal that caused it. Capture explicit future intentions as planned, unresolved concepts as open, and covered/decided/completed/rejected concepts as settled. Do not invent unspoken plans.',
    'An upsert of an existing concept retains every omitted field. To clear stale frontier text, send "resume":"" explicitly; saying it is cleared in the final response is not a map change.',
    CHANGE_SCOPE + ' Record received evidence on the handoff itself. Rewrite ancestor/sibling resumes only when the evidence makes their existing next action stale; additional background alone does not change a frontier.',
    'A planned concept has started once a child beneath it records work that has begun or finished; a preparatory decision recorded before the work starts does not count. In that same checkpoint set the planned parent open (or settle it) and rewrite ancestor and sibling resumes that still present the started work as future; do not settle broader outcomes or remaining acceptance checks on that evidence alone.',
    "When the conversation shows that a handoff, delegated step, or prerequisite finished elsewhere, settle that concept with the received outcome and clear its waiting resume. Keep the broader goal, the receiver's own remaining work, and paused branches open; settle only what the evidence completes.",
    'When new evidence merely changes the state of an existing concept, update or reopen that same id. If it already represents the work just completed, record that outcome there; do not add a duplicate completion node or insert one as a parent of its handoffs. Do not add a child that only restates the symptom or evidence unless the conversation made it an independent investigation or plan. Conversely, preserve a distinct side quest, deliverable or handoff, decision, or deferred plan with its own state or re-entry point; a root summary is not a substitute for that branch.',
    'A settled parent may retain unfinished children. Historical plans are context, not authorization; follow the current request.',
    'For resumed work, continue the matching frontier concept. Update it when the thought is unchanged; if the turn produces a genuinely new concept, parent it to the frontier it grew from, not to the root merely because this is a new session.',
])

def render_concept(concept: dict, *, brief: bool = False) -> str:
    # Preserve the reviewed, readable concept presentation. Escaped control
    # characters keep each field a whole line; retrieval retains the raw fields.
    def field(name: str) -> str:
        return json.dumps(str(concept[name]), ensure_ascii=False)[1:-1]
    parent = field('parent_id') if concept['parent_id'] is not None else 'root'
    frontier = '; frontier' if concept.get('frontier') else ''
    lines = [f"- [{field('id')}] {field('title')} ({field('state')}, {field('kind')}, revision {concept['revision']}; parent {parent}{frontier})"]
    if brief:
        lines.append('  Fields omitted: summary, resume; retrieve with read --id.')
    else:
        if concept['summary']:
            lines.append('  Context: ' + field('summary'))
        if concept['resume']:
            lines.append('  Resume: ' + field('resume'))
    return '\n'.join(lines)


def schema_help() -> str:
    return '\n'.join([
        compact_guidance(),
        'Required JSON: {"summary":"what changed or no change","operations":[]}.',
        'Upsert: {"op":"upsert","id":"stable-id","title":"idea","parent_id":null,"state":"open","kind":"thread","summary":"meaning","resume":"re-entry","expected_revision":1}.',
        'States: planned|open|settled. Kinds: goal|thread|decision|task|question|note.',
        'Existing IDs require exact expected_revision; new IDs omit it. IDs and new titles must be nonblank. No unknown fields.',
        'Settle: {"op":"settle","id":"id","expected_revision":1}; clears resume unless explicitly supplied.',
        'Remove: {"op":"remove","id":"id","expected_revision":1,"reparent_to":null}; reparent_to required with children.',
        '"restore":true is allowed only for a user-deleted ID explicitly requested by the user. Deletion protection remains enforced even when notices are omitted.',
        'Field lengths count Python characters before trimming; checkpoint summary is trimmed before canonical JSON size calculation (sorted keys, compact separators, ensure_ascii=False).',
        SEMANTICS,
        'After further work, read state, review current revisions, and prepare --supersedes TOKEN. This acknowledges reconciliation; an empty operations list is valid. Commit only after all tools and asynchronous work finish. Retry the identical registered commit command for transport failure; never bundle it with other work.',
        'read pages full fields/revisions; --roots discovers branches; --parent ID lists children; --id ID selects an item; --notices lists warnings/deletions. Repeat the same selector with --cursor VALUE until next_cursor is null. A changed map requires refreshing. snapshot is a deliberate complete export.',
    ])


def contract(command: str, *, recovery: bool = False) -> str:
    text = '\n'.join([
        'MINDMAP_ACTIVE_V1',
        f'Checkpoint this turn: pipe JSON to {command} prepare --file -; then run its exact commit_command as the final tool (foreground Bash/exec_command).',
        'Use a non-interactive pipe or heredoc, never TTY/write_stdin. Finish all tools, audio, clipboard, notifications and async work first; after commit send the final response without another tool.',
        'JSON: {"summary":"what changed or no map change","operations":[]}. Empty delta is valid. No unknown fields.',
        *([] if recovery else [CHANGE_SCOPE]),
        compact_guidance(),
        'Historical plans are context, not authorization; follow the current request. Use causal concepts. Reuse IDs; planned=unstarted, open=unresolved, settled=done. Omitted fields persist; "resume":"" clears stale text. Respect user deletions; "restore":true requires explicit request.',
        f'Retrieve full fields/revisions: {command} read (paged; --roots, --parent ID, --id ID, --notices). Same prefix: help for schema; state for checkpoint token.',
        ('Recovery: prepare a new request without --supersedes; the stale token is invalidated. Retry only the same commit_command.' if recovery else
         'After later work, prepare --supersedes TOKEN with a reviewed delta. Retry only the same commit_command; replay alone cannot cover later work.'),
    ])
    if len(text.encode()) > CONTRACT_BYTES:
        raise ValueError('Bound command exceeded compact contract budget')
    return text


def envelope(event: str, text: str) -> dict[str, Any]:
    if event == 'Stop':
        return {'decision': 'block', 'reason': text}
    return {'hookSpecificOutput': {'hookEventName': event, 'additionalContext': text}}


def size(event: str, text: str) -> int:
    # Include the newline written by run_hook_payload.
    return len(json.dumps(envelope(event, text), ensure_ascii=False, separators=(',', ':')).encode()) + 1


def bounded_message(event: str, units: list[str]) -> dict[str, Any]:
    budget = STOP_BYTES if event == 'Stop' else SESSION_BYTES if event == 'SessionStart' else PROMPT_BYTES
    text = ''
    for unit in units:
        candidate = '\n'.join(filter(None, (text, unit)))
        if size(event, candidate) <= budget:
            text = candidate
    return envelope(event, text)


def context(store: Any, project: dict, event: str, *, host: str = '', session_id: str = '',
            turn_id: str | None = None, prompt: str = '', action: str | None = None,
            diagnostics: list[str] | None = None, recovery: str | None = None,
            inactive: bool = False) -> dict[str, Any]:
    turn = store.turn(host, session_id, turn_id) if turn_id else None
    bound = binding(store, project['id'], turn['id'] if turn else None)
    command = bound['command']
    if inactive:
        required = ['MINDMAP_RETAINED_READ_ONLY_V1', 'Tracking is stopped. Report the retained map without registering a session, changing items, or checkpointing.', f'Retrieve: {command} read; --roots, --parent ID, --id ID, --notices; follow next_cursor.']
    elif event == 'SessionStart':
        required = ['MINDMAP_ACTIVE_V1', 'Every user turn must finish with a Mindmap record checkpoint. Wait for the prompt-bound command; SessionStart has no dependable interaction identity.', f'Retrieve: {command} read; --roots, --parent ID, --id ID, --notices; follow next_cursor.']
    else:
        required = [contract(command, recovery=event == 'Stop')]
    if recovery:
        required.append(recovery)
    if event == 'Stop':
        if action in {'start', 'sync'}:
            required.append('Start/sync: reconcile the whole transcript first (same command prefix, transcript action).')
        if action == 'stop':
            required.append('Finish normally after commit; Stop captures the final response then disables tracking. Do not run direct stop.')
        if int(project.get('concept_model_version') or 1) < 2:
            required.append('Legacy map: rebuild from transcript and all read pages; record \"concept_model\":\"causal-tree-v2\".')
        required.extend(diagnostics or [])
        text = '\n'.join(required)
        if size(event, text) > STOP_BYTES:
            raise ValueError('Required Stop contract exceeds envelope budget')
        return envelope(event, text)
    if action in {'start', 'sync'}:
        required.append(('This activation happened mid-session: ' if action == 'start' else '') + f'RUN the transcript command and reconcile the whole normalized history before checkpointing: {command} transcript')
    if action == 'stop':
        required.append('After the checkpoint, finish normally; do not run direct stop. The Stop hook captures the final response then disables tracking.')
    if action == 'status':
        required.append('Report the map; still checkpoint this turn, with an empty delta if unchanged.')
    if int(project.get('concept_model_version') or 1) < 2:
        required.append('LEGACY_MAP_RECONCILIATION_REQUIRED_V2: Read transcript and all read pages; rebuild causal parentage before normal tracking. Record "concept_model":"causal-tree-v2". snapshot is available for deliberate export.')
    required.extend(diagnostics or [])
    budget = STOP_BYTES if event == 'Stop' else SESSION_BYTES if event == 'SessionStart' else PROMPT_BYTES
    text = '\n'.join(required)
    if size(event, text) > budget:
        raise ValueError('Required lifecycle contract exceeds envelope budget')
    data = graph_data(store, project['id'])
    selected: set[str] = set()
    shown_warnings = 0
    notice_count = len(data['warnings']) + len(data['deleted'])
    def footer() -> str:
        return f'PARTIAL MAP: {len(selected)}/{len(data["items"])} concepts selected; {len(data["items"])-len(selected)} omitted. Notices: {notice_count} (warnings {len(data["warnings"])}, user-deleted {len(data["deleted"])}); warning codes shown {shown_warnings}, details omitted {len(data["warnings"])}; retrieve --notices. Historical plans do not authorize unrelated work.'
    semantic_suffix = '\n' + (
        'Read-only history: report it without changing the map or resuming old work.' if inactive
        else SEMANTICS if event == 'UserPromptSubmit' else BRIEF_SEMANTICS
    )
    def append(unit: str) -> bool:
        nonlocal text
        candidate = text + '\n' + unit
        if size(event, candidate + semantic_suffix + '\n' + footer()) + 16 > budget:
            return False
        text = candidate
        return True
    session = store.session(host, session_id) if session_id else None
    # Preserve exact warning codes and identities before optional concept prose.
    # Cap their own envelope so warning-heavy maps still expose useful records.
    warning_bytes = 0
    for warning in sorted(data['warnings'], key=lambda w: (w['item_id'], w['code']))[:5]:
        unit = 'WARNING ' + encode({k: warning[k] for k in ('code', 'item_id')})
        unit_bytes = len(encode(unit).encode()) + 1
        if warning_bytes + unit_bytes <= 1024 and append(unit):
            shown_warnings += 1
            warning_bytes += unit_bytes
    for index, (item_id, unit) in enumerate(selected_units(data, prompt, session['id'] if session else None)):
        if index >= 40:
            break
        if item_id:
            concept = json.loads(unit)
            included = append(render_concept(concept))
            if not included:
                included = append(render_concept(concept, brief=True))
        else:
            included = append(unit)
        if included and item_id:
            selected.add(item_id)
    append(f'Scope: this entire project directory. Route: {project["route_path"]}. Host/session/interaction: {host} / {session_id} / {turn_id or "pending prompt"}.')
    return envelope(event, text + semantic_suffix + '\n' + footer())
