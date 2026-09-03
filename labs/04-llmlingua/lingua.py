"""LLMLingua 3형제 어댑터.

## 셋은 같은 클래스입니다

`PromptCompressor` 하나에 파라미터만 다릅니다. 그래서 폴더를 나누지 않고
설정으로 가릅니다. 다만 **조용히 무시되는 인자**가 있어서 그대로 두면
"설정을 바꿨는데 결과가 같은" 상황이 생깁니다.

    variant   무엇이 다른가                         필요한 것
    v1        토큰별 정보량으로 프루닝               인과 LM
    long      질문을 주고 문단별 중요도를 함께 봄     인과 LM + 질문 + 여러 문단
    v2        분류 모델이 토큰을 남길지 판정          전용 인코더 모델

## 조용히 무시되는 인자 — 이 랩에서 가장 조심할 부분

`use_llmlingua2=True` 로 만든 압축기에 `question` 이나 `rank_method` 를
넘기면 **에러 없이 무시됩니다.** LongLLMLingua 설정을 v2 에 잘못 붙여도
그냥 돌아가고, 결과만 v2 그대로입니다.

숫자가 안 바뀌는 이유를 찾느라 시간을 버리기 쉬우므로, 여기서는 **변형이
쓰지 않는 인자가 들어오면 실행을 거부합니다.**
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# ══════════════════════════════════════════════════════════════════
# 모델
#
# v1 기본값이 NousResearch/Llama-2-7b-hf(13GB) 입니다. 이 랩에서 쓰기에는
# 너무 크고, 무엇보다 **한국어를 잘 못 다룹니다.** 작고 다국어를 지원하는
# 모델로 바꿉니다. 압축 품질보다 "언어별로 다르게 동작하는가" 를 보려는
# 것이므로 작은 모델로 충분합니다.
# ══════════════════════════════════════════════════════════════════

# 크기별로 골라 쓸 수 있게 해 둡니다. 기본은 small 입니다 — 저장소를 받자마자
# 돌려볼 수 있어야 하고, 13GB 를 강제로 받게 하고 싶지 않았습니다.
#
# 다만 **작은 모델은 결과가 확연히 나쁩니다.** 특히 한국어에서 그렇습니다.
# 실제로 쓰실 거라면 large 로 한 번 재보시고 판단하세요.
MODELS = {
    "v1": {
        "small": ("Qwen/Qwen2.5-0.5B", "약 1GB"),
        "large": ("Qwen/Qwen2.5-1.5B", "약 3GB"),
        "paper": ("NousResearch/Llama-2-7b-hf", "약 13GB · 논문이 쓴 모델"),
    },
    "long": {
        "small": ("Qwen/Qwen2.5-0.5B", "약 1GB"),
        "large": ("Qwen/Qwen2.5-1.5B", "약 3GB"),
        "paper": ("NousResearch/Llama-2-7b-hf", "약 13GB · 논문이 쓴 모델"),
    },
    "v2": {
        "small": ("microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank",
                  "약 700MB"),
        "large": ("microsoft/llmlingua-2-xlm-roberta-large-meetingbank",
                  "약 2.2GB · 논문이 쓴 모델"),
    },
}

DEFAULT_MODEL = {k: v["small"][0] for k, v in MODELS.items()}


def resolve_model(variant: str, name: Optional[str]) -> str:
    """모델 이름을 정합니다.

    small/large/paper 같은 별칭을 쓰거나 HuggingFace 경로를 그대로 주셔도
    됩니다. 별칭이면 표에서 찾고, 아니면 그대로 씁니다.
    """
    if not name:
        return DEFAULT_MODEL[variant]
    tiers = MODELS[variant]
    if name in tiers:
        return tiers[name][0]
    if "/" not in name:
        raise ValueError(
            f"모르는 모델 별칭: {name}\n"
            f"  {variant} 에서 쓸 수 있는 별칭: {list(tiers)}\n"
            f"  또는 HuggingFace 경로를 그대로 주세요 (예: Qwen/Qwen2.5-3B)")
    return name


# 변형마다 실제로 쓰는 인자입니다. 목록에 없는 것이 들어오면 거부합니다.
ALLOWED = {
    "v1": {"rate", "target_token", "force_reserve_digit", "force_tokens",
           "use_sentence_level_filter", "drop_consecutive", "context_budget"},
    "long": {"rate", "target_token", "force_reserve_digit", "force_tokens",
             "use_sentence_level_filter", "drop_consecutive", "context_budget",
             "question", "rank_method", "condition_compare",
             "dynamic_context_compression_ratio", "reorder_context",
             "concate_question"},
    "v2": {"rate", "target_token", "force_reserve_digit", "force_tokens",
           "drop_consecutive", "chunk_end_tokens"},
}

# long 은 질문 기반 재순위가 핵심이라 이 값들이 기본으로 켜집니다.
LONG_DEFAULTS = {"rank_method": "longllmlingua", "condition_compare": True}

_CACHE: Dict[Tuple[str, str], Any] = {}


def load(variant: str, model_name: Optional[str] = None, device: str = "cpu"):
    """압축기를 만듭니다. 같은 조합은 다시 만들지 않습니다.

    모델 로딩이 수십 초 걸립니다. 케이스마다 새로 만들면 12건에 10분이
    넘어가므로 프로세스 안에서 재사용합니다.
    """
    if variant not in MODELS:
        raise ValueError(f"모르는 변형: {variant} (v1 | long | v2)")
    name = resolve_model(variant, model_name)
    key = (variant, name)
    if key not in _CACHE:
        from llmlingua import PromptCompressor
        _CACHE[key] = PromptCompressor(
            model_name=name, device_map=device,
            use_llmlingua2=(variant == "v2"))
    return _CACHE[key]


def check_params(variant: str, params: Dict[str, Any]) -> None:
    """이 변형이 쓰지 않는 인자가 있으면 멈춥니다.

    무시하고 넘어가면 '설정을 바꿨는데 결과가 같은' 상황이 생기고,
    원인을 찾기가 아주 어렵습니다.
    """
    unknown = set(params) - ALLOWED[variant]
    if not unknown:
        return
    hint = ""
    if variant == "v2" and unknown & ALLOWED["long"]:
        hint = ("\n  LongLLMLingua 전용 인자로 보입니다. v2 는 질문을 쓰지 않습니다 — "
                "variant 를 long 으로 바꾸시거나 이 인자를 빼주세요.")
    raise ValueError(
        f"variant={variant} 이 쓰지 않는 인자입니다: {sorted(unknown)}{hint}\n"
        f"  이 변형이 받는 인자: {sorted(ALLOWED[variant])}")


def split_contexts(text: str) -> List[str]:
    """문단으로 나눕니다.

    LongLLMLingua 는 **여러 조각**을 받아 조각별 중요도를 매깁니다.
    통짜 문자열을 주면 조각이 하나뿐이라 재순위가 할 일이 없어집니다.
    """
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(parts) >= 2:
        return parts
    # 빈 줄이 없으면 문장으로 내려갑니다.
    sents = [s.strip() for s in re.split(r"(?<=[.!?다요])\s+", text) if s.strip()]
    return sents if len(sents) >= 2 else [text]


def compress(text: str, variant: str = "v2", question: str = "",
             model_name: Optional[str] = None, device: str = "cpu",
             **params) -> Tuple[str, Dict[str, Any]]:
    """랩 계약과 같은 시그니처입니다."""
    kw = dict(params)
    if variant == "long":
        for k, v in LONG_DEFAULTS.items():
            kw.setdefault(k, v)
        if question:
            kw["question"] = question
    check_params(variant, kw)

    c = load(variant, model_name, device)
    ctx = split_contexts(text) if variant == "long" else [text]

    r = c.compress_prompt(ctx, **kw)
    out = r["compressed_prompt"]

    # LongLLMLingua 는 질문을 결과에 덧붙일 수 있습니다(concate_question 기본 True).
    # 그대로 두면 질문 토큰이 압축 결과에 섞여 절감률이 왜곡됩니다.
    if question and out.rstrip().endswith(question.rstrip()):
        out = out.rstrip()[: -len(question.rstrip())].rstrip()

    return out, {
        "variant": variant,
        "model": resolve_model(variant, model_name),
        "n_contexts": len(ctx),
        # 라이브러리가 자기 토크나이저로 센 값입니다. 랩의 토큰 수와 기준이
        # 다르므로 참고용으로만 남깁니다.
        "lib_tokens_before": r.get("origin_tokens"),
        "lib_tokens_after": r.get("compressed_tokens"),
    }
