from __future__ import annotations

import json

from scraper_services import fetch_app_store_games

OUTPUT_FILE = "latest_us_app_store_games.json"


def main() -> None:
    games = fetch_app_store_games()
    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(games, file, ensure_ascii=False, indent=2)

    print(f"Saved {len(games)} records to {OUTPUT_FILE}")
    if games:
        print(json.dumps(games[0], ensure_ascii=False, indent=2))
    else:
        print("No game data was returned.")


if __name__ == "__main__":
    main()
