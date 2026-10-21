#!/usr/bin/env python3
"""Offline scenario arithmetic, not a production configuration or billing tool.

Reads no media, credentials or runtime config; sends no requests; writes stdout only.
Prices checked 2026-10-21: Alibaba Model Studio Beijing qwen3.8-flash,
CNY 0.8/M input and 2.7/M output, without cache/free-tier/batch discounts.
See docs/qwen38_flash_one_hour_cost_estimate_2026-10-21.md for assumptions.
"""

from dataclasses import dataclass, replace
from decimal import Decimal
import math


INPUT_PRICE = Decimal('0.8')
OUTPUT_PRICE = Decimal('2.7')
MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class Stage:
    name: str
    calls: int
    frames_each: int
    text_each: int
    output_each: int


STAGES = (
    Stage('A1-L1', 360, 10, 6000, 300),
    Stage('A2-L2', 120, 30, 6000, 4000),
    Stage('L3-reuse', 0, 0, 0, 0),
    Stage('C_GATE', 1, 128, 10000, 2000),
    Stage('A3-fit', 1, 0, 128000, 1800),
    Stage('A3-balance', 3, 0, 128000, 900),
    Stage('A5-fit', 1, 0, 128000, 1400),
    Stage('A5-balance', 2, 0, 128000, 1400),
    Stage('A7', 8, 256, 2000, 1000),
)


def calculate(stage: Stage, image_tokens: int) -> tuple[int, int, int, Decimal]:
    vision = stage.calls * stage.frames_each * image_tokens
    text = stage.calls * stage.text_each
    output = stage.calls * stage.output_each
    cost = ((vision + text) * INPUT_PRICE + output * OUTPUT_PRICE) / MILLION
    return vision, text, output, cost


def total(stages: tuple[Stage, ...], image_tokens: int) -> Decimal:
    return sum((calculate(s, image_tokens)[3] for s in stages), Decimal(0))


