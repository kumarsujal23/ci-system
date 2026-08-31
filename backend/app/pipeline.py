"""
YAML pipeline schema + parsing.

Example pipeline.yaml:

  image: python:3.11-slim
  timeout_seconds: 600
  resources:
    memory: 512m
    cpus: 1.0
    network: bridge
  steps:
    - name: install
      run: pip install -r requirements.txt
    - name: test
      run: pytest -q
"""
from __future__ import annotations
import yaml
from pydantic import BaseModel, Field, field_validator


class ResourceLimits(BaseModel):
    memory: str = "512m"
    cpus: float = Field(default=1.0, gt=0)


class PipelineStep(BaseModel):
    name: str
    run: str
    allow_failure: bool = False


class Pipeline(BaseModel):
    image: str
    timeout_seconds: int = Field(default=900, gt=0)
    resources: ResourceLimits = ResourceLimits()
    network: str = "none"  # "none" (default, no outbound network) or "bridge" (opt-in for remote deps)
    steps: list[PipelineStep]

    @field_validator("network")
    @classmethod
    def supported_network(cls, v):
        if v not in ("none", "bridge"):
            raise ValueError("network must be 'none' or 'bridge'")
        return v

    @field_validator("steps")
    @classmethod
    def must_have_steps(cls, v):
        if not v:
            raise ValueError("pipeline must define at least one step")
        return v


class PipelineParseError(ValueError):
    pass


def parse_pipeline(raw_yaml: str) -> Pipeline:
    try:
        data = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as e:
        raise PipelineParseError(f"invalid YAML: {e}") from e
    if not isinstance(data, dict):
        raise PipelineParseError("pipeline YAML must be a mapping at the top level")
    try:
        return Pipeline(**data)
    except Exception as e:  # pydantic ValidationError etc.
        raise PipelineParseError(str(e)) from e
