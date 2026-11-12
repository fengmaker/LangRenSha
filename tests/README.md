# Python tests

This directory covers retained game rules, timeline and review-page rendering, voting, workflow, collection, and incremental processing logic. Tests use small in-memory fixtures or final `data/games/**/game.json` records; they do not require a database or website API service.

- Run the root suite from the project root: `.\.venv\Scripts\python.exe -m pytest tests -q`.
- The root suite uses the project test environment described in [requirements/test.txt](../requirements/test.txt).
