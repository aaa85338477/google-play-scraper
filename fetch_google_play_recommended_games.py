from __future__ import annotations

import json

from scraper_services import fetch_google_play_games

OUTPUT_FILE = "google_play_recommended_games.json"


def main() -> None:
    games, metadata = fetch_google_play_games()
    payload = {
        **metadata,
        "games": games,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)

    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()