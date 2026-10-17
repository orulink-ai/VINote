#!/usr/bin/env python3
"""Clone the verified VINote prefix into one bounded host-Nginx upload route.

Read-only by default. Explicit paths, --execute and the reviewed input SHA256
are required for mutation. No third-party packages, network probes or inference.
"""
import argparse
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import uuid

PREFIX = b"/vinote-api/"
UPLOAD = b"/vinote-api/api/generate_from_upload"
LIMIT = 129 * 1024 * 1024
MAX_CONFIG = 2 * 1024 * 1024


class PatchError(RuntimeError):
    pass


class ApplyError(PatchError):
    def __init__(self, message, receipt):
        super().__init__(message)
        self.receipt = receipt


@dataclass
class Token:
    value: bytes
    start: int
    end: int
    structural: bool = False


@dataclass
class Node:
    words: list
    start: int
    end: int
    opening: int | None = None
    children: list = field(default_factory=list)
    parent: object = None

    @property
    def values(self):
        return [word.value for word in self.words]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def tokenize(data):
    """Small fail-closed Nginx lexer: quoted/comment braces are not structure."""
    tokens, pos = [], 0
    while pos < len(data):
        if data[pos] in b" \t\r\n":
            pos += 1
            continue
        if data[pos] == 35:
            end = data.find(b"\n", pos)
            pos = len(data) if end < 0 else end + 1
            continue
        start = pos
        if data[pos] in b"{};":
            tokens.append(Token(data[pos:pos + 1], pos, pos + 1, True))
            pos += 1
            continue
        value = bytearray()
        while pos < len(data) and data[pos] not in b" \t\r\n{};#":
            if data[pos] in (34, 39):
                quote = data[pos]
                pos += 1
                while pos < len(data) and data[pos] != quote:
                    if data[pos] == 92:
                        pos += 1
                        if pos >= len(data):
                            raise PatchError("Unterminated quoted escape")
                    value.append(data[pos])
                    pos += 1
                if pos == len(data):
                    raise PatchError("Unterminated quoted value")
                pos += 1
            elif data[pos:pos + 2] == b"${":
                end = data.find(b"}", pos + 2)
                if end < 0 or not re.fullmatch(rb"[A-Za-z0-9_]+", data[pos + 2:end]):
                    raise PatchError("Unsupported variable syntax")
                value.extend(data[pos:end + 1])
                pos = end + 1
            elif data[pos] == 92:
                pos += 1
                if pos == len(data):
                    raise PatchError("Unterminated escape")
                value.append(data[pos])
                pos += 1
            else:
                value.append(data[pos])
                pos += 1
        if pos == start:
            raise PatchError("Unsupported configuration syntax")
        tokens.append(Token(bytes(value), start, pos))
    return tokens


def parse(data):
    tokens = tokenize(data)
    pos = 0

    def scope(parent=None):
        nonlocal pos
        nodes, words = [], []
        while pos < len(tokens):
            token = tokens[pos]
            pos += 1
            if token.structural and token.value == b"}":
                if parent is None or words:
                    raise PatchError("Unexpected closing brace")
                parent.end = token.end
                return nodes
            if token.structural and token.value in (b";", b"{"):
                if not words:
                    raise PatchError("Empty directive")
                node = Node(words, words[0].start, token.end, parent=parent)
                words = []
                if token.value == b"{":
                    node.opening = token.start
                    node.children = scope(node)
                nodes.append(node)
            else:
                words.append(token)
        if parent is not None or words:
            raise PatchError("Unterminated directive or block")
        return nodes
    return scope()


def flatten(nodes):
    for node in nodes:
        yield node
        yield from flatten(node.children)


def directives(node, name):
    return [child for child in node.children if child.values[0] == name]


def one(node, name, required=True):
    matches = directives(node, name)
    if len(matches) > 1 or not matches and required:
        raise PatchError("Missing or duplicate " + name.decode())
    if matches and matches[0].opening is not None:
        raise PatchError("Expected a simple directive")
    return matches[0] if matches else None


def body_size(value):
    match = re.fullmatch(rb"([0-9]+)([kKmMgG]?)", value)
    if not match:
        raise PatchError("Unknown or dynamic client_max_body_size")
    size = int(match[1]) * {b"": 1, b"k": 1024, b"m": 1024 ** 2, b"g": 1024 ** 3}[match[2].lower()]
    return None if size == 0 else size  # Nginx zero means unlimited.


def effective_size(node):
    current = node
    while current is not None:
        directive = one(current, b"client_max_body_size", required=False)
        if directive:
            if len(directive.words) != 2:
                raise PatchError("Invalid body size directive")
            return body_size(directive.words[1].value)
        current = current.parent
    raise PatchError("Body-size inheritance is outside this file; inspect it manually")


