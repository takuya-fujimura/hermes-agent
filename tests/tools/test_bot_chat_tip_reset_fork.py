"""Discovery pins the receipt lineage's child after a local reset.

A local reset keeps the receipt on the creation id and advances its ``lineage`` to a
physical child, but ``get_compression_tip`` deliberately does not follow reset forks
(#114271). ``_bot_chat_tip`` therefore read the owner's receipt lineage first and falls
back to the compression walk when no receipt answers.
"""
import json
import uuid
from contextlib import closing

from hermes_state import SessionDB
import hermes_state_runtime as rt
from hermes_state_local import POLICY_PREFIX, local_receipt
from tests.hermes_state.test_target_advance_fence import _local_session, _mutate
from tools.bot_live_delivery import _bot_chat_tip


def _titled_bot_chat(db, sid):
    db.set_session_title(sid, 'Bot Chat')


def test_reset_forked_bot_chat_pins_the_lineage_child(tmp_path):
    """After a reset the pin follows the receipt lineage's child, not the creation id."""
    with closing(SessionDB(tmp_path / 'state.db')) as db:
        epoch = rt.begin_runtime_epoch(db, instance_id='owner')
        sid = _local_session(db, epoch, tmp_path)
        _titled_bot_chat(db, sid)
        # get_compression_tip cannot see reset forks: it still names the creation id.
        assert db.get_compression_tip(sid) == sid
        child = _mutate(db, epoch, sid, 'reset')['target_session_id']
        assert _bot_chat_tip(tmp_path) == child


def test_no_receipt_falls_back_to_compression_tip(tmp_path):
    """Without a receipt the pre-patch compression walk is the answer."""
    with closing(SessionDB(tmp_path / 'state.db')) as db:
        sid = 'local-' + uuid.uuid4().hex
        db.create_session(session_id=sid, source='local')
        _titled_bot_chat(db, sid)
        assert _bot_chat_tip(tmp_path) == sid


def _damage_receipt(db, sid, raw):
    db._execute_write(lambda conn: conn.execute(
        'UPDATE state_meta SET value=? WHERE key=?', (raw, POLICY_PREFIX + sid)))


def test_damaged_receipt_falls_back_to_compression_tip(tmp_path):
    """A receipt that cannot be parsed must not break discovery.

    Green before and after the owner-resolve fix: this pins the *fallback contract*
    (discovery must answer for any receipt state), not the fix itself.
    """
    with closing(SessionDB(tmp_path / 'state.db')) as db:
        epoch = rt.begin_runtime_epoch(db, instance_id='owner')
        sid = _local_session(db, epoch, tmp_path)
        _titled_bot_chat(db, sid)
        _damage_receipt(db, sid, '{not json')
        assert _bot_chat_tip(tmp_path) == db.get_compression_tip(sid)


def test_receipt_missing_session_id_falls_back_to_compression_tip(tmp_path):
    """A parseable but malformed receipt is still 'any receipt state'.

    This is the case a narrowed ``except`` set must not let escape: the receipt parses,
    so no ValueError is raised, but ``local_physical_target`` reads ``session_id`` and
    raises KeyError. Green before and after the fix.
    """
    with closing(SessionDB(tmp_path / 'state.db')) as db:
        epoch = rt.begin_runtime_epoch(db, instance_id='owner')
        sid = _local_session(db, epoch, tmp_path)
        _titled_bot_chat(db, sid)
        _damage_receipt(db, sid, json.dumps({'lineage': [sid]}))
        assert _bot_chat_tip(tmp_path) == db.get_compression_tip(sid)


def test_foreign_receipt_falls_back_to_compression_tip(tmp_path):
    """A receipt naming another session under this key must not be followed.

    ``local_physical_target`` refuses the mismatch; discovery must still answer.
    Green before and after the fix.
    """
    with closing(SessionDB(tmp_path / 'state.db')) as db:
        epoch = rt.begin_runtime_epoch(db, instance_id='owner')
        sid = _local_session(db, epoch, tmp_path)
        _titled_bot_chat(db, sid)
        receipt = local_receipt(db, sid)
        receipt['session_id'] = 'local-someone-else'
        _damage_receipt(db, sid, json.dumps(receipt))
        assert _bot_chat_tip(tmp_path) == db.get_compression_tip(sid)


def test_no_bot_chat_title_row_returns_none(tmp_path):
    """A profile with a store but no Bot Chat yet answers None, not a guess.

    Green before and after the fix; previously uncovered.
    """
    with closing(SessionDB(tmp_path / 'state.db')) as db:
        epoch = rt.begin_runtime_epoch(db, instance_id='owner')
        _local_session(db, epoch, tmp_path)
        assert _bot_chat_tip(tmp_path) is None


def test_mid_segment_title_still_pins_the_head(tmp_path):
    """A title on a superseded segment must still pin the lineage head.

    On ``11d312535f`` the title row id is used as the receipt key, so the pin names the
    mid segment (RED). With the owner resolve it names the head the gateway routes to
    (GREEN). Reachable because ``/reset`` never moves the title while a Bot Mode open
    re-titles the then-head.
    """
    with closing(SessionDB(tmp_path / 'state.db')) as db:
        epoch = rt.begin_runtime_epoch(db, instance_id='owner')
        sid = _local_session(db, epoch, tmp_path)
        _titled_bot_chat(db, sid)
        mid = _mutate(db, epoch, sid, 'reset')['target_session_id']
        head = _mutate(db, epoch, sid, 'reset')['target_session_id']
        db.set_session_title(mid, 'Bot Chat')
        titled = db.get_session_by_title('Bot Chat')
        assert titled is not None and titled['id'] == mid
        assert _bot_chat_tip(tmp_path) == head

