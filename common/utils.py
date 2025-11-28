import asyncio
import itertools
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, List, Optional, TypeVar, Union, cast

from pyrogram.errors import (
    FloodTestPhoneWait,
    FloodWait,
    SlowmodeWait,
    TakeoutInitDelay,
    TwoFaConfirmWait,
)

AnyReturnType = TypeVar("AnyReturnType")


def flatten(list_of_lists: List[list]) -> list:
    if not list_of_lists:
        return []
    if isinstance(list_of_lists[0], list):
        return list(itertools.chain(*list_of_lists))
    return list_of_lists


def serialize_pyrogram_type(v: Any) -> Optional[Union[dict, list, Enum]]:
    exclude_keys = [
        "_client",
        "raw",
        "waveform",  # exclude "waveform" because not helpful bytes data
    ]

    if not v:
        return v

    def serialize(obj):
        if isinstance(obj, Enum):
            return obj.value
        elif hasattr(obj, "__dict__"):
            return {
                key: serialize(value)
                for key, value in obj.__dict__.items()
                if key not in exclude_keys
            }
        elif isinstance(obj, list):
            return [serialize(o) for o in obj]

        return obj

    if isinstance(v, list):
        return [serialize(r) for r in v]

    return serialize(v)


async def run_pyrogram_method_with_retry_async(
    retries: int, func: Callable[..., AnyReturnType], *args, **kwargs
) -> Optional[AnyReturnType]:
    seconds = 10
    for retry in range(retries):
        try:
            result = func(*args, **kwargs)
            if asyncio.iscoroutine(result):
                return await result
            return result
        except (TimeoutError, OSError) as e:
            print(f"Waiting {seconds} seconds!")
            await asyncio.sleep(seconds)
            if retry == (retries - 1):
                print("Skipping!", e)
                raise e
        except (
            TwoFaConfirmWait,
            FloodTestPhoneWait,
            FloodWait,
            SlowmodeWait,
            TakeoutInitDelay,
        ) as e:
            # flood errors: https://docs.pyrogram.org/api/errors/flood
            seconds = cast(int, e.value)  # e.value contains the flood wait timeout
            print(f"Exception: {e}. Waiting {seconds} seconds")
            await asyncio.sleep(seconds)


def naive_utcnow() -> datetime:
    """Returns the current UTC time as a naive datetime (without timezone info)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_or_create_event_loop():
    """
    Utility function to get the current event loop or create a new one if none exists.
    """
    try:
        return asyncio.get_running_loop()  # Get current event loop if available
    except RuntimeError:
        loop = asyncio.new_event_loop()  # Create new loop if none exists
        asyncio.set_event_loop(loop)  # Set the new loop as  current loop
        return loop  # later do not kill loop for reuse (via run_until_complete)
