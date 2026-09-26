"""Run with:  python3 -m lynxdeck --config config/lynx_deck.yaml"""
import argparse
import asyncio
import logging
import signal

from . import __version__, config
from .engine import Engine
from .hyperdeck_server import HyperDeckServer
from .library import Library

log = logging.getLogger("lynxdeck")


async def run(cfg):
    library = Library(cfg)
    await library.scan()
    engine = Engine(cfg, library)
    await engine.start()
    server = HyperDeckServer(cfg, engine)
    await server.start()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()

    log.info("Shutting down")
    await server.close()
    await engine.close()


def main():
    ap = argparse.ArgumentParser(description="Lynx Deck media player")
    ap.add_argument("--config", default="config/lynx_deck.yaml")
    ap.add_argument("--debug", action="store_true", help="log every protocol command")
    args = ap.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    log.info("Lynx Deck %s starting", __version__)
    asyncio.run(run(config.load(args.config)))


if __name__ == "__main__":
    main()
