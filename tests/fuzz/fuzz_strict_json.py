"""Atheris harness for the fail-closed MCP wire JSON decoder."""

import sys

import atheris

from scientific_toolkit_mcp.strict_json import loads


def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    if fdp.ConsumeBool():
        payload = fdp.ConsumeBytes(4096)
    else:
        payload = fdp.ConsumeUnicodeNoSurrogates(4096)
    try:
        loads(payload)
    except (UnicodeDecodeError, ValueError):
        pass


atheris.Setup(sys.argv, TestOneInput)
atheris.Fuzz()
