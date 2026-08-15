"""Chart timeframes.

Only three timeframes are fetched from upstream providers: ``10s``, ``1m``
and ``1d``. Everything else is derived by resampling one of those, which
keeps the provider layer small and makes every derived timeframe testable as
a pure function.

``10s`` is its own base rather than a resample because nothing coarser can
produce it: it is fetched as native 10-second bars from IBKR, or rebuilt from
individual trade prints on Alpaca, and extended live from the trade stream.
"""

from __future__ import annotations

from enum import Enum


class Timeframe(str, Enum):
    S10 = "10s"
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    D1 = "1d"
    W1 = "1w"

    @property
    def seconds(self) -> int:
        return _SECONDS[self]

    @property
    def is_intraday(self) -> bool:
        return self in _INTRADAY

    @property
    def base(self) -> "Timeframe":
        """The upstream timeframe this one is resampled from.

        A base timeframe is its own base.
        """
        if self is Timeframe.S10:
            return Timeframe.S10
        return Timeframe.M1 if self.is_intraday else Timeframe.D1

    @property
    def is_base(self) -> bool:
        return self is self.base

    @property
    def label(self) -> str:
        return self.value.upper()

    @classmethod
    def parse(cls, value: str | "Timeframe") -> "Timeframe":
        """Case-insensitive lookup.

        Raises ``ValueError`` with the supported list, which the WebSocket
        layer turns into a client-facing error message.
        """
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            supported = ", ".join(t.value for t in cls)
            raise ValueError(
                f"Unsupported timeframe {value!r}. Supported: {supported}."
            ) from None


_SECONDS: dict[Timeframe, int] = {
    Timeframe.S10: 10,
    Timeframe.M1: 60,
    Timeframe.M5: 5 * 60,
    Timeframe.M15: 15 * 60,
    Timeframe.H1: 60 * 60,
    Timeframe.D1: 24 * 60 * 60,
    Timeframe.W1: 7 * 24 * 60 * 60,
}

_INTRADAY = frozenset(
    {Timeframe.S10, Timeframe.M1, Timeframe.M5, Timeframe.M15, Timeframe.H1}
)

ALL_TIMEFRAMES: tuple[Timeframe, ...] = tuple(Timeframe)
BASE_TIMEFRAMES: tuple[Timeframe, ...] = (Timeframe.S10, Timeframe.M1, Timeframe.D1)
