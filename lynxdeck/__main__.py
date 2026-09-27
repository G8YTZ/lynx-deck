"""Run with:  python3 -m lynxdeck --config config/lynx_deck.yaml"""
import argparse
import asyncio
import logging
import signal
from pathlib import Path

from . import __version__, config
from .engine import Engine
from .deck_protocol import DeckServer
from .library import Library
from .state import State
from .rest_api import serve as serve_http

log = logging.getLogger("lynxdeck")


async def run(cfg):
    state = State(cfg)
    state.load_into_config()
    library = Library(cfg)
    await library.scan()
    engine = Engine(cfg, library)
    await engine.start()
    server = DeckServer(cfg, engine)
    await server.start()
    http_task = asyncio.create_task(serve_http(cfg, engine, server, state))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()

    log.info("Shutting down")
    http_task.cancel()
    await server.close()
    await engine.close()


def main():
    ap = argparse.ArgumentParser(description="Lynx Deck media player")
    ap.add_argument("--config", default="config/lynx_deck.yaml")
    ap.add_argument("--debug", action="store_true", help="log every protocol command")
    args = ap.parse_args()
    if not Path(args.config).is_file():
        example = Path(args.config).with_suffix(".yaml.example")
        raise SystemExit(f"No config at {args.config}\n"
                         f"Copy the example: cp {example} {args.config}")
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    log.info("Lynx Deck %s starting", __version__)
    asyncio.run(run(config.load(args.config)))


if __name__ == "__main__":
    main()
