"""Single-send Qwen-compatible HTTP transport and bounded temporary OSS upload.

Provider URLs, policies and authorization headers are never written to reports.
No SDK, HTTP adapter or proxy retry loop is installed by this module.
"""
import base64
from decimal import Decimal
import http.client
import json
import math
import mimetypes
import os
from pathlib import Path
from pathlib import PurePosixPath
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .errors import Blocked, ConfigError, PipelineError, ProtocolError, UnknownExecution
from .caption_response import decode_caption
from .util import canonical, digest, file_digest, strict_json


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_json(url, *, headers, body=None, timeout=600, limit=4_000_000):
    request = urllib.request.Request(url, data=body, headers=headers, method='POST' if body is not None else 'GET')
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            value = response.read(limit + 1)
            if len(value) > limit:
                raise ProtocolError('API response exceeded configured byte limit')
            return strict_json(value)
    except urllib.error.HTTPError as error:
        raise PipelineError('HTTP service returned status ' + str(error.code)) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise UnknownExecution('Network request failed or timed out; execution status unknown') from None
    except (ValueError, UnicodeError):
        raise ProtocolError('Service did not return valid JSON') from None


class QwenCompatibleProvider:
    synthetic = False

    def __init__(self, config, store, *, settings=None, api_key=None):
        self.config, self.store = config, store
        self.settings = settings or config.data['teacher']
        self.key = api_key or os.environ.get(self.settings['key_env']) or ''
        if not self.key and self.settings.get('auth_required', True):
            raise ConfigError('API credential environment variable is missing; no request sent')
        if any(ord(c) < 32 for c in self.key):
            raise ConfigError('Invalid control character in configured API credential')
        self._json = http_json  # injectable in offline transport tests

    def materialize(self, path, *, media_type):
        path = Path(path)
        if not path.is_file() or path.stat().st_size > self.settings['max_video_bytes']:
            raise Blocked('media_file_size_limit')
        mime = mimetypes.guess_type(path.name)[0] or ('video/mp4' if media_type == 'video' else 'image/jpeg')
        if self.settings['transport'] == 'base64':
            encoded_size = 4 * ((path.stat().st_size + 2) // 3)
            if encoded_size > self.settings['max_payload_bytes'] // 2:
                raise Blocked('base64_media_payload_limit_use_oss_transport')
            return 'data:' + mime + ';base64,' + base64.b64encode(path.read_bytes()).decode('ascii')
        checksum = file_digest(path)
        cache_key = digest([self.settings['model'], self.settings['base_url'], checksum,
                            digest(self.key)])
        cached = self.store.cache(cache_key)
        if cached and cached['expires'] > time.time() + 300:
            return cached['resource']
        aid = self.store.auxiliary('upload_policy')
        query = urllib.parse.urlencode({'action': 'getPolicy', 'model': self.settings['model']})
        policy = self._json(self.settings['upload_policy_url'] + '?' + query,
                            headers={'Authorization': 'Bearer ' + self.key, 'Accept': 'application/json'},
                            timeout=self.settings['timeout_seconds'], limit=1_000_000).get('data')
        self.store.auxiliary_done(aid)
        required = {'upload_dir', 'upload_host', 'max_file_size_mb', 'policy', 'signature', 'oss_access_key_id',
                    'x_oss_object_acl', 'x_oss_forbid_overwrite'}
        if not isinstance(policy, dict) or not required <= set(policy):
            raise ProtocolError('Upload policy schema mismatch')
        if path.stat().st_size > float(policy['max_file_size_mb']) * 1024 * 1024:
            raise Blocked('provider_upload_policy_file_size_limit')
        if policy['x_oss_object_acl'] != 'private' or str(policy['x_oss_forbid_overwrite']).lower() != 'true':
            raise ProtocolError('Refusing a non-private or overwriting upload policy')
        parsed = urllib.parse.urlsplit(policy['upload_host'])
        if (parsed.scheme != 'https' or not parsed.hostname or not parsed.hostname.endswith('.aliyuncs.com')
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ProtocolError('Unexpected upload host')
        key = policy['upload_dir'].rstrip('/') + '/' + checksum + '_' + uuid.uuid4().hex + path.suffix.lower()
        fields = {'OSSAccessKeyId': policy['oss_access_key_id'], 'Signature': policy['signature'],
                  'policy': policy['policy'], 'key': key, 'x-oss-object-acl': 'private',
                  'x-oss-forbid-overwrite': 'true', 'success_action_status': '200', 'x-oss-content-type': mime}
        self._upload(parsed, fields, path, mime)
        resource = 'oss://' + key
        # Provider documentation gives media URLs 48h; use a conservative 47h cache.
        self.store.cache(cache_key, resource=resource, expires=time.time() + 47 * 3600)
        return resource

    def _upload(self, parsed, fields, path, mime):
        boundary = 'vsft' + uuid.uuid4().hex
        prefix = b''
        for name, value in fields.items():
            prefix += (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n').encode()
        prefix += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="media{path.suffix}"\r\n'
                   f'Content-Type: {mime}\r\n\r\n').encode()
        suffix = f'\r\n--{boundary}--\r\n'.encode()
        length = len(prefix) + path.stat().st_size + len(suffix)
        aid = self.store.auxiliary('oss_upload', path.stat().st_size)
        connection = http.client.HTTPSConnection(parsed.hostname, parsed.port,
                                                timeout=self.settings['timeout_seconds'])
        try:
            connection.putrequest('POST', parsed.path or '/')
            connection.putheader('Content-Type', 'multipart/form-data; boundary=' + boundary)
            connection.putheader('Content-Length', str(length))
            connection.endheaders()
            connection.send(prefix)
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    connection.send(chunk)
            connection.send(suffix)
            response = connection.getresponse()
            response.read(65536)
            if response.status != 200:
                raise PipelineError('OSS upload failed with status ' + str(response.status))
            self.store.auxiliary_done(aid)
        except (OSError, TimeoutError, http.client.HTTPException):
            raise PipelineError('Media upload failed; no inference request was sent') from None
        finally:
            connection.close()

    def build_body(self, role, system, context, media, profile):
        content = [{'type': 'text', 'text': canonical(context)}]
        for item in media:
            resource = self.materialize(item['path'], media_type=item['type'])
            if item['type'] == 'video':
                content.append({'type': 'video_url', 'video_url': {'url': resource}, 'fps': profile['fps'],
                                'max_pixels': profile['max_pixels'], 'total_pixels': profile['total_pixels']})
            else:
                content.extend([{'type': 'text', 'text': canonical({'frame_id': item['id'], 'original_seconds': item['time']})},
                                {'type': 'image_url', 'image_url': {'url': resource}, 'max_pixels': profile['max_pixels']}])
        body = {'model': self.settings['model'],
                'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': content}],
                'stream': False, 'response_format': {'type': 'json_object'},
                'max_completion_tokens': profile['max_completion_tokens'],
                'temperature': profile['temperature'], 'enable_thinking': profile['enable_thinking'],
                'vl_high_resolution_images': False}
        if profile['enable_thinking']:
            body['thinking_budget'] = profile['thinking_budget']
        return body

    def send(self, body):
        headers = {'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json',
                   'X-DashScope-OssResourceResolve': 'enable'}
        return self._json(self.settings['base_url'].rstrip('/') + '/chat/completions', headers=headers,
                          body=canonical(body).encode(), timeout=self.settings['timeout_seconds'],
                          limit=self.settings['max_response_bytes'])


