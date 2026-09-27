=== There is also a [TypeScript and Lua](https://github.com/dbowlin/CoCo3_MCP_Server/) version ===

# CoCo 3 MCP Server PYTHON

This app lets an assistant use a Tandy Color Computer 3. It runs the CoCo in MAME, so the assistant can type, use disks, and look at the screen.

You need:

- Python 3.10 or newer (`python` on your PATH)
- This repo
- [MAME](https://www.mamedev.org/) (`mame.exe`)
- Your own CoCo 3 ROM (`coco3.zip`)

`decb.exe` is only needed if you want the assistant to build a disk.

## Turn it on

In this folder, run:

```bat
install.cmd
```

That sets the app up and starts it. Leave it running.

After you restart the computer, start it again with:

```bat
coco3-mcp.cmd
```

The assistant starts MAME when you ask it to start the CoCo.

## Use it from any app

Once `coco3-mcp.cmd` is running, any program on this computer can use the CoCo at:

```text
http://127.0.0.1:18766/mcp
```

That address is also saved in `server.json` in this folder, and in your user folder at `.coco3-mcp\server.json`.

Open this in a browser to check that it is on:

```text
http://127.0.0.1:18766/
```

You should see `"ok": true`.

## Add it to an IDE

This works the same way in Cursor, VS Code, Antigravity, Visual Studio, and other editors that support MCP. Open the editor’s MCP (or AI tools) settings and add a server.

If you use Cursor, `install.cmd` already adds it. Reload MCP in Cursor’s settings.

For any other editor, add a server with these three settings:


| Setting        | Value            |
| -------------- | ---------------- |
| Name           | `coco3`          |
| Command        | `python`         |
| Arguments      | `-m` `coco3_mcp` |
| Working folder | this folder      |


Example:

```json
{
  "mcpServers": {
    "coco3": {
      "command": "python",
      "args": ["-m", "coco3_mcp"],
      "cwd": "C:\\path\\to\\coco3-mcp"
    }
  }
}
```

Change `C:\\path\\to\\coco3-mcp` to the real path of this folder. Then reload MCP in the editor and ask it to start the CoCo.

## What you can ask for

- Start or stop the CoCo
- Type on the keyboard
- Mount or eject a disk
- Take a picture of the screen
- Read or change memory
- Save or load a state
- Build a disk (needs `decb.exe`)

## Disclosure
Agentic AI was used in some parts of this code.

## License

[MIT](LICENSE)
