#!/usr/bin/env python3
"""Relay a public TCP port on the seedbox to rtorrent in k8s.

PulsedMedia's wireguard NATs egress out of the seedbox IP but forwards
nothing inbound, so peers cannot reach the pod. This listens on the
seedbox's public interface and dials the pod's fixed tunnel address.

Usage: rtorrent-relay.py LISTEN_PORT TARGET_HOST TARGET_PORT
"""

import asyncio
import sys


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except OSError:
        pass
    finally:
        writer.close()


async def handle(
    client_r: asyncio.StreamReader,
    client_w: asyncio.StreamWriter,
    host: str,
    port: int,
) -> None:
    try:
        target_r, target_w = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=5
        )
    except (OSError, asyncio.TimeoutError):
        # Pod or tunnel down: refuse fast so the peer moves on.
        client_w.close()
        return
    await asyncio.gather(pipe(client_r, target_w), pipe(target_r, client_w))


async def main(listen_port: int, host: str, port: int) -> None:
    server = await asyncio.start_server(
        lambda r, w: handle(r, w, host, port),
        "0.0.0.0",
        listen_port,
        reuse_address=True,
    )
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]), sys.argv[2], int(sys.argv[3])))