class CompatibleProvider(QwenCompatibleProvider):
    """DeepSeek and vLLM dialects; never send DashScope-specific fields here."""

    def materialize(self, path, *, media_type):
        if self.settings['transport'] != 'file_uri':
            return super().materialize(path, media_type=media_type)
        if self.settings['backend'] != 'vllm':
            raise ConfigError('Shared file references are restricted to vLLM')
        local = self.settings['local_media_root']
        remote = self.settings['server_media_root']
        if not local or not Path(local).is_absolute() or not remote.startswith('/'):
            raise ConfigError('file_uri needs explicit local_media_root and absolute server_media_root')
        value = Path(path).resolve()
        try:
            relative = value.relative_to(Path(local).resolve())
        except ValueError:
            raise Blocked('media_outside_vllm_shared_root') from None
        if not value.is_file() or value.stat().st_size > self.settings['max_video_bytes']:
            raise Blocked('media_file_size_limit')
        mapped = PurePosixPath(remote).joinpath(*relative.parts)
        return 'file://' + urllib.parse.quote(str(mapped), safe='/')

    def build_body(self, role, system, context, media, profile):
        backend = self.settings['backend']
        if profile['enable_thinking']:
            raise ConfigError('This adapter cannot enforce a separate thinking_budget; disable thinking for now')
        content = [{'type': 'text', 'text': canonical(context)}]
        for item in media:
            if item['type'] == 'video' and (backend == 'deepseek' or not self.settings['capabilities']['native_video']):
                raise ConfigError('Selected endpoint does not accept native video_url input')
            resource = self.materialize(item['path'], media_type=item['type'])
            if item['type'] == 'video':
                content.append({'type': 'video_url', 'video_url': {'url': resource}})
            else:
                content.extend([{'type': 'text', 'text': canonical({'frame_id': item['id'], 'original_seconds': item['time']})},
                                {'type': 'image_url', 'image_url': {'url': resource}}])
        body = {'model': self.settings['model'], 'messages': [
                    {'role': 'system', 'content': system},
                    {'role': 'user', 'content': content if media else canonical(context)}],
                'stream': False, 'response_format': {'type': 'json_object'},
                self.settings['token_parameter']: profile['max_completion_tokens'], 'temperature': profile['temperature']}
        style = self.settings['thinking_style']
        if style == 'deepseek':
            body['thinking'] = {'type': 'disabled'}
        elif style == 'chat_template':
            body['chat_template_kwargs'] = {'enable_thinking': False}
        for key, value in self.settings['extra_body'].items():
            if key in ('chat_template_kwargs',):
                body.setdefault(key, {}).update(value)
            else:
                body[key] = value
        if media and any(i['type'] == 'video' for i in media) and backend == 'vllm' and self.settings['request_mm_kwargs']:
            duration = max(i['end'] - i['start'] for i in media if i['type'] == 'video')
            # Explicitly cover the whole supplied video; never inherit vLLM's
            # default 300-second decode limit or an arbitrary 32-frame cap.
            body['media_io_kwargs'] = {'video': {'fps': profile['fps'],
                'num_frames': math.ceil(duration * profile['fps']) + 1, 'max_duration': math.ceil(duration) + 1}}
        return body

    def send(self, body):
        headers = {'Content-Type': 'application/json'}
        if self.key:
            headers['Authorization'] = 'Bearer ' + self.key
        return self._json(self.settings['base_url'].rstrip('/') + '/chat/completions', headers=headers,
                          body=canonical(body).encode(), timeout=self.settings['timeout_seconds'],
                          limit=self.settings['max_response_bytes'])


class ProviderRouter:
    def __init__(self, config, store):
        self.config, self.store, self.clients = config, store, {}

    def client(self, role):
        name = self.config.provider_id(role)
        if name not in self.clients:
            settings = self.config.provider_settings(role)
            cls = QwenCompatibleProvider if settings['backend'] == 'qwen_compatible' else CompatibleProvider
            self.clients[name] = cls(self.config, self.store, settings=settings,
                                     api_key=self.config.credentials.get(name))
        return self.clients[name]


class ModelGateway:
    def __init__(self, config, store, provider):
        self.config, self.store, self.provider = config, store, provider

    def call(self, role, unit_id, video, system, context, media=None):
        media = media or []
        profile = self.config.profile(role)
        request_id = digest([self.config.fingerprint, video['id'], role, unit_id, system, context,
                             [{k: v for k, v in item.items() if k != 'path'} for item in media]])
        existing = self.store.request(request_id)
        if existing and existing['status'] == 'done':
            return self._parsed(existing['response'], role, request_id, video), request_id
        recovered = self._recovered(role, video, system, context, media, profile)
        if recovered:
            return recovered
        text_bound = len((system + canonical(context)).encode()) + profile['context_overhead_tokens']
        # This deliberately overestimates Qwen text via UTF-8 bytes. Visual input
        # is separately reserved at a configured, capability-verified bound.
        if text_bound + profile['visual_token_reserve'] > profile['input_token_limit']:
            raise Blocked('input_context_budget_exceeded')
        if role in ('A1', 'A2', 'A7'):
            if len(media) != 1 or media[0]['type'] != 'video':
                raise ProtocolError(role + ' requires one native video file')
            duration = media[0]['end'] - media[0]['start']
            if duration < profile['min_video_seconds']:
                raise Blocked('native_video_segment_below_provider_minimum')
            provider_settings = self.config.provider_settings(role)
            margin = 1 if provider_settings.get('backend') == 'vllm' and provider_settings.get('request_mm_kwargs') else 0
            if duration * profile['fps'] + margin > profile['max_frames'] or video['fps'] < profile['fps']:
                raise Blocked('fixed_fps_cannot_be_preserved')
        elif role == 'C_GATE' and (not media or len(media) > profile['max_frames']):
            raise Blocked('caption_gate_frame_limit')
        prices = self.config.prices(role)
        reservation = (Decimal(profile['input_token_limit']) * Decimal(str(prices['input_per_million']))
                       + Decimal(profile['max_completion_tokens'] + 10) * Decimal(str(prices['output_per_million']))) / 1_000_000
        if self.provider is None:
            self.provider = ProviderRouter(self.config, self.store) if self.config.data['schema_version'] == 2 else QwenCompatibleProvider(self.config, self.store)
        adapter = self.provider.client(role) if isinstance(self.provider, ProviderRouter) else self.provider
        self.store.reserve(request_id, video['id'], role, reservation)
        self.store.put('request_view:' + request_id, 'request_view', video['id'],
                       {'request_id': request_id, 'role': role, 'provider_id': self.config.provider_id(role), 'profile': profile,
                          'branch':context.get('branch') or context.get('candidate',{}).get('branch'),
                          'unit_id':unit_id,
                        'system_hash': digest(system), 'context_hash': digest(context),
                        'media': media, 'provider_effective_sampling': None,
                        'observability': 'requested_view_only_native_preprocessing_unobserved'})
        self.store.notify('api_wait', role=role, unit_id=unit_id, video_id=video['id'],
                          model=self.config.provider_settings(role)['model'])
        try:
            body = adapter.build_body(role, system, context, media, profile)
            if len(canonical(body).encode()) > self.config.provider_settings(role)['max_payload_bytes']:
                raise Blocked('http_request_payload_limit')
        except Blocked:
            # No inference sent; this reserved slot remains conservative and resumable.
            raise
        self.store.sent(request_id)
        try:
            raw = adapter.send(body)
        except BaseException as error:
            self.store.fail(request_id, type(error).__name__, uncertain=True)
            raise UnknownExecution('Inference may have executed; refusing automatic retry') from None
        usage = raw.get('usage', {}) if isinstance(raw, dict) else {}
        normalized = {'input_tokens': usage.get('prompt_tokens'), 'output_tokens': usage.get('completion_tokens')}
        if 'completion_tokens_details' in usage:
            normalized['completion_tokens_details'] = usage['completion_tokens_details']
        self.store.complete(request_id, raw, normalized)
        return self._parsed(raw, role, request_id, video), request_id

    def _parsed(self, raw, role, request_id, video):
        value = self._decode(raw, role=role)
        normalization = getattr(value, 'normalization', None)
        if normalization:
            self.store.put('response_normalization:' + request_id, 'response_normalization', video['id'],
                           {'request_id': request_id, **normalization})
            self.store.notify('response_normalized', role=role, request_id=request_id,
                              operation='uncertain_details_union')
        return value

    def _recovered(self, role, video, system, context, media, profile):
        if role not in ('A1', 'A2'):
            return None
        for entry in self.store.records('recovered_request', video['id']):
            item = entry['payload']
            view = item['view']
            if (item['video_sha256'] == video['sha256'] and view['role'] == role
                    and view['profile'] == profile and view['system_hash'] == digest(system)
                    and view['context_hash'] == digest(context)
                    and view['provider_id'] == self.config.provider_id(role)
                    and [{k: v for k, v in m.items() if k != 'path'} for m in view['media']]
                        == [{k: v for k, v in m.items() if k != 'path'} for m in media]):
                prior = self.store.request(item['request_id'])
                if not prior or prior['status'] != 'done':
                    raise ProtocolError('Recovery ledger mismatch')
                self.store.notify('cache_reused', role=role, request_id=item['request_id'])
                return self._parsed(prior['response'], role, item['request_id'], video), item['request_id']
        # A changed window/context cannot silently turn a paid unit into a
        # second charge. An explicit new independent run remains available.
        if any(e['payload']['view']['role'] == role and
               any(m.get('id') == n.get('id') for m in e['payload']['view']['media'] for n in media)
               for e in self.store.records('recovered_request', video['id'])):
            raise Blocked('recovered_caption_context_or_window_changed_no_automatic_rebill')
        return None

    @staticmethod
    def _decode(raw, *, role=None):
        try:
            choice = raw['choices'][0]
            if choice['finish_reason'] != 'stop':
                raise ProtocolError('Incomplete/refused model response; no repair or continuation')
            text = choice['message']['content']
            value = decode_caption(text) if role in ('A1', 'A2') else strict_json(text)
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except ValueError as error:
            if str(error) == 'Duplicate JSON key':
                raise ProtocolError('caption_duplicate_field_conflict' if role in ('A1', 'A2') else 'model_duplicate_json_key') from None
            raise ProtocolError('Model response did not satisfy the JSON object protocol') from None
        except (KeyError, IndexError, TypeError):
            raise ProtocolError('Model response did not satisfy the JSON object protocol') from None
