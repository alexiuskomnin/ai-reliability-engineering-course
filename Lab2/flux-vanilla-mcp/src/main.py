#!/usr/bin/env python3
"""flux-vanilla-mcp MCP server with dynamic tool loading.

This server automatically discovers and loads tools from the src/tools/ directory.
Each tool file should contain a function decorated with @mcp.tool().

Usage Examples:
  # Stdio mode (default MCP transport)
  python src/main.py
  
  # HTTP mode with MCP protocol over HTTP
  python src/main.py --transport http
  
  # Custom host/port
  python src/main.py --transport http --host localhost --port 8080
  
  # Environment variable mode
  MCP_TRANSPORT_MODE=http python src/main.py
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Add src to Python path
sys.path.insert(0, str(Path(__file__).parent))

from core.config import RuntimeConfig, set_config  # noqa: E402
from core.server import DynamicMCPServer  # noqa: E402


def main() -> None:
    """Main entry point for the MCP server."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="flux-vanilla-mcp MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport mode: stdio, or http"
    )
    parser.add_argument(
        "--host",
        default=os.getenv("HOST", "localhost"),
        help="Host to bind to in HTTP mode (default: localhost)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("PORT", "3000")),
        help="Port to bind to in HTTP mode (default: 3000)"
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        default=os.getenv("FLUX_MCP_READ_ONLY", "").lower() in ("1", "true", "yes"),
        help="Disable write / delete / reconcile tools.",
    )
    parser.add_argument(
        "--mask-secrets",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Mask Secret data and sensitive-looking fields in output.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.getenv("FLUX_MCP_TIMEOUT", "60")),
        help="Per-tool timeout in seconds.",
    )
    parser.add_argument(
        "--kubeconfig",
        default=os.getenv("KUBECONFIG") or None,
        help="Path to kubeconfig file (defaults to $KUBECONFIG, then ~/.kube/config).",
    )
    parser.add_argument(
        "--kube-context",
        default=None,
        help="Kubeconfig context to use (overridable at runtime via set_kubeconfig_context).",
    )
    parser.add_argument(
        "--enabled-tools",
        default="",
        help="Comma-separated allowlist of tool names. Empty = all tools enabled.",
    )
    _destructive_env = os.getenv("FLUX_MCP_ALLOW_DESTRUCTIVE", "").lower()
    parser.add_argument(
        "--allow-destructive",
        action="store_true",
        default=_destructive_env in ("1", "true", "yes"),
        help="Permit delete on Namespace / CRD / kube-system. Off by default.",
    )
    _docs_url_default = (
        os.getenv("FLUX_MCP_DOCS_SEARCH_URL")
        or RuntimeConfig.flux_docs_search_url
    )
    parser.add_argument(
        "--flux-docs-search-url",
        default=_docs_url_default,
        help=(
            "URL template for search_flux_docs. `{query}` is substituted with "
            "the URL-encoded query. Default hits GitHub code search."
        ),
    )

    args = parser.parse_args()

    set_config(
        RuntimeConfig(
            read_only=args.read_only,
            mask_secrets=args.mask_secrets,
            timeout_seconds=args.timeout,
            kubeconfig_path=args.kubeconfig,
            kube_context_override=args.kube_context,
            enabled_tools=[t.strip() for t in args.enabled_tools.split(",") if t.strip()],
            allow_destructive=args.allow_destructive,
            flux_docs_search_url=args.flux_docs_search_url,
        )
    )

    # Check environment variable for transport mode
    transport_mode = os.getenv("MCP_TRANSPORT_MODE", args.transport)

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stderr)
        ]
    )

    try:
        # Create server with dynamic tool loading
        server = DynamicMCPServer(
            name="flux-vanilla-mcp",
            tools_dir="src/tools"
        )

        # Load tools and start server
        server.load_tools()

        if transport_mode not in ["http", "stdio"]:
            raise ValueError(f"Invalid transport mode: {transport_mode}. Must be one of: http, or stdio")
        
        server.run(transport_mode=transport_mode, host=args.host, port=args.port)

    except KeyboardInterrupt:
        print("\nShutting down server...")
    except Exception as e:
        print(f"Server error: {e}", file=sys.stderr)
        sys.exit(1)


def dev() -> None:
    """Entry point for the 'dev' script."""
    sys.argv = ["dev", "--transport", "http"]
    main()


def start() -> None:
    """Entry point for the 'start' script."""
    sys.argv = ["start", "--transport", "stdio"]
    main()


if __name__ == "__main__":
    main()
