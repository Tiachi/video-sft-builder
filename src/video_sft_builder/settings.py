"""Private persistent settings, public frozen run plans and provider capabilities."""
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
import uuid

from .config import ROLES, RuntimeConfig, money, positive, template, validate_config
from .errors import ConfigError
from .util import asset, canonical, read_json, within, write_json


def default_settings_path():
    return Path(os.environ.get('VIDEO_SFT_CONFIG', str(Path.home() / '.config/video-sft-builder/config.json'))).expanduser().resolve()


def validate_run_name(value):
    if (not isinstance(value, str) or not value or len(value.encode('utf-8')) > 180
            or not value[0].isalnum() or not re.fullmatch(r'[\w.-]+', value, flags=re.UNICODE)
            or value.endswith('.') or value in ('.', '..')):
        raise ConfigError('Build name must start with a letter/number and contain only letters, numbers, _, - or .')
    return value


def private_write_json(path, value, *, replace=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not replace:
        raise FileExistsError('Private settings already exist')
    staging = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.part')
    try:
        fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(staging, path)
        else:
            from .util import publish_file
            publish_file(staging, path)
        os.chmod(path, 0o600)
    finally:
        staging.unlink(missing_ok=True)


def merged(base, updates):
    value = deepcopy(base)
    for key, item in updates.items():
        value[key] = merged(value[key], item) if isinstance(value.get(key), dict) and isinstance(item, dict) else deepcopy(item)
    return value


def validate_public_provider(provider):
    from .util import safe_name
    allowed = set(read_json(asset('configs/provider_presets.json'))['vllm'])
    if not isinstance(provider, dict) or set(provider) != allowed:
        raise ConfigError('Unknown/missing provider fields; secrets belong only in private settings api_key')
    if provider['backend'] not in ('qwen_compatible', 'deepseek', 'vllm', 'openai_compatible'):
        raise ConfigError('Unsupported provider backend')
    endpoint = urlsplit(provider['base_url'])
    if (endpoint.scheme not in ('https', 'http') or not endpoint.hostname or endpoint.username or endpoint.password
            or endpoint.query or endpoint.fragment or (endpoint.scheme == 'http' and not provider['allow_http'])):
        raise ConfigError('Provider endpoint must use HTTPS, or explicit allow_http for a trusted local deployment')
    if not isinstance(provider['model'], str) or not provider['model']:
        raise ConfigError('Model ID is missing')
    safe_name(provider['key_env'])
    for key in ('provider_max_input_tokens', 'timeout_seconds', 'max_video_bytes', 'max_payload_bytes', 'max_response_bytes'):
        positive(provider[key], 'provider.' + key, integer=True)
    if set(provider['capabilities']) != {'text', 'images', 'native_video'} or not all(type(v) is bool for v in provider['capabilities'].values()):
        raise ConfigError('Provider capabilities must be explicit booleans')
    if provider['transport'] not in ('base64', 'dashscope_oss', 'file_uri'):
        raise ConfigError('Unknown media transport')
    if provider['transport'] == 'dashscope_oss' and provider['backend'] != 'qwen_compatible':
        raise ConfigError('DashScope OSS is only valid for its Qwen adapter')
    if provider['transport'] == 'file_uri' and provider['backend'] != 'vllm':
        raise ConfigError('file_uri is restricted to explicitly configured vLLM deployments')
    if provider['transport'] == 'file_uri':
        from pathlib import PurePosixPath
        if (not Path(provider['local_media_root']).is_absolute() or not provider['server_media_root'].startswith('/')
                or '..' in PurePosixPath(provider['server_media_root']).parts):
            raise ConfigError('file_uri needs absolute, non-traversing local/server media roots')
    if provider['backend'] == 'deepseek' and provider['capabilities']['native_video']:
        raise ConfigError('DeepSeek official Chat API has no documented native video_url capability')
    if provider['token_parameter'] not in ('max_tokens', 'max_completion_tokens'):
        raise ConfigError('Unknown completion cap parameter')
    if provider['thinking_style'] not in ('qwen', 'deepseek', 'chat_template', 'none'):
        raise ConfigError('Unknown thinking control style')
    for name in ('auth_required', 'allow_http', 'sampling_verified', 'request_mm_kwargs'):
        if type(provider[name]) is not bool:
            raise ConfigError('Provider flags must be booleans')
    if not isinstance(provider['rates'], dict) or set(provider['rates']) != {'input_per_million', 'output_per_million'}:
        raise ConfigError('Provider rates must explicitly price input and output tokens')
    for name in ('input_per_million', 'output_per_million'):
        money(provider['rates'][name], 'provider.rates.' + name)
    allowed_extra = {'mm_processor_kwargs', 'chat_template_kwargs', 'reasoning_effort', 'top_p', 'top_k', 'repetition_penalty'}
    if not isinstance(provider['extra_body'], dict) or set(provider['extra_body']) - allowed_extra:
        raise ConfigError('extra_body may not override messages, model, streaming, tools or token limits')
    if provider['extra_body'].get('reasoning_effort', 'none') != 'none':
        raise ConfigError('extra_body may not implicitly enable unbudgeted thinking')
    kwargs = provider['extra_body'].get('chat_template_kwargs', {})
    if not isinstance(kwargs, dict) or kwargs.get('enable_thinking', False) is not False:
        raise ConfigError('extra_body may not override the explicit thinking switch')
    if provider['backend'] == 'qwen_compatible' and (provider['extra_body'] or provider['token_parameter'] != 'max_completion_tokens'):
        raise ConfigError('Use Qwen role profiles for controlled parameters; extra_body is reserved for generic adapters')


def read_credentials(path, provider_names):
    # Read-only report/export still work after a private settings file is moved.
    if not Path(path).is_file():
        return {}
    data = read_json(path)
    return {name: data.get('models', {}).get(name, {}).get('api_key', '') for name in provider_names}


class Settings:
    def __init__(self, path=None):
        self.path = Path(path or default_settings_path()).expanduser().resolve()
        code_root = asset('configs/task_registry.json').parent.parent
        if within(self.path, code_root):
            raise ConfigError('Private configuration must be outside the source checkout')
        if not self.path.exists():
            private_write_json(self.path, read_json(asset('configs/terminal.example.json')))
        self.reload()

    def reload(self):
        data = read_json(self.path)
        self.validate(data)
        self.data = data
        return self

    def validate(self, data):
        shape = read_json(asset('configs/terminal.example.json'))
        expected = set(shape)
        if not isinstance(data, dict) or set(data) != expected or data['version'] != 1:
            raise ConfigError('Invalid private terminal settings structure')
        if not isinstance(data['source'], str) or not isinstance(data['output_dir'], str):
            raise ConfigError('source/output_dir must be strings')
        if not isinstance(data['models'], dict) or not data['models'] or not isinstance(data['routes'], dict):
            raise ConfigError('models/routes must be profile dictionaries')
        if not all(isinstance(v, str) for v in data['routes'].values()):
            raise ConfigError('API route values must be model profile names')
        for section in ('limits', 'recipe', 'download'):
            if not isinstance(data[section], dict) or set(data[section]) != set(shape[section]):
                raise ConfigError('Unexpected/missing private settings fields in ' + section)
        for key, value in data['limits'].items():
            money(value, key) if key == 'max_cost_cny' else positive(value, key, integer=True)
        positive(data['download']['max_bytes'], 'download.max_bytes', integer=True)
        positive(data['download']['timeout_seconds'], 'download.timeout_seconds')
        if type(data['download']['allow_http']) is not bool:
            raise ConfigError('download.allow_http must be boolean')
        recipe = data['recipe']
        for key in ('recursive', 'enable_thinking'):
            if type(recipe[key]) is not bool:
                raise ConfigError('recipe.' + key + ' must be boolean')
        for key in ('l1_seconds', 'l2_seconds', 'gate_frame_count', 'max_scan_entries', 'max_frames', 'max_pixels',
                    'total_pixels', 'general_balance_attempts', 'long_balance_attempts', 'max_completion_tokens'):
            positive(recipe[key], 'recipe.' + key, integer=True)
        for key in ('l1_fps', 'l2_fps', 'audit_fps'):
            positive(recipe[key], 'recipe.' + key)
        if recipe['l2_seconds'] % recipe['l1_seconds']:
            raise ConfigError('L2 seconds must be a multiple of L1 seconds')
        positive(recipe['temperature'], 'recipe.temperature', zero=True)
        if recipe['temperature'] > 2:
            raise ConfigError('temperature must be <=2')
        if recipe['enable_thinking'] and recipe['thinking_budget'] is None:
            raise ConfigError('Enabled thinking needs an explicit budget')
        if recipe['thinking_budget'] is not None:
            positive(recipe['thinking_budget'], 'recipe.thinking_budget', integer=True)
        if not isinstance(data['active_model'], str) or data['active_model'] not in data['models'] or set(data['routes']) - set(ROLES):
            raise ConfigError('Unknown active model or API role route')
        for name, entry in data['models'].items():
            from .util import safe_name
            safe_name(name)
            if not isinstance(entry, dict) or not isinstance(entry.get('api_key', ''), str):
                raise ConfigError('Each model profile must have a string api_key')
            if any(ord(c) < 33 or ord(c) > 126 for c in entry.get('api_key', '')):
                raise ConfigError('API key must not contain spaces or control characters')
            self.provider(name, data=data)
        safe_name(recipe['source_name'])
        if any(name not in data['models'] for name in data['routes'].values()):
            raise ConfigError('An API route references an unknown profile')

    def save(self):
        self.validate(self.data)
        private_write_json(self.path, self.data, replace=True)
        self.reload()

    def provider(self, name, *, data=None):
        data = data or self.data
        presets = read_json(asset('configs/provider_presets.json'))
        if name not in data['models']:
            raise ConfigError('Unknown model profile: ' + name)
        overrides = deepcopy(data['models'][name])
        overrides.pop('api_key', None)
        value = merged(presets.get(name, presets['vllm']), overrides)
        validate_public_provider(value)
        return value

    def routes(self):
        return {role: self.data['routes'].get(role) or self.data['active_model'] for role in ROLES}

    def redacted(self):
        value = deepcopy(self.data)
        for entry in value['models'].values():
            if 'api_key' in entry:
                entry['api_key'] = '<configured>' if entry['api_key'] else '<not set>'
        # Signed source URLs are kept only in the private settings file.
        if value['source'].startswith(('http://', 'https://')):
            from .sources import public_url
            value['source'] = public_url(value['source'])
        return value

    def compile(self, run_id, input_root, *, allowlist=None):
        output_base = Path(self.data['output_dir']).expanduser().resolve()
        validate_run_name(run_id)
        run_root = output_base / run_id
        recipe, limits = self.data['recipe'], self.data['limits']
        routes = self.routes()
        providers = {name: self.provider(name) for name in sorted(set(routes.values()))}
        data = template()
        data['schema_version'] = 2
        data['run'].update(id=run_id, output_root=str(output_base), state_root=str(run_root / 'state'), max_videos=limits['max_videos'])
        data['input'].update(root=str(Path(input_root).resolve()), source=recipe['source_name'],
                             recursive=recipe['recursive'], allowlist=allowlist or [], max_scan_entries=recipe['max_scan_entries'])
        data['media'].update(timeout_seconds=300, preset='fast', crf=18, clip_duration_tolerance_seconds=0.2,
                             sample_count=6, sample_width=96, sample_height=64, min_width=64, min_height=64,
                             black_pixel_threshold=8, black_fraction_threshold=0.99, blur_laplacian_threshold=0)
        data['caption'].update(l1_seconds=recipe['l1_seconds'], l2_seconds=recipe['l2_seconds'], gate_frame_count=recipe['gate_frame_count'])
        # Legacy teacher fields remain a recipe container; per-role adapters and
        # limits come from execution.providers, never an inferred API fallback.
        data['teacher'].update(backend='routed', model='routed', provider_max_input_tokens=max(p['provider_max_input_tokens'] for p in providers.values()),
                               timeout_seconds=600, max_video_bytes=max(p['max_video_bytes'] for p in providers.values()),
                               max_payload_bytes=max(p['max_payload_bytes'] for p in providers.values()), max_response_bytes=4194304)
        for role, profile in data['teacher']['roles'].items():
            provider = providers[routes[role]]
            visual = profile['mode'] != 'text'
            profile.update(input_token_limit=provider['provider_max_input_tokens'] if visual else min(131072, provider['provider_max_input_tokens']),
                           visual_token_reserve=min(8192, provider['provider_max_input_tokens'] // 4) if visual else 0,
                           context_overhead_tokens=1024, max_completion_tokens=recipe['max_completion_tokens'],
                           enable_thinking=recipe['enable_thinking'], thinking_budget=recipe['thinking_budget'], temperature=recipe['temperature'])
            if profile['mode'] == 'native_video':
                profile.update(fps=recipe['l1_fps'] if role == 'A1' else recipe['l2_fps'] if role == 'A2' else recipe['audit_fps'],
                               max_frames=recipe['max_frames'], max_pixels=recipe['max_pixels'], total_pixels=recipe['total_pixels'],
                               min_video_seconds=2, sampling_capability_verified=provider['sampling_verified'])
            elif profile['mode'] == 'ordered_images':
                profile.update(max_frames=recipe['gate_frame_count'], max_pixels=recipe['max_pixels'])
        data['budgets'].update(max_cost=limits['max_cost_cny'], **{key: limits[key] for key in
                              ('max_requests', 'per_video_max_requests', 'max_aux_requests', 'max_upload_bytes')},
                              input_per_million='0', output_per_million='0')
        data['generation'].update(general_balance_attempts=recipe['general_balance_attempts'],
                                  long_balance_attempts=recipe['long_balance_attempts'], templates_per_slot=2)
        data['execution'] = {'layout': 'contained', 'credential_file': str(self.path), 'providers': providers, 'routes': routes}
        validate_config(data)
        credentials = read_credentials(self.path, providers)
        return RuntimeConfig(data, run_root / 'runtime.json', credentials)

    def build_id(self, name, *, now=None):
        validate_run_name(name)
        return name + '_' + (now or datetime.now().astimezone()).strftime('%Y%m%d_%H%M')
