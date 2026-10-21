#!/usr/bin/env python3
"""Offline scenario arithmetic, not a production configuration or billing tool.

Reads no media, credentials or runtime config; sends no requests; writes stdout only.
Prices checked 2026-10-21: Alibaba Model Studio Beijing qwen3.8-flash,
CNY 0.8/M input and 2.7/M output, without cache/free-tier/batch discounts.
See docs/qwen38_flash_one_hour_cost_estimate_2026-10-21.md for assumptions.
"""

from dataclasses import dataclass, replace
from decimal import Decimal


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


def main() -> None:
    # Image mode: round dimensions to multiples of 32, then area / 1024 + 2.
    # 1920x1080 -> 1920x1088; alternative 1280x720 -> 1280x704.
    full_hd_tokens = 1920 * 1088 // 1024 + 2
    hd_tokens = 1280 * 704 // 1024 + 2
    print('SCENARIO ONLY: independent image inputs, thinking off; no API/media IO')
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
    # Official example's non-qwen3-vl-plus pixel cap: 768*32*32; pair factor 2.
    # 1920x1080 scales to 1184x640 in that example; all sampling is unchanged.
    # This is not a verified qwen3.8-flash server default.
    native_caption_visual = (
        360 * (5 * (1184 * 640 // 1024) + 2)
        + 120 * (15 * (1184 * 640 // 1024) + 2)
    )
    image_caption_visual = 7200 * full_hd_tokens
    saving = (image_caption_visual - native_caption_visual) * INPUT_PRICE / MILLION
    print('CONDITIONAL_NATIVE_CAPTION_VISUAL_TOKENS', native_caption_visual)
    print('CONDITIONAL_NATIVE_CAPTION_TOTAL_CNY', total(STAGES, full_hd_tokens) - saving)
    print('PASS: offline scenario arithmetic completed; no API or billing validation')


if __name__ == '__main__':
    main()
