from __future__ import annotations

import sys


def main() -> int | None:
    """Console-script entrypoint.

    The historical CLI lives in ``swarm.cli``.  This wrapper adds lightweight
    top-level commands that must work before the full runtime is constructed.
    """
    if len(sys.argv) > 1 and sys.argv[1] == "doctor":
        from swarm.doctor import main as doctor_main

        return doctor_main(sys.argv[2:])

    from swarm import cli as cli_module

    if hasattr(cli_module, "memory") and "memory" not in cli_module.cli.commands:
        cli_module.cli.add_command(cli_module.memory, "memory")

    return cli_module.cli()


if __name__ == "__main__":
    raise SystemExit(main())
