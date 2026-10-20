"""Consent and frozen participant/grouping options; no provider requests."""
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import feishu_auto_policy as policy
from app.services import feishu_service as module
from app.models.feishu_destination import FeishuDeliveryDestinationDB
from test_feishu_auto_policy import contact_service, enable, policy_id, submit  # noqa: F401
from test_feishu_delivery import service  # noqa: F401


def test_legacy_policy_fingerprint_is_unchanged():
    original = dict(binding={'owner': 'a'}, destination={'kind': 'personal'},
                    notify_self=True, groups=[], permission_policy='private', contacts=[])
    assert policy.spec(**{'current_binding': original.pop('binding')},
                       **original) == {'binding': {'owner': 'a'}, **original}


@pytest.mark.parametrize('flag', ['notify_participants', 'group_meeting_versions'])
def test_new_policy_option_cannot_expand_enabled_consent_silently(contact_service, monkeypatch, flag):
    previous = enable(contact_service, monkeypatch)
    body = dict(notify_self=False, groups=[], auto_publish=True, contacts=[{'open_id': 'ou_b'}], **{flag: True})
    if flag == 'group_meeting_versions':
        target = {'kind': 'wiki', 'space_id': 'space', 'node_token': 'root'}
        monkeypatch.setattr(contact_service, 'check_destination', lambda owner, target: {**target, 'can_attempt_create': True})
        body['destination_config'] = target
    with pytest.raises(module.FeishuError) as caught:
        contact_service.save_preferences('a', body)
    assert caught.value.code == 'automatic_consent_required'
    assert contact_service.status('a')['automatic_delivery']['policy_id'] == policy_id(previous)


def test_grouping_rejects_non_wiki_destination(contact_service, monkeypatch):
    with pytest.raises(module.FeishuError) as caught:
        enable(contact_service, monkeypatch, group_meeting_versions=True)
    assert caught.value.code == 'invalid_destination'


def test_grouping_scope_is_frozen_in_accepted_delivery(contact_service, monkeypatch):
    target = {'kind': 'wiki', 'space_id': 'space', 'node_token': 'root'}
    monkeypatch.setattr(contact_service, 'check_destination', lambda owner, target: {**target, 'can_attempt_create': True})
    chosen = enable(contact_service, monkeypatch, destination_config=target, group_meeting_versions=True)
    accepted = submit(contact_service, policy_id(chosen))
    with module.session_scope() as db:
        snapshot = json.loads(db.get(FeishuDeliveryDestinationDB, accepted['id']).snapshot)
    assert snapshot['group_meeting_versions'] is True
    assert {key: snapshot['destination'][key] for key in target} == target
    assert snapshot['app_id'] == contact_service.config.feishu_app_id


def test_participant_resolution_runs_once_and_freezes_only_public_evidence(contact_service, monkeypatch):
    chosen = enable(contact_service, monkeypatch, notify_participants=True)
    resolver = Mock(return_value={'contacts': [], 'candidates': [], 'confirmation_status': 'cleared',
        'unresolved': [{'reason': 'attendance_identity_unverified'}], 'evidence_revision': 'frozen'})
    monkeypatch.setitem(sys.modules, 'app.services.meeting_participants', SimpleNamespace(resolve_saved_meeting=resolver))
    accepted = submit(contact_service, policy_id(chosen))
    resolver.assert_called_once()
    with module.session_scope() as db:
        snapshot = json.loads(db.get(FeishuDeliveryDestinationDB, accepted['id']).snapshot)
    assert 'contacts' not in snapshot['meeting_attendance']
    assert snapshot['meeting_attendance']['evidence_revision'] == 'frozen'
    contact_service.delivery_by_operation('a', accepted['operation_id'])
    assert resolver.call_count == 1


def test_tampered_new_scope_invalidates_original_consent(contact_service, monkeypatch):
    chosen = enable(contact_service, monkeypatch, notify_participants=True)
    with module.session_scope() as db:
        row = db.get(module.FeishuConnectionDB, 'a')
        prefs = json.loads(row.preferences)
        prefs['auto_policy']['notify_participants'] = False
        row.preferences = json.dumps(prefs)
    with pytest.raises(module.FeishuError) as caught:
        submit(contact_service, policy_id(chosen))
    assert caught.value.code == 'automatic_policy_changed'


@pytest.mark.parametrize('confirmation_status', ['unconfirmed', 'stale', None])
def test_unconfirmed_participants_wait_before_any_delivery_is_created(contact_service, monkeypatch, confirmation_status):
    chosen = enable(contact_service, monkeypatch, notify_participants=True)
    resolver = Mock(return_value={'contacts': [], 'candidates': [], 'unresolved': [],
                                  'confirmation_status': confirmation_status})
    monkeypatch.setitem(sys.modules, 'app.services.meeting_participants', SimpleNamespace(resolve_saved_meeting=resolver))
    with pytest.raises(module.FeishuError) as caught:
        submit(contact_service, policy_id(chosen))
    assert caught.value.code == 'attendance_confirmation_required'
    assert caught.value.uncertain is False
    with module.session_scope() as db:
        assert db.query(module.FeishuDeliveryDB).count() == 0


@pytest.mark.parametrize('flag', ['notify_participants', 'group_meeting_versions'])
def test_disabled_edit_preferences_round_trip_without_expanding_saved_consent_or_delivery(contact_service, monkeypatch, flag):
    target = {'kind': 'wiki', 'space_id': 'space', 'node_token': 'root'}
    monkeypatch.setattr(contact_service, 'check_destination', lambda owner, destination: {**destination, 'can_attempt_create': True})
    initial = enable(contact_service, monkeypatch, destination_config=target)
    accepted = submit(contact_service, policy_id(initial))
    with module.session_scope() as db:
        original_snapshot = db.get(FeishuDeliveryDestinationDB, accepted['id']).snapshot
        original_policy = json.loads(db.get(module.FeishuConnectionDB, 'a').preferences)['auto_policy']
    changes = dict(notify_self=False, groups=[], auto_publish=False,
                   contacts=[{'open_id': 'ou_b'}], destination_config=target, **{flag: True})
    saved = contact_service.save_preferences('a', changes)
    assert saved[flag] is True
    assert contact_service.status('a')[flag] is True
    assert saved['auto_publish'] is False and saved['automatic_delivery']['enabled'] is False
    with module.session_scope() as db:
        preferences = json.loads(db.get(module.FeishuConnectionDB, 'a').preferences)
        assert preferences[flag] is True
        # Editing a disabled setting is not a newly authorized target scope.
        assert preferences['auto_policy'] == {**original_policy, 'enabled': False}
        assert db.get(FeishuDeliveryDestinationDB, accepted['id']).snapshot == original_snapshot
    with pytest.raises(module.FeishuError) as caught:
        contact_service.save_preferences('a', {**changes, 'auto_publish': True})
    assert caught.value.code == 'automatic_consent_required'
    assert contact_service.status('a')['auto_publish'] is False
    confirmed = contact_service.save_preferences('a', {**changes, 'auto_publish': True,
                                                      'automatic_delivery_consent': True})
    assert confirmed[flag] is True
    assert policy_id(confirmed) != policy_id(initial)
    with module.session_scope() as db:
        assert db.get(FeishuDeliveryDestinationDB, accepted['id']).snapshot == original_snapshot
