    sub = parser.add_subparsers(dest="command")
    svc = sub.add_parser("service", help="Start/stop/restart the server service.")
    svc.add_argument("service_action", choices=["start", "stop", "restart"])
    serve = sub.add_parser("serve", help="Run the MCP server (default).")
    parser.add_argument(