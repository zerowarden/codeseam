from __future__ import annotations

from collections import Counter

from codeseam.analysis.relations.models import (
    ArgumentNormalization,
    MemberFeatureCache,
    MemberFeatures,
    MemberInput,
)
from codeseam.analysis.signatures import CallFingerprint, call_kwarg_shape_values
from codeseam.platform import text

NORMALIZATION_TRANSFORM_METHODS = {"decode", "encode"}
ONE_PARAMETER = 1


def argument_normalization_relation_features(
    left: MemberFeatures,
    right: MemberFeatures,
) -> ArgumentNormalization:
    if not _compatible_members(left, right):
        return ArgumentNormalization()
    left_transforms = _argument_transform_tokens(left)
    right_transforms = _argument_transform_tokens(right)
    if bool(left_transforms) == bool(right_transforms):
        return ArgumentNormalization()
    shared = _shared_operation_tokens(left, right)
    if not shared:
        return ArgumentNormalization()
    wrapper = left if left_transforms else right
    primitive = right if left_transforms else left
    transforms = sorted(left_transforms or right_transforms)
    return ArgumentNormalization(
        wrapper=wrapper.member.binding_key,
        primitive=primitive.member.binding_key,
        wrapper_parameter_type=wrapper.member.first_parameter,
        primitive_parameter_type=primitive.member.first_parameter,
        transform_tokens=tuple(transforms),
        shared_operation_tokens=tuple(shared),
        interpretation=(
            "typed argument normalization before a shared operation; not semantic equivalence"
        ),
    )


def has_argument_normalization_transform(member: MemberInput) -> bool:
    return bool(_argument_transform_tokens(MemberFeatureCache((member,)).get(member)))


def shared_operation_candidate(left: MemberInput, right: MemberInput) -> bool:
    cache = MemberFeatureCache((left, right))
    return bool(_shared_operation_tokens(cache.get(left), cache.get(right)))


def _compatible_members(left: MemberFeatures, right: MemberFeatures) -> bool:
    return bool(
        left.member.language == right.member.language
        and left.member.return_type
        and left.member.return_type == right.member.return_type
        and left.member.parameter_count == ONE_PARAMETER
        and right.member.parameter_count == ONE_PARAMETER
        and left.member.first_parameter != right.member.first_parameter
        and _returns_arg0(left)
        and _returns_arg0(right)
    )


def _argument_transform_tokens(member: MemberFeatures) -> set[str]:
    if member.normalization_transform_tokens:
        return set(member.normalization_transform_tokens)
    tokens: set[str] = set()
    for call in member.call_fingerprints:
        receiver = _receiver(call)
        callee = _callee(call)
        if not receiver or not callee:
            continue
        if receiver[0] != "ARG0" or receiver[1]:
            continue
        arg_roles = _arg_roles(call)
        kwarg_roles = _kwarg_roles(call)
        if set(arg_roles) - _constant_roles(arg_roles):
            continue
        if set(kwarg_roles) - _constant_roles(kwarg_roles):
            continue
        name_tokens = [item for item in callee if item]
        if not name_tokens or "_".join(name_tokens) not in NORMALIZATION_TRANSFORM_METHODS:
            continue
        if token := _token(call):
            tokens.add(token)
    return tokens


def _shared_operation_tokens(left: MemberFeatures, right: MemberFeatures) -> list[str]:
    left_counts = Counter(left.calls) - Counter(_argument_transform_tokens(left))
    right_counts = Counter(right.calls) - Counter(_argument_transform_tokens(right))
    shared = left_counts & right_counts
    return sorted(shared.elements())


def _returns_arg0(member: MemberFeatures) -> bool:
    return member.statements == ("RETURN:ARG0",)


def _items(value: object) -> list[object]:
    if isinstance(value, dict):
        return list(value.values())
    return list(value) if isinstance(value, list | tuple) else []


def _constant_roles(value: object) -> set[str]:
    return {text(item) for item in _items(value) if text(item).startswith("CONST_")}


def _receiver(call: CallFingerprint) -> tuple[str, tuple[str, ...]] | None:
    if call.receiver_shape is None:
        return None
    return call.receiver_shape.base, call.receiver_shape.access_path


def _callee(call: CallFingerprint) -> tuple[str, ...]:
    return call.callee_shape.name_tokens


def _arg_roles(call: CallFingerprint) -> tuple[str, ...]:
    return call.arg_roles


def _kwarg_roles(call: CallFingerprint) -> tuple[str, ...]:
    return call_kwarg_shape_values(call)


def _token(call: CallFingerprint) -> str:
    return call.token
