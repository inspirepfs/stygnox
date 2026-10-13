"""OS-credential-checked, DENIED-only R3D.2 successor-attestation boundary.

Root custody is owned by the root broker, never by a user-owned Stygnox
checkout. A trusted broker may answer a strictly non-authorising request from
one pinned successor UID. No RPC can perform an execution, grant, replay,
retirement, provider call, or controller write. This is a cutover building block,
NOT the operator-approved handoff or runtime authority implementation.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import socket
import stat
import struct
from typing import Any, Mapping

from . import direct_interruption_epoch_reservation as reservation

SCHEMA = 'stygnox_r3d2_denied_broker_v1'
MAX_REQUEST = 4096
MAX_REPLY = 4096


class BrokerRefused(RuntimeError):
    """Invalid identity, source, service boundary, or requested capability."""


def _deny(reason: str) -> None:
    raise BrokerRefused(reason)


def _canonical(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False) + '\n').encode()


@dataclass(frozen=True)
class DeniedContext:
    transaction_id: str
    plan_sha256: str
    epoch: str
    successor_uid: int
    source_sha256: str
    host_boot_id: str
    reservation_sha256: str

    @classmethod
    def from_reservation(cls, record: Mapping[str, Any], *,
                         pinned_source_sha256: str, boot_id: str) -> 'DeniedContext':
        reservation.validate_reservation(record)
        if record['installed_source_archive_sha256'] != pinned_source_sha256:
            _deny('source identity differs from the exact reserved artifact')
        if record['host_boot_id'] != boot_id:
            _deny('reservation belongs to a different host boot')
        return cls(transaction_id=record['transaction_id'],
                   plan_sha256=record['approved_plan_hash'],
                   epoch=record['runtime_epoch'],
                   successor_uid=record['successor_uid'],
                   source_sha256=pinned_source_sha256,
                   host_boot_id=boot_id,
                   reservation_sha256=record['record_sha256'])

    def answer(self, *, peer_uid: int, message: Any) -> bytes:
        if peer_uid != self.successor_uid or peer_uid in (0, 1000):
            _deny('UNAUTHORISED_PEER')
        if not isinstance(message, dict) or set(message) != {
                'schema', 'operation', 'transaction_id', 'approved_plan_hash',
                'runtime_epoch', 'installed_source_archive_sha256'}:
            _deny('INVALID_REQUEST')
        if (message['schema'] != SCHEMA or message['operation'] != 'attest-denial' or
                message['transaction_id'] != self.transaction_id or
                message['approved_plan_hash'] != self.plan_sha256 or
                message['runtime_epoch'] != self.epoch or
                message['installed_source_archive_sha256'] != self.source_sha256):
            _deny('WRONG_AUTHORITY_CONTEXT')
        return _canonical({'schema': SCHEMA, 'phase': 'SUCCESSOR_IDENTITY_ATTESTED_EXECUTION_DENIED',
                           'execution_authority': 'NONE', 'provider_executed': False,
                           'legacy_controller_excluded': False,
                           'controller_admitted': False,
                           'successor_execution_authorised': False,
                           'operator_release_approved': False,
                           'transaction_id': self.transaction_id,
                           'runtime_epoch': self.epoch})


def peer_identity(connection: socket.socket) -> tuple[int, int, int]:
    """Only kernel SO_PEERCRED is trusted; never a request-supplied UID/PID."""
    if not hasattr(socket, 'SO_PEERCRED'):
        _deny('kernel peer credentials unavailable')
    raw = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i'))
    if len(raw) != struct.calcsize('3i'):
        _deny('short kernel credential record')
    return struct.unpack('3i', raw)


def _read_request(connection: socket.socket) -> Any:
    connection.settimeout(3.0)
    data = bytearray()
    while len(data) <= MAX_REQUEST:
        chunk = connection.recv(min(1024, MAX_REQUEST + 1 - len(data)))
        if not chunk:
            break
        data.extend(chunk)
        if b'\n' in chunk:
            break
    if len(data) > MAX_REQUEST or not data.endswith(b'\n') or data.count(b'\n') != 1:
        _deny('oversized or unterminated request')
    try:
        value = json.loads(data)
    except (ValueError, UnicodeError) as exc:
        raise BrokerRefused('invalid request JSON') from exc
    if _canonical(value) != bytes(data):
        _deny('noncanonical request')
    return value


def handle_connection(connection: socket.socket, context: DeniedContext) -> None:
    """Never advertise success to invalid/untrusted callers; no sensitive state."""
    with connection:
        try:
            _pid, uid, _gid = peer_identity(connection)
            if uid != context.successor_uid:
                return  # No root-owned state or detail is returned to old UID.
            body = _read_request(connection)
            reply = context.answer(peer_uid=uid, message=body)
            if len(reply) > MAX_REPLY:
                _deny('oversized reply')
            connection.sendall(reply)
        except (BrokerRefused, TimeoutError, socket.timeout, OSError):
            return


def bind_private_socket(path: Path, *, successor_gid: int) -> socket.socket:
    """Root-only socket publisher: never replaces a stale/adversarial socket."""
    if os.name != 'posix' or os.geteuid() != 0 or not hasattr(socket, 'SO_PEERCRED'):
        _deny('Linux root broker required')
    if (type(successor_gid) is not int or not 1 <= successor_gid <= 65533 or
            not path.is_absolute() or '..' in path.parts or path.name in ('', '.', '..')):
        _deny('invalid dedicated socket identity or path')
    # The entire ancestor chain must be controlled by root, not just the leaf.
    for parent in (*reversed(path.parent.parents), path.parent):
        st = parent.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or stat.S_IMODE(st.st_mode) & 0o022:
            _deny('untrusted socket ancestor')
    st = path.parent.lstat()
    if stat.S_IMODE(st.st_mode) != 0o710 or st.st_gid != successor_gid:
        _deny('socket directory must be root:successor-gid 0710')
    if os.path.lexists(path):
        _deny('existing socket path is never adopted or removed')
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        old_mask = os.umask(0o177)
        try:
            server.bind(str(path))
        finally:
            os.umask(old_mask)
        os.chown(path, 0, successor_gid)
        os.chmod(path, 0o660)
        st = path.lstat()
        if not stat.S_ISSOCK(st.st_mode) or st.st_uid != 0 or st.st_gid != successor_gid:
            _deny('socket inode was substituted')
        server.listen(16)
        return server
    except Exception:
        server.close()
        # Leave failed publication in place for manual inspection.
        raise


def serve_denied_forever(server: socket.socket, context: DeniedContext) -> None:
    """Intentional service loop with no release, execution or state-write route."""
    while True:
        conn, _ = server.accept()
        handle_connection(conn, context)
