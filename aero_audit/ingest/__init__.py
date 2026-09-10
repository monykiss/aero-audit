from .adsblol import AdsbLolProvider
from .base import Provider
from .opensky import OpenSkyProvider
from .replay import iter_recording

PROVIDERS: dict[str, type[Provider]] = {
    "adsblol": AdsbLolProvider,
    "opensky": OpenSkyProvider,
}


def make_provider(name: str) -> Provider:
    try:
        return PROVIDERS[name.lower()]()
    except KeyError as e:
        raise KeyError(f"Unknown provider '{name}'. Known: {', '.join(PROVIDERS)}") from e


__all__ = ["PROVIDERS", "AdsbLolProvider", "OpenSkyProvider", "Provider", "iter_recording", "make_provider"]
