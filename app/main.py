from livekit import agents

from app.server import server


def main() -> None:
    agents.cli.run_app(server)


if __name__ == "__main__":
    main()

