"""Pure, instance-local output choices. These are not execution authority."""
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

POLICY_VERSION = 'native-json/1'
_SUPPORTED_PAIR = ('aliyun-token-plan-openai', 'deepseek-v4.1-flash')


@dataclass(frozen=True)
class FrozenBinding:
    owner: str
    origin: str
    connection_id: str | None
    connection_auth_mode: str | None
    model: str

    @property
    def scope(self):
        # Missing connection fields are a real historical source shape, not a
        # license to resolve the current connection or to invent its identity.
        return 'explicit_connection' if self.connection_id is not None else 'legacy_source'


@dataclass(frozen=True)
class OutputPolicy:
    binding: FrozenBinding | None
    mode: Literal['unchanged', 'json_object']
    reason: Literal['no_frozen_binding', 'catalog_entry_unavailable', 'unsupported_pair', 'eligible_pair']
    version: str = POLICY_VERSION

    def parameters(self):
        return {'response_format': {'type': 'json_object'}} if self.mode == 'json_object' else {}


def frozen_binding(owner, model, source):
    """Read the existing frozen source only; never resolve defaults or credentials."""
    if (not isinstance(owner, str) or not owner or not isinstance(model, str) or not model
            or not isinstance(source, tuple) or len(source) != 2 or source[0] != owner
            or not isinstance(source[1], dict)):
        return None
    value = source[1]
    if (value.get('mode') != 'cloud' or value.get('llm_model') != model
            or value.get('owner', owner) != owner or not isinstance(value.get('server_url'), str)):
        return None
    origin = value['server_url']
    try:
        url = urlsplit(origin)
        if (url.scheme not in ('http', 'https') or not url.netloc or url.username or url.password
                or url.query or url.fragment):
            return None
    except ValueError:
        return None
    connection, auth = value.get('connection_id'), value.get('connection_auth_mode')
    if ('connection_id' in value and (not isinstance(connection, str) or not connection)
            or 'connection_auth_mode' in value and (not connection or auth not in ('account', 'api_key'))):
        return None
    return FrozenBinding(owner, origin, connection, auth, model)


def select_policy(binding, catalog):
    if binding is None:
        return OutputPolicy(None, 'unchanged', 'no_frozen_binding')
    rows = [row for row in catalog if isinstance(row, dict) and row.get('id') == binding.model
            and row.get('modelType') == 'llm'] if isinstance(catalog, list) else []
    if len(rows) != 1:
        return OutputPolicy(binding, 'unchanged', 'catalog_entry_unavailable')
    row = rows[0]
    if (row.get('providerId'), row.get('providerModel')) != _SUPPORTED_PAIR:
        return OutputPolicy(binding, 'unchanged', 'unsupported_pair')
    return OutputPolicy(binding, 'json_object', 'eligible_pair')
