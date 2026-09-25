def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.command == "service":
        return _service(args.service_action)
    # serve (explicit or default when no subcommand given)
    try: