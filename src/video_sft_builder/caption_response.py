"""One narrowly scoped, lossless caption JSON normalization; all else is strict."""
import json

from .util import digest


class CaptionResponse(dict):
    pass


def decode_caption(text):
    changes = []

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                if key != 'uncertain_details' or not all(isinstance(v, list) and
                        all(isinstance(s, str) for s in v) for v in (result[key], value)):
                    raise ValueError('Duplicate JSON key')
                result[key] = list(dict.fromkeys(result[key] + value))
                changes.append({'field': key, 'operation': 'stable_union_string_arrays'})
            else:
                result[key] = value
        return result

    def invalid(_):
        raise ValueError('Non-finite JSON number')

    value = json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)
    if not isinstance(value, dict) or set(value) != {'description', 'uncertain_details'}:
        raise ValueError('Caption fields do not match the protocol')
    if not isinstance(value['description'], str) or not value['description'].strip():
        raise ValueError('Empty caption')
    if not isinstance(value['uncertain_details'], list) or not all(isinstance(s, str) for s in value['uncertain_details']):
        raise ValueError('Invalid caption uncertainty array')
    result = CaptionResponse(value)
    result.normalization = {'operations': changes, 'raw_content_hash': digest(text)} if changes else None
    return result