def validate_proxy(node):
    if any(child.opening is not None for child in node.children):
        raise PatchError("Nested blocks are unsupported inside the VINote location")
    rewrite = one(node, b"rewrite")
    if rewrite.values != [b"rewrite", b"^/vinote-api/(.*)$", b"/$1", b"break"]:
        raise PatchError("Unexpected prefix rewrite; cannot safely clone it")
    proxy = one(node, b"proxy_pass")
    if len(proxy.words) != 2 or not re.fullmatch(rb"https?://[^/?#\s]+", proxy.words[1].value):
        raise PatchError("Unexpected proxy_pass URI")
    auth = [item for item in directives(node, b"proxy_set_header")
            if len(item.words) >= 2 and item.words[1].value.lower() == b"authorization"]
    if len(auth) != 1 or auth[0].values != [b"proxy_set_header", b"Authorization", b"$http_authorization"]:
        raise PatchError("Expected explicit unchanged Bearer forwarding")
    buffer = one(node, b"proxy_request_buffering", required=False)
    if buffer and buffer.values not in ([b"proxy_request_buffering", b"on"], [b"proxy_request_buffering", b"off"]):
        raise PatchError("Unexpected proxy_request_buffering value")


def block_start(data, node):
    start = data.rfind(b"\n", 0, node.start) + 1
    if data[start:node.start].strip(b" \t"):
        raise PatchError("Location must begin on its own line")
    return start


def signature(node):
    return [child.values for child in node.children
            if child.values[0] not in (b"client_max_body_size", b"proxy_request_buffering")]


def rewrite_block(data, node, *, make_exact):
    start = block_start(data, node)
    block = data[start:node.end]
    indent = data[start:node.start]
    newline = b"\r\n" if b"\r\n" in block else b"\n"
    edits, additions = [], []
    if make_exact:
        edits.append((node.start, node.opening, b"location = " + UPLOAD + b" "))
    size = one(node, b"client_max_body_size", required=False)
    if size:
        edits.append((size.words[1].start, size.words[1].end, b"129m"))
    else:
        additions.append(b"client_max_body_size 129m;")
    buffer = one(node, b"proxy_request_buffering", required=False)
    if buffer:
        edits.append((buffer.words[1].start, buffer.words[1].end, b"off"))
    else:
        additions.append(b"proxy_request_buffering off;")
    if additions:
        insertion = b"".join(newline + indent + b" " + value for value in additions)
        edits.append((node.opening + 1, node.opening + 1, insertion))
    for first, end, value in sorted(edits, reverse=True):
        block = block[:first - start] + value + block[end - start:]
    return block, start, newline


def plan_config(original):
    if not original or len(original) > MAX_CONFIG or b"\x00" in original:
        raise PatchError("Empty, oversized or binary configuration")
    nodes = list(flatten(parse(original)))
    prefixes = [node for node in nodes if node.values == [b"location", b"^~", PREFIX]]
    if len(prefixes) != 1:
        raise PatchError("Expected exactly one literal VINote prefix location")
    prefix = prefixes[0]
    if prefix.parent is None or prefix.parent.values != [b"server"]:
        raise PatchError("VINote prefix must be directly inside one server block")
    validate_proxy(prefix)
    exacts = [node for node in nodes if node.values == [b"location", b"=", UPLOAD]]
    if any(node.values[0] == b"location" and UPLOAD in b" ".join(node.values[1:])
           and node not in exacts for node in nodes):
        raise PatchError("Conflicting non-exact upload location; inspect it manually")
    if len(exacts) > 1:
        raise PatchError("Ambiguous existing upload route")
    exact = exacts[0] if exacts else None
    if exact:
        if exact.parent is not prefix.parent:
            raise PatchError("Upload route belongs to a different server")
        validate_proxy(exact)
        if signature(exact) != signature(prefix):
            raise PatchError("Existing upload route differs from prefix forwarding/restrictions")
    size = effective_size(exact or prefix)
    report = {"original_sha256": sha(original), "effective_body_limit_bytes": size,
              "exact_upload_location": UPLOAD.decode(), "planned_body_limit": "129m",
              "runtime_verified": False}
    if size is None or size >= LIMIT:
        return original, {**report, "action": "noop", "reason": "existing_limit_sufficient", "candidate_sha256": sha(original)}
    block, start, newline = rewrite_block(original, exact or prefix, make_exact=exact is None)
    candidate = (original[:start] + block + original[exact.end:] if exact else
                 original[:start] + block + newline + original[start:])
    # Parse again and independently verify the original prefix was not edited.
    updated = list(flatten(parse(candidate)))
    before = original[prefix.start:prefix.end]
    after = [n for n in updated if n.values == [b"location", b"^~", PREFIX]]
    target = [n for n in updated if n.values == [b"location", b"=", UPLOAD]]
    if len(after) != 1 or candidate[after[0].start:after[0].end] != before or len(target) != 1:
        raise PatchError("Postcondition failed: original prefix must remain byte-identical")
    if effective_size(target[0]) != LIMIT or one(target[0], b"proxy_request_buffering").values[-1] != b"off":
        raise PatchError("Postcondition failed: upload route is not bounded and unbuffered")
    validate_proxy(target[0])
    return candidate, {**report, "action": "update_exact" if exact else "add_exact", "candidate_sha256": sha(candidate)}


