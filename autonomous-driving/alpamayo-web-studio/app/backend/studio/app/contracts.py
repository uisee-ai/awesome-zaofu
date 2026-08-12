"""Typed API and provider-result contracts for Alpamayo Studio."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


DemoId = Literal[
    "workbench",
    "navigation",
    "ablation",
    "vqa",
    "auto-label",
    "regression-judge",
]


class CreateSceneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="Golden road scene", min_length=1, max_length=120)
    source: Literal["golden"] = "golden"


class DemoRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    demoId: DemoId
    parameters: dict[str, Any] = Field(default_factory=dict)


class ReviewRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["accepted", "modified", "rejected"]
    remarks: str = Field(default="", max_length=2_000)
    labels: list[str] = Field(default_factory=list, max_length=24)


class TrajectoryPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeSeconds: float
    position: tuple[float, float, float]
    rotation: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ]


class ProviderInferencePayload(BaseModel):
    """The semantic body a provider must return before a run can complete."""

    model_config = ConfigDict(extra="ignore")

    vqaAnswer: str = Field(min_length=1)
    chainOfCausation: str = Field(min_length=1)
    metaAction: str = Field(min_length=1)
    trajectory: list[TrajectoryPoint]
    labels: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    reviewStatus: Literal["unreviewed", "approved", "rejected"] = "unreviewed"

    @field_validator("trajectory")
    @classmethod
    def validate_trajectory(cls, points: list[TrajectoryPoint]) -> list[TrajectoryPoint]:
        if len(points) != 64:
            raise ValueError("trajectory must contain exactly 64 points")
        for index, point in enumerate(points, start=1):
            expected = round(index * 0.1, 1)
            if round(point.timeSeconds, 1) != expected:
                raise ValueError("trajectory must cover 0.1 through 6.4 seconds")
        return points
