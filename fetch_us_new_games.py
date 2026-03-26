from __future__ import annotations

import json

from scraper_services import fetch_app_store_games

OUTPUT_FILE = "latest_us_app_store_games.json"


def main() -> None:
    games, metadata = fetch_app_store_games()
    payload = {
        **metadata,
        "games": games,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)

    print(
        f"Saved {metadata['filtered_count']} verified games "
        f"from {metadata['raw_count']} App Store candidates to {OUTPUT_FILE}"
    )
    if games:
        print(json.dumps(games[0], ensure_ascii=False, indent=2))
    else:
        print("No verified game data was returned.")


if __name__ == "__main__":
    main()