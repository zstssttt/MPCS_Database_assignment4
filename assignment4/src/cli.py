import argparse
import logging
import sys

from src import sync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("sync")


def main() -> None:
    """CLI entry point: parse the subcommand (init / full-load / incremental /
    validate) from argv and dispatch to the matching function in :mod:`sync`.
    Exits with code 0 on success, 1 on any failure (logged as an error).
    """
    parser = argparse.ArgumentParser(description="Sakila (MySQL) -> SQLite analytics sync")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Create analytics DB, verify MySQL, seed dim_date and sync_state")
    sub.add_parser("full-load", help="Load all source data into analytics DB")
    sub.add_parser("incremental", help="Load only new or changed data")
    v = sub.add_parser("validate", help="Verify consistency between MySQL and SQLite")
    v.add_argument("--from", dest="date_from")
    v.add_argument("--to", dest="date_to")

    args = parser.parse_args()

    try:
        if args.command == "init":
            sync.init()
            log.info("init completed: tables created, dim_date and sync_state ready.")
        elif args.command == "full-load":
            sync.full_load()
            log.info("full-load completed successfully.")
        elif args.command == "incremental":
            sync.incremental()
            log.info("incremental completed successfully.")
        elif args.command == "validate":
            sync.validate(date_from=args.date_from, date_to=args.date_to)
            log.info("validate completed successfully.")
        else:
            raise NotImplementedError(f"'{args.command}' not implemented yet (coming next step)")
        sys.exit(0)
    except Exception as e:
        log.error(f"{args.command} failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()