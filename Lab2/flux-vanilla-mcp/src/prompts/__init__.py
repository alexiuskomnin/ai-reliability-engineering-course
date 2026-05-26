"""MCP prompts for the Flux MCP server.

One prompt per file. Modules are auto-imported by `DynamicMCPServer` —
they only need to call `@mcp.prompt(...)` to self-register.
"""
