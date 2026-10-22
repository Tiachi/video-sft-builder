"""Select equivalent passthrough options from the installed FFmpeg's capabilities."""
import re

from .errors import PipelineError


def passthrough_args(help_output):
    """Use modern per-stream mode, or FFmpeg 4.x's timestamp-preserving mode.

    Inspect option declarations, not a version string or arbitrary mention of an
    option in prose. Never fall back to CFR or the muxer's automatic sync mode.
    """
    text = help_output.decode(errors='replace') if isinstance(help_output, bytes) else help_output
    if re.search(r'(?m)^\s*-fps_mode\b', text):
        return ('-fps_mode', 'passthrough')
    if re.search(r'(?m)^\s*-vsync\b', text):
        return ('-vsync', '0')
    raise PipelineError('FFmpeg exposes neither -fps_mode nor -vsync; cannot guarantee passthrough timing')
