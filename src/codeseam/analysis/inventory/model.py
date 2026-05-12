from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from typing import cast

from codeseam.platform import Json, sha256_text

type FunctionCacheRecord = tuple[
    str,
    str,
    str,
    str | None,
    int,
    int,
    bool,
    bool,
    int,
    int,
    int,
    int,
    int,
    str,
    tuple[str, ...],
    str,
    str,
    int,
    str,
]

FUNCTION_CACHE_RECORD_FIELD_COUNT = 19


@dataclass
class FunctionRecord:
    language: str
    file: str
    symbol: str
    container: str | None
    start_line: int
    end_line: int
    is_exported_or_public: bool
    is_async: bool
    parameter_count: int
    branch_count: int
    loop_count: int
    return_count: int
    max_nesting: int
    role: str
    source: InitVar[str]
    caveats: list[str] = field(default_factory=list)
    extraction_confidence: str = "high"
    schema_version: str = field(init=False, default="codeseam.function_unit.v1")
    function_id: str = field(init=False, default="")
    line_span: int = field(init=False)
    content_hash: str = field(init=False)

    def __post_init__(self, source: str) -> None:
        self.line_span = max(1, self.end_line - self.start_line + 1)
        self.content_hash = sha256_text(source)

    def to_json_object(self) -> Json:
        return {
            "language": self.language,
            "file": self.file,
            "symbol": self.symbol,
            "container": self.container,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "is_exported_or_public": self.is_exported_or_public,
            "is_async": self.is_async,
            "parameter_count": self.parameter_count,
            "branch_count": self.branch_count,
            "loop_count": self.loop_count,
            "return_count": self.return_count,
            "max_nesting": self.max_nesting,
            "role": self.role,
            "caveats": self.caveats,
            "extraction_confidence": self.extraction_confidence,
            "schema_version": self.schema_version,
            "function_id": self.function_id,
            "line_span": self.line_span,
            "content_hash": self.content_hash,
        }

    def to_cache_record(self) -> FunctionCacheRecord:
        ## Warm analysis needs to hydrate function inventory before reports can be built.

        return (
            self.language,
            self.file,
            self.symbol,
            self.container,
            self.start_line,
            self.end_line,
            self.is_exported_or_public,
            self.is_async,
            self.parameter_count,
            self.branch_count,
            self.loop_count,
            self.return_count,
            self.max_nesting,
            self.role,
            tuple(self.caveats),
            self.extraction_confidence,
            self.function_id,
            self.line_span,
            self.content_hash,
        )

    @classmethod
    def from_cache_record(cls, data: FunctionCacheRecord) -> FunctionRecord:
        record = cls(
            language=data[0],
            file=data[1],
            symbol=data[2],
            container=data[3],
            start_line=data[4],
            end_line=data[5],
            is_exported_or_public=data[6],
            is_async=data[7],
            parameter_count=data[8],
            branch_count=data[9],
            loop_count=data[10],
            return_count=data[11],
            max_nesting=data[12],
            role=data[13],
            source="",
            caveats=list(data[14]),
            extraction_confidence=data[15],
        )
        record.function_id = data[16]
        record.line_span = data[17]
        record.content_hash = data[18]
        return record


@dataclass(frozen=True, slots=True)
class FileWithoutFunctionUnits:
    file: str
    language: str
    caveats: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FunctionInventory:
    records: tuple[FunctionRecord, ...]
    selected_file_count: int
    files_without_function_units: tuple[FileWithoutFunctionUnits, ...] = ()

    @property
    def function_count(self) -> int:
        return len(self.records)


def function_cache_payload(
    records: tuple[FunctionRecord, ...],
) -> tuple[FunctionCacheRecord, ...]:
    return tuple(record.to_cache_record() for record in records)


def functions_from_cache_value(value: object) -> tuple[FunctionRecord, ...] | None:
    if not isinstance(value, tuple):
        return None
    records: list[FunctionRecord] = []
    try:
        for item in value:
            if not isinstance(item, tuple) or len(item) != FUNCTION_CACHE_RECORD_FIELD_COUNT:
                return None
            records.append(FunctionRecord.from_cache_record(cast(FunctionCacheRecord, item)))
    except (IndexError, KeyError, TypeError, ValueError):
        return None
    return tuple(records)


def assign_ids(records: list[FunctionRecord]) -> list[FunctionRecord]:
    sorted_records = sorted(
        records,
        key=lambda item: (
            item.file,
            item.start_line,
            item.end_line,
            item.container or "",
            item.symbol,
            item.content_hash,
        ),
    )
    for index, record in enumerate(sorted_records, start=1):
        record.function_id = f"fn_{index:06d}"
    return sorted_records
