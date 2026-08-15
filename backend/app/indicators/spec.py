"""Indicator definitions, loaded and validated from YAML.

Indicators are configuration, not code: adding an EMA or a new key level is a
YAML edit. The schema is strict so a typo fails at startup with a clear
message instead of silently drawing nothing.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

from ..domain.timeframes import Timeframe
from .functions import SESSION_LEVEL_KINDS
from .levels import LevelKey, parse_level_key


class IndicatorType(str, Enum):
    EMA = "ema"
    SMA = "sma"
    VWAP = "vwap"
    MACD = "macd"
    PREMARKET = "premarket"
    SESSION_BOUND = "session_bound"
    SESSION_LEVEL = "session_level"
    DAILY_LEVEL = "daily_level"
    VOLUME = "volume"
    TRADES = "trades"


class Pane(str, Enum):
    PRICE = "price"
    VOLUME = "volume"
    TRADES = "trades"
    MACD = "macd"


class LineStyle(str, Enum):
    SOLID = "solid"
    DASHED = "dashed"
    DOTTED = "dotted"


class TimeframeOption(BaseModel):
    model_config = {"extra": "forbid"}

    enabled: bool = True
    # Lets one indicator id use a different length per timeframe. This is how
    # the 10s chart carries the 1-minute EMAs: ema9 runs with span 54 there
    # (9 minutes = 54 ten-second bars), so it stays the same line, same
    # colour, same toggle across timeframes.
    span: int | None = Field(default=None, gt=0)
    # Optional per-timeframe display label, e.g. "EMA 54" on the 10s chart.
    label: str | None = None


class IndicatorSpec(BaseModel):
    model_config = {"extra": "forbid"}

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    type: IndicatorType
    label: str
    color: str = Field(default="#2a78d6", pattern=r"^#[0-9a-fA-F]{6}$")
    # Dark mode is a selected palette, not an automatic flip: each hue gets a
    # step chosen for the dark surface. Falls back to `color` when omitted.
    color_dark: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    span: int | None = Field(default=None, gt=0)
    # MACD lengths; meaningful only for type: macd.
    fast: int = Field(default=12, gt=0)
    slow: int = Field(default=26, gt=0)
    signal: int = Field(default=9, gt=0)
    level: str | None = None
    bound: Literal["high", "low"] | None = None
    line_width: int = Field(default=1, ge=1, le=4)
    line_style: LineStyle = LineStyle.SOLID
    price_line: bool = False
    last_value: bool = False
    group: str = "general"
    timeframes: dict[str, TimeframeOption] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_shape(self) -> "IndicatorSpec":
        if self.type in (IndicatorType.EMA, IndicatorType.SMA) and not self.span:
            raise ValueError(f"indicator {self.id!r} of type {self.type.value} needs a span")
        if self.type in (IndicatorType.PREMARKET, IndicatorType.SESSION_BOUND) and self.bound is None:
            raise ValueError(f"indicator {self.id!r} needs bound: high or low")
        if self.type is IndicatorType.DAILY_LEVEL:
            if not self.level:
                raise ValueError(f"indicator {self.id!r} needs a level")
            parse_level_key(self.level)  # raises with a precise message
        if self.type is IndicatorType.SESSION_LEVEL:
            if self.level not in SESSION_LEVEL_KINDS:
                raise ValueError(
                    f"indicator {self.id!r} needs one of {sorted(SESSION_LEVEL_KINDS)}"
                )

        for name in self.timeframes:
            Timeframe.parse(name)  # raises on an unknown timeframe key
        return self

    @property
    def pane(self) -> Pane:
        if self.type is IndicatorType.VOLUME:
            return Pane.VOLUME
        if self.type is IndicatorType.TRADES:
            return Pane.TRADES
        if self.type is IndicatorType.MACD:
            return Pane.MACD
        return Pane.PRICE

    @property
    def level_key(self) -> LevelKey | None:
        return parse_level_key(self.level) if self.level else None

    @property
    def draws_series(self) -> bool:
        """Volume and trades are read straight off the bar, not as a series."""
        return self.type not in (IndicatorType.VOLUME, IndicatorType.TRADES)

    def option_for(self, timeframe: Timeframe) -> TimeframeOption | None:
        return self.timeframes.get(timeframe.value)

    def applies_to(self, timeframe: Timeframe) -> bool:
        return timeframe.value in self.timeframes

    def span_for(self, timeframe: Timeframe) -> int | None:
        option = self.option_for(timeframe)
        if option and option.span:
            return option.span
        return self.span

    def label_for(self, timeframe: Timeframe) -> str:
        option = self.option_for(timeframe)
        if option and option.label:
            return option.label
        return self.label

    def to_client(self) -> dict:
        return {
            "id": self.id,
            "type": self.type.value,
            "label": self.label,
            "color": self.color,
            "color_dark": self.color_dark or self.color,
            "pane": self.pane.value,
            "line_width": self.line_width,
            "line_style": self.line_style.value,
            "price_line": self.price_line,
            "last_value": self.last_value,
            "group": self.group,
            "timeframes": {
                name: {
                    "enabled": option.enabled,
                    **({"label": option.label} if option.label else {}),
                }
                for name, option in self.timeframes.items()
            },
        }


class IndicatorConfigError(RuntimeError):
    """Raised when the indicator YAML is malformed."""


def load_indicator_specs(path: str | Path) -> list[IndicatorSpec]:
    """Read and validate the indicator config file."""
    file_path = Path(path)
    try:
        raw = yaml.safe_load(file_path.read_text()) or {}
    except FileNotFoundError as exc:
        raise IndicatorConfigError(f"Indicator config not found: {file_path}") from exc
    except yaml.YAMLError as exc:
        raise IndicatorConfigError(f"Invalid YAML in {file_path}: {exc}") from exc

    entries = raw.get("indicators")
    if not isinstance(entries, list):
        raise IndicatorConfigError(f"{file_path} must contain a top-level 'indicators' list")

    specs: list[IndicatorSpec] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        try:
            spec = IndicatorSpec.model_validate(entry)
        except ValidationError as exc:
            raise IndicatorConfigError(f"indicators[{index}] is invalid:\n{exc}") from exc
        if spec.id in seen:
            raise IndicatorConfigError(f"duplicate indicator id {spec.id!r}")
        seen.add(spec.id)
        specs.append(spec)
    return specs
