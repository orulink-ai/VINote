"""Content-free preparation reasons accepted by task status serialization."""
SUMMARY_PREFLIGHT_CODES = frozenset({
    'summary_preflight_owner_changed', 'summary_preflight_task_changed',
    'summary_preflight_context_changed', 'summary_preflight_source_changed',
    'summary_preflight_reference_changed', 'summary_preflight_request_changed',
    'summary_preflight_snapshot_changed', 'summary_preflight_visual_changed',
    'summary_preflight_visual_unavailable', 'summary_preflight_unconfirmed',
})
