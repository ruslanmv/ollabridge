"""Result models for the doctor diagnostic suite (human + JSON output)."""

from __future__ import annotations

import json
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class CheckStatus(str, Enum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"

    @property
    def icon(self) -> str:
        return {"ok": "✅", "warn": "⚠", "fail": "❌", "skip": "⏭"}[self.value]


class CheckResult(BaseModel):
    name: str
    status: CheckStatus
    detail: str = ""
    hint: str = ""  # remediation hint shown on warn/fail
    data: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def ok(cls, name: str, detail: str = "", **data: Any) -> "CheckResult":
        return cls(name=name, status=CheckStatus.OK, detail=detail, data=data)

    @classmethod
    def warn(
        cls, name: str, detail: str = "", hint: str = "", **data: Any
    ) -> "CheckResult":
        return cls(
            name=name, status=CheckStatus.WARN, detail=detail, hint=hint, data=data
        )

    @classmethod
    def fail(
        cls, name: str, detail: str = "", hint: str = "", **data: Any
    ) -> "CheckResult":
        return cls(
            name=name, status=CheckStatus.FAIL, detail=detail, hint=hint, data=data
        )

    @classmethod
    def skip(cls, name: str, detail: str = "", hint: str = "") -> "CheckResult":
        return cls(name=name, status=CheckStatus.SKIP, detail=detail, hint=hint)


class SectionReport(BaseModel):
    name: str
    checks: list[CheckResult] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    def add(self, check: CheckResult) -> CheckResult:
        self.checks.append(check)
        return check

    @property
    def failed(self) -> bool:
        return any(c.status == CheckStatus.FAIL for c in self.checks)


class DoctorReport(BaseModel):
    sections: list[SectionReport] = Field(default_factory=list)
    version: Optional[str] = None

    @property
    def ok(self) -> bool:
        return not any(s.failed for s in self.sections)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)
