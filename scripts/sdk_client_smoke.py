"""End-to-end transport check with the official third-party MCP Python SDK.

Runs against a loopback instance and an ephemeral test token; no production
secret, Render environment, or external LLM account is needed.
"""
import asyncio
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def exercise(url, token):
    async with streamablehttp_client(
        url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
        sse_read_timeout=30,
    ) as (reader, writer, _):
        async with ClientSession(reader, writer) as session:
            initialized = await session.initialize()
            assert initialized.serverInfo.name == "furox-scientific-toolkit", initialized
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            assert len(names) == 9, names
            assert "toolkit_catalog" in names
            assert "plan_auditor_audit" not in names
            response = await session.call_tool("toolkit_catalog", {})
            assert not response.isError, response
            catalog = json.loads(response.content[0].text)
            assert catalog["count"] == 7, catalog
            print("PASS official MCP SDK initialize, list_tools (9), call_tool "
                  "(7 project catalog), plan audit not exported remotely")


def main():
    port = free_port()
    token = secrets.token_urlsafe(36)
    env = {**os.environ, "SCITOOL_MCP_BEARER_TOKEN": token, "PORT": str(port)}
    process = subprocess.Popen([sys.executable, "-m",
                                "scientific_toolkit_mcp.http_server"],
                               env=env, stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE, text=True)
    try:
        for _ in range(50):
            if process.poll() is not None:
                raise RuntimeError(f"Server exited: {process.stderr.read()}")
            try:
                with urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                    assert json.load(r)["status"] == "ok"
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise TimeoutError("loopback server did not start")
        asyncio.run(exercise(f"http://127.0.0.1:{port}/mcp", token))
    finally:
        process.terminate()
        try:
            process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


if __name__ == "__main__":
    main()
