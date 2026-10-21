from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import cached_property
import json
import math
import os
from pathlib import Path
from urllib.parse import urlsplit

from .errors import ConfigError
from .util import asset, digest, file_digest, read_json, safe_name, within

ROLES = ('A1', 'A2', 'C_GATE', 'A3', 'A5', 'A7')


def positive(value, name, *, integer=False, zero=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ConfigError(name + ' must be an explicit finite number')
    if value < 0 or (not zero and value == 0) or (integer and int(value) != value):
        raise ConfigError(name + ' has an invalid range')
    return value


def money(value, name):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0:
            raise InvalidOperation
        return number
    except InvalidOperation:
        raise ConfigError(name + ' must be a nonnegative decimal amount') from None


def https_endpoint(value, name):
    parsed = urlsplit(value or '')
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ConfigError(name + ' must be HTTPS without credentials, query or fragment')


@dataclass(frozen=True)
class RuntimeConfig:
    data: dict
    path: Path

    @property
    def run_id(self):
        return self.data['run']['id']

    @property
    def output(self):
        return Path(self.data['run']['output_root']) / self.run_id

    @property
    def state_dir(self):
        return Path(self.data['run']['state_root']) / self.run_id

    @cached_property
    def fingerprint(self):
        return digest([self.data, self.code_and_asset_identity])

    @cached_property
    def code_and_asset_identity(self):
        package = Path(__file__).parent
        code = {p.name: file_digest(p) for p in sorted(package.glob('*.py'))}
        resources = ['configs/task_registry.json', 'configs/question_templates.json',
                     'prompts/task_scheduler/generation.system.en.txt']
        resources += ['prompts/runtime/' + name + '.txt' for name in ('caption', 'caption_gate', 'audit')]
        return {'code': code, 'assets': {name: file_digest(asset(name)) for name in resources}}

    def profile(self, role):
        return self.data['teacher']['roles'][role]

    def source_for(self, relative_path):
        from pathlib import PurePosixPath
        path = PurePosixPath(relative_path)
        mapping = self.data['input'].get('source_by_prefix', {})
        matches = [prefix for prefix in mapping if path.is_relative_to(PurePosixPath(prefix))]
        return mapping[max(matches, key=lambda p: len(PurePosixPath(p).parts))] if matches else self.data['input']['source']


def load_config(path, *, allow_synthetic=False):
    data = read_json(path)
    validate_config(data, allow_synthetic=allow_synthetic)
    return RuntimeConfig(data, Path(path).resolve())


def validate_config(data, *, allow_synthetic=False):
    if not isinstance(data, dict):
        raise ConfigError('Runtime configuration must be a JSON object')
    if data.get('schema_version') != 1:
        raise ConfigError('Expected runtime schema_version=1; design project.example.json is not executable')
    expected = {'schema_version', 'run', 'input', 'media', 'caption', 'teacher', 'budgets', 'generation'}
    if set(data) != expected:
        raise ConfigError('Unexpected/missing runtime top-level sections: ' + str(set(data) ^ expected))
    shape = template()
    for section in sorted(expected - {'schema_version'}):
        value = data[section]
        if not isinstance(value, dict) or set(value) != set(shape[section]):
            raise ConfigError('Unexpected/missing configuration fields in ' + section)
    run, source = data['run'], data['input']
    safe_name(run['id'])
    safe_name(source['source'])
    for key in ('output_root', 'state_root'):
        if not run.get(key) or not Path(run[key]).is_absolute():
            raise ConfigError('run.' + key + ' must be an absolute external path')
    if not source.get('root') or not Path(source['root']).is_absolute():
        raise ConfigError('input.root must be absolute')
    roots = [Path(source['root']).resolve(), Path(run['output_root']).resolve(), Path(run['state_root']).resolve()]
    checkout = asset('configs/task_registry.json').parent.parent
    for root in roots:
        if within(root, checkout):
            raise ConfigError('Media, outputs and runtime state must stay outside the code checkout')
    for index, left in enumerate(roots):
        for right in roots[index + 1:]:
            if left == right or within(left, right) or within(right, left):
                raise ConfigError('Input, output and state roots must be disjoint')
    if not isinstance(source.get('recursive'), bool):
        raise ConfigError('input.recursive must explicitly be true or false')
    if not isinstance(source.get('allowlist'), list) or any(not isinstance(p, str) or not p for p in source['allowlist']):
        raise ConfigError('input.allowlist must be a list of relative MP4 paths')
    mapping = source.get('source_by_prefix', {})
    if not isinstance(mapping, dict):
        raise ConfigError('input.source_by_prefix must map relative paths to source names')
    for prefix, name in mapping.items():
        from pathlib import PurePosixPath
        parsed = PurePosixPath(prefix)
        if not prefix or parsed.is_absolute() or '..' in parsed.parts or '\\' in prefix or ':' in prefix:
            raise ConfigError('Invalid relative source prefix')
        safe_name(name)
    positive(run['max_videos'], 'run.max_videos', integer=True)
    positive(source['max_scan_entries'], 'input.max_scan_entries', integer=True)
    if not isinstance(run.get('seed'), int) or isinstance(run['seed'], bool):
        raise ConfigError('run.seed must be an integer')
    media = data['media']
    for key in ('ffmpeg', 'ffprobe', 'codec', 'preset'):
        if not isinstance(media.get(key), str) or not media[key] or media[key].startswith('-'):
            raise ConfigError('media.' + key + ' must be explicit')
    for key in ('timeout_seconds', 'sample_count', 'sample_width', 'sample_height'):
        positive(media[key], 'media.' + key, integer=True)
    if media['sample_count'] > 64 or media['sample_width'] > 256 or media['sample_height'] > 256:
        raise ConfigError('Pre-clean samples exceed bounded v1 IO limits')
    if min(media['sample_width'], media['sample_height']) < 16:
        raise ConfigError('Pre-clean sample dimensions must be at least 16')
    positive(media['clip_duration_tolerance_seconds'], 'clip duration tolerance')
    if not isinstance(media['crf'], int) or not 0 <= media['crf'] <= 51:
        raise ConfigError('media.crf must be in 0..51')
    for key in ('min_width', 'min_height'):
        positive(media[key], key, integer=True)
    for key in ('black_pixel_threshold', 'black_fraction_threshold', 'blur_laplacian_threshold'):
        positive(media[key], key, zero=True)
    if media['black_pixel_threshold'] > 255 or not 0 <= media['black_fraction_threshold'] <= 1:
        raise ConfigError('Invalid black-frame thresholds')
    if media['perceptual_duplicate_hamming'] is not None:
        positive(media['perceptual_duplicate_hamming'], 'perceptual duplicate threshold', integer=True, zero=True)
        if media['perceptual_duplicate_hamming'] > 64:
            raise ConfigError('Perceptual duplicate Hamming threshold must be <=64')
    caption = data['caption']
    for key in ('l1_seconds', 'l2_seconds', 'gate_frame_count'):
        positive(caption[key], 'caption.' + key, integer=True)
    if caption['l2_seconds'] % caption['l1_seconds']:
        raise ConfigError('L2 block length must be a multiple of L1 window length')
    teacher = data['teacher']
    backend = teacher.get('backend')
    if backend not in ('qwen_compatible', 'synthetic') or (backend == 'synthetic' and not allow_synthetic):
        raise ConfigError('Production requires qwen_compatible; synthetic is available only to demo/tests')
    if teacher.get('automatic_retries') != 0:
        raise ConfigError('All inference automatic retries must be zero')
    if backend != 'synthetic':
        https_endpoint(teacher['base_url'], 'teacher.base_url')
        https_endpoint(teacher['upload_policy_url'], 'teacher.upload_policy_url')
        if not isinstance(teacher.get('model'), str) or not teacher['model']:
            raise ConfigError('teacher.model must be explicit')
        safe_name(teacher['key_env'])
        if teacher['transport'] not in ('dashscope_oss', 'base64'):
            raise ConfigError('Unsupported teacher.transport')
        if not teacher.get('billing_bounds_verified'):
            raise ConfigError('Confirm provider billing/context bounds before live execution')
    positive(teacher['timeout_seconds'], 'teacher.timeout_seconds')
    positive(teacher['provider_max_input_tokens'], 'teacher.provider_max_input_tokens', integer=True)
    for key in ('max_video_bytes', 'max_payload_bytes', 'max_response_bytes'):
        positive(teacher[key], key, integer=True)
    if set(teacher['roles']) != set(ROLES):
        raise ConfigError('teacher.roles must configure exactly A1/A2/C_GATE/A3/A5/A7')
    for role in ROLES:
        profile = teacher['roles'][role]
        if not isinstance(profile, dict) or set(profile) != set(shape['teacher']['roles'][role]):
            raise ConfigError('Unexpected/missing profile fields for ' + role)
        if profile['mode'] != ('ordered_images' if role == 'C_GATE' else 'text' if role in ('A3', 'A5') else 'native_video'):
            raise ConfigError('Unexpected input mode for ' + role)
        for key in ('input_token_limit', 'visual_token_reserve', 'context_overhead_tokens', 'max_completion_tokens'):
            positive(profile[key], role + '.' + key, integer=True, zero=key in ('visual_token_reserve', 'context_overhead_tokens'))
        if not isinstance(profile['enable_thinking'], bool):
            raise ConfigError(role + '.enable_thinking must be explicit')
        if profile['thinking_budget'] is not None:
            positive(profile['thinking_budget'], role + '.thinking_budget', integer=True, zero=True)
        if profile['enable_thinking'] and profile['thinking_budget'] is None:
            raise ConfigError('Enabled thinking requires an explicit thinking_budget')
        positive(profile['temperature'], role + '.temperature', zero=True)
        if profile['temperature'] > 2:
            raise ConfigError(role + '.temperature must be <=2')
        if profile['mode'] == 'text' and profile['visual_token_reserve'] != 0:
            raise ConfigError('Text-only role must have zero visual reservation')
        if profile['input_token_limit'] > teacher['provider_max_input_tokens']:
            raise ConfigError('Role input budget exceeds the provider context ceiling')
        if profile['mode'] != 'text' and profile['input_token_limit'] != teacher['provider_max_input_tokens']:
            raise ConfigError('Visual roles reserve the full verified provider input ceiling, not a guessed token estimate')
        if profile['mode'] == 'ordered_images':
            positive(profile['max_frames'], role + '.max_frames', integer=True)
            positive(profile['max_pixels'], role + '.max_pixels', integer=True)
        if profile['mode'] == 'native_video':
            for key in ('fps', 'max_frames', 'max_pixels', 'total_pixels', 'min_video_seconds'):
                positive(profile[key], role + '.' + key, integer=key in ('max_frames', 'max_pixels', 'total_pixels'))
            if profile.get('sampling_capability_verified') is not True:
                raise ConfigError(role + ' native-video sampling capability is not confirmed')
    budgets = data['budgets']
    if budgets['currency'] != 'CNY':
        raise ConfigError('v1 budget ledger is denominated in CNY')
    for key in ('max_cost', 'input_per_million', 'output_per_million'):
        money(budgets[key], 'budgets.' + key)
    for key in ('max_requests', 'per_video_max_requests', 'max_aux_requests', 'max_upload_bytes'):
        positive(budgets[key], 'budgets.' + key, integer=True)
    generation = data['generation']
    for key in ('general_balance_attempts', 'long_balance_attempts', 'templates_per_slot'):
        positive(generation[key], 'generation.' + key, integer=True)
    if generation['templates_per_slot'] > 8:
        raise ConfigError('At most 8 template candidates per slot')
    if generation.get('cot_enabled') is not False or generation.get('refill_rejected') is not False:
        raise ConfigError('CoT and rejected-QA refilling are outside the current pipeline')


def template():
    return read_json(asset('configs/runtime.example.json'))