def read_config(path):
    if not path.is_absolute() or path.is_symlink() or path.resolve(strict=True) != path:
        raise PatchError("Use an explicit absolute canonical config path, without symlinks")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_CONFIG:
        raise PatchError("Config must be a bounded regular file with one link")
    data = path.read_bytes()
    after = path.stat()
    if any(getattr(after, key) != getattr(info, key) for key in
           ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")):
        raise PatchError("Config changed during read")
    return data, info


def command(argv):
    try:
        result = subprocess.run(argv, capture_output=True, timeout=20, check=True)
    except (OSError, subprocess.SubprocessError):
        # Never echo nginx -T output: other vhosts may contain private values.
        raise PatchError("Nginx command failed: " + " ".join(str(v) for v in argv)) from None
    return result.stdout


def verify_loaded(runner, nginx_bin, config, expected):
    dump = runner([str(nginx_bin), "-T"])
    marker = b"# configuration file " + os.fsencode(config) + b":\n"
    if dump.count(marker) != 1:
        raise PatchError("Selected config is not uniquely loaded by this nginx binary")
    contents = dump.split(marker, 1)[1].split(b"\n# configuration file ", 1)[0]
    if contents.rstrip(b"\r\n") != expected.rstrip(b"\r\n"):
        raise PatchError("Nginx loaded config differs from the selected host file")


@contextmanager
def config_lock(path):
    import fcntl  # Host deployment is POSIX; pure planning/tests are portable.
    lock = path.with_name("." + path.name + ".upload.lock")
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode) or os.fstat(descriptor).st_nlink != 1:
            raise PatchError("Unsafe lock file")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


def sync_directory(path):
    if os.name == "posix":
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def atomic_write(path, data, info):
    descriptor, name = tempfile.mkstemp(prefix="." + path.name + ".upload-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            if hasattr(os, "fchown"):
                os.fchown(stream.fileno(), info.st_uid, info.st_gid)
            if hasattr(os, "fchmod"):
                os.fchmod(stream.fileno(), stat.S_IMODE(info.st_mode))
            os.fsync(stream.fileno())
        os.replace(name, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def apply(config, nginx_bin, expected_sha256, runner=command):
    with config_lock(config):
        original, info = read_config(config)
        if not re.fullmatch(r"[a-f0-9]{64}", expected_sha256) or sha(original) != expected_sha256:
            raise PatchError("Config SHA256 does not match the reviewed dry-run")
        candidate, report = plan_config(original)
        if report["action"] == "noop":
            return {**report, "executed": False, "backup": None}
        verify_loaded(runner, nginx_bin, config, original)
        backup = config.with_name(config.name + ".upload-" + sha(original) + "." + uuid.uuid4().hex + ".bak")
        descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(original)
            stream.flush()
            os.fsync(stream.fileno())
        if sha(backup.read_bytes()) != sha(original):
            raise PatchError("Backup hash verification failed")
        sync_directory(config.parent)
        receipt = {**report, "config": str(config), "backup": str(backup), "backup_sha256": sha(original),
                   "runtime_verified": True, "executed": False, "rolled_back": False}
        changed = False
        try:
            if read_config(config)[0] != original:
                raise PatchError("Config changed before apply")
            changed = True
            atomic_write(config, candidate, info)
            runner([str(nginx_bin), "-t"])
            if read_config(config)[0] != candidate:
                raise PatchError("Config changed concurrently during validation")
            verify_loaded(runner, nginx_bin, config, candidate)
            runner([str(nginx_bin), "-s", "reload"])
            if read_config(config)[0] != candidate:
                raise PatchError("Config changed concurrently during reload")
            return {**receipt, "executed": True}
        except Exception as failure:
            receipt["failure"] = str(failure) if isinstance(failure, PatchError) else type(failure).__name__
            if changed:
                try:
                    current = read_config(config)[0]
                    if current not in (candidate, original):
                        raise PatchError("Concurrent config change; refusing to overwrite it")
                    if current != original:
                        atomic_write(config, original, info)
                    receipt["bytes_restored"] = sha(config.read_bytes()) == sha(original)
                    runner([str(nginx_bin), "-t"])
                    verify_loaded(runner, nginx_bin, config, original)
                    runner([str(nginx_bin), "-s", "reload"])
                    receipt["rolled_back"] = True
                except Exception:
                    receipt["rollback_requires_attention"] = True
            raise ApplyError("Upload route apply failed; inspect rollback receipt and the original backup", receipt) from failure


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--nginx-bin", required=True, type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--expected-sha256", default="")
    args = parser.parse_args(argv)
    try:
        if not args.nginx_bin.is_absolute() or not args.nginx_bin.is_file():
            raise PatchError("Provide the explicit absolute host nginx binary path")
        if args.execute and not args.expected_sha256:
            raise PatchError("--execute requires --expected-sha256 from the reviewed dry-run")
        original, _ = read_config(args.config)
        if args.execute:
            report = apply(args.config, args.nginx_bin, args.expected_sha256)
        else:
            _, report = plan_config(original)
            report.update(executed=False, config=str(args.config), nginx_bin=str(args.nginx_bin))
        print(json.dumps(report, sort_keys=True))
        return 0
    except (PatchError, OSError) as error:
        print(json.dumps({"error": str(error), **getattr(error, "receipt", {})}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
