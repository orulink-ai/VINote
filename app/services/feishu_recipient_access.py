"""Pure recipient ACL state predicates; no provider calls or credential access."""

POLICY = "grant_view_and_notify"
PROTOCOL = 1


def permission_unknown(target, state):
    # A message ambiguity takes precedence and must never be cleared by ACL reads.
    if state.get("status") in ("sending", "unknown", "sent"):
        return False
    return (state.get("status") == "permission_unknown" or
            state.get("reading_permission", {}).get("status") in ("granting", "unknown") or
            # Older group grants had no journal. Preserve ambiguous historical
            # failures rather than interpreting a timeout as permission to grant again.
            (target.startswith("oc_") and state.get("status") == "failed" and
             state.get("error_code") == "result_unknown"))


def has_permission_unknown(recipients):
    return any(permission_unknown(target, state) for target, state in recipients.items())