def short_video_estimate(frame_count: int, max_pixels: int) -> tuple[int, int, int]:
    """1080p, 1/2-FPS short-clip scenarios; API caps + example resize.

    Qwen3.8-Flash API reference: default max_pixels=655360,
    total_pixels=819200000. Width/height snapping and pair-token estimate
    follow the official vision example, not a verified server trace.
    """
    if frame_count not in (10, 20, 30, 60) or not 65536 <= max_pixels <= 2048000:
        raise ValueError('Only the documented short-clip estimation scenarios are supported')
    width, height, factor = 1920, 1080, 32
    pixel_cap = min(max_pixels, 819200000 // frame_count)
    resized_width = round(width / factor) * factor
    resized_height = round(height / factor) * factor
    if resized_width * resized_height > pixel_cap:
        beta = math.sqrt(width * height / pixel_cap)
        resized_width = math.floor(width / beta / factor) * factor
        resized_height = math.floor(height / beta / factor) * factor
    tokens = math.ceil(frame_count / 2) * resized_width * resized_height // 1024 + 2
    return resized_width, resized_height, tokens


def video_2fps_rows(max_pixels: int = 655360) -> tuple[tuple, ...]:
    """Historical comparison: L1/L2 native, with the old image-based A7."""
    rows = []
    for stage in STAGES:
        vision, text, output, cost = calculate(stage, 2042)
        if stage.name in ('A1-L1', 'A2-L2'):
            _, _, clip_tokens = short_video_estimate(stage.frames_each * 2, max_pixels)
            vision = stage.calls * clip_tokens
            cost = ((vision + text) * INPUT_PRICE + output * OUTPUT_PRICE) / MILLION
        rows.append((stage.name, stage.calls, vision, text, output, cost))
    return tuple(rows)


def native_audit_usage_scenario(vision_tokens_each: int) -> tuple[Decimal, Decimal, Decimal]:
    """Explicit token-usage scenario, not a native-video preprocessing prediction.

    A7 now receives the original video plus text. No 256-image assumption.
    Preserve the hypothetical 2000 text / 1000 visible output tokens per audit.
    """
    if vision_tokens_each < 0:
        raise ValueError('Visual token count cannot be negative')
    per_question = ((vision_tokens_each + 2000) * INPUT_PRICE + 1000 * OUTPUT_PRICE) / MILLION
    other_stages = sum((r[5] for r in video_2fps_rows() if r[0] != 'A7'), Decimal(0))
    return per_question, per_question * 8, other_stages + per_question * 8


def main() -> None:
    # Image mode: round dimensions to multiples of 32, then area / 1024 + 2.
    # 1920x1080 -> 1920x1088; alternative 1280x720 -> 1280x704.
    full_hd_tokens = 1920 * 1088 // 1024 + 2
    hd_tokens = 1280 * 704 // 1024 + 2
    print('HISTORICAL IMAGE SCENARIO ONLY; A7 now uses native video plus text; no API/media IO')
    print('stage,calls,frames,vision_tokens,text_tokens,output_tokens,cost_CNY,cost_plus4096_thinking_CNY')
    for stage in STAGES:
        vision, text, output, cost = calculate(stage, full_hd_tokens)
        thought_cost = stage.calls * 4096 * OUTPUT_PRICE / MILLION
        print(f'{stage.name},{stage.calls},{stage.calls * stage.frames_each},'
              f'{vision},{text},{output},{cost:.7f},{cost + thought_cost:.7f}')
    print('TOTAL_CALLS', sum(s.calls for s in STAGES))
    print('TOTAL_CNY', total(STAGES, full_hd_tokens))
    print('IMAGE_720P_COMPARISON_CNY', total(STAGES, hd_tokens))

    # Existing proposed balance attempt caps: 12 General, 5 Long.
    # Charge each additional attempt the same assumed response budget.
    capped_attempts = tuple(
        replace(s, calls=12) if s.name == 'A3-balance'
        else replace(s, calls=5) if s.name == 'A5-balance'
        else s for s in STAGES
    )
    print('PROPOSED_ATTEMPT_CAP_CALLS', sum(s.calls for s in capped_attempts))
    print('PROPOSED_ATTEMPT_CAP_CNY', total(capped_attempts, full_hd_tokens))

    for extra_thinking in (4096, 32768):
        extra_cost = sum(s.calls for s in STAGES) * extra_thinking * OUTPUT_PRICE / MILLION
        print('ADDED_THINKING_TOKENS_EACH', extra_thinking, 'EXTRA_CNY', extra_cost)

    # Conditional native-video comparison for caption stages only.
    # Historical non-qwen3-vl-plus example cap: 768*32*32; pair factor 2.
    # Correct floor-to-32 calculation gives 1152x640, not 1184x640.
    # This is not a verified qwen3.8-flash server default.
    native_caption_visual = (
        360 * short_video_estimate(10, 786432)[2]
        + 120 * short_video_estimate(30, 786432)[2]
    )
    image_caption_visual = 7200 * full_hd_tokens
    saving = (image_caption_visual - native_caption_visual) * INPUT_PRICE / MILLION
    print('CONDITIONAL_NATIVE_CAPTION_VISUAL_TOKENS', native_caption_visual)
    print('CONDITIONAL_NATIVE_CAPTION_TOTAL_CNY', total(STAGES, full_hd_tokens) - saving)

    # New user scenario: native L1/L2 clips at 2 FPS. API reference supplies
    # explicit qwen3.8-flash defaults; the historical 768*1024 cap above is
    # only a comparison, never the model's default.
    print('HISTORICAL VIDEO2FPS_DEFAULT: L1/L2 native only; C_GATE/A7 image comparison')
    for row in video_2fps_rows():
        print('VIDEO2FPS_STAGE', *row)
    for pixel_cap in (655360, 786432, 2048000):
        rows = video_2fps_rows(pixel_cap)
        cost = sum((row[5] for row in rows), Decimal(0))
        thought_cost = Decimal(496 * 4096) * OUTPUT_PRICE / MILLION
        print('VIDEO2FPS_PROFILE', pixel_cap,
              'L1_resize_and_tokens', short_video_estimate(20, pixel_cap),
              'L2_resize_and_tokens', short_video_estimate(60, pixel_cap),
              'TOTAL_CNY', cost, 'WITH_4096_THINKING_EACH_CNY', cost + thought_cost)
    print('CURRENT_A7_NATIVE_VIDEO: actual preprocessing unknown; explicit usage scenarios only')
    for vision_each in (100000, 400000, 800000):
        per_question, eight_questions, total_cost = native_audit_usage_scenario(vision_each)
        print('A7_NATIVE_USAGE', vision_each, 'PER_QUESTION_CNY', per_question,
              'EIGHT_QUESTIONS_CNY', eight_questions, 'PIPELINE_CNY', total_cost)
    print('PASS: offline scenario arithmetic completed; no API or billing validation')


if __name__ == '__main__':
    main()
