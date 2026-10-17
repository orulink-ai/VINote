from app.services.workspace_migration_service import portable_version, version_batches


def test_internal_ids_and_parent_links_use_same_stable_mapping():
    parent = portable_version('note', {'id': '__vinote:old', 'content': 'before'})
    child = portable_version('note', {'id': 'user-id', 'parent_id': '__vinote:old', 'evidence_revision': 5, 'content': 'after'})
    assert child['parent_id'] == parent['id']
    assert child['id'] == 'user-id'
    assert 'evidence_revision' not in child
    assert portable_version('note', {'id': '__vinote:old'})['id'] == parent['id']


def test_history_batches_obey_size_and_count_limits():
    versions = [{'id': str(i), 'content': '中' * 300000} for i in range(60)]
    batches = list(version_batches(versions))
    assert sum(map(len, batches)) == 60
    assert max(map(len, batches)) <= 4
    assert len(list(version_batches([{'id': str(i)} for i in range(120)]))) == 3
