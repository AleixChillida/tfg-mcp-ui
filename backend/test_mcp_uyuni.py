import asyncio
from pathlib import Path

from dotenv import load_dotenv

from mcp_clients.uyuni_client import UyuniMCPClient


load_dotenv(dotenv_path=Path(__file__).parent / ".env")


async def main() -> None:
    client = UyuniMCPClient()

    print("Probando conexión con MCP Uyuni...")
    print()

    tools = await client.list_tools()

    print("TOOLS DISPONIBLES:")
    for tool in tools:
        print("-", tool)

    print()
    print("Probando tool list_systems...")
    print()

    result = await client.call_tool("list_systems", {})

    print("RESULTADO list_systems:")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())