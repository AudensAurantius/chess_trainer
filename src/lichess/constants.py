import requests
import yaml
from os import getenv
from xml.etree import ElementTree as ETree
from .. import ASSETS, get_logger
from .models import Theme

logger = get_logger(__name__)

LICHESS_API = "https://lichess.org/api"
LICHESS_TOKEN = getenv("LICHESS_TOKEN")

PUZZLE_DIFFICULTIES = [
    "easiest",
    "easier",
    "normal",
    "harder",
    "hardest",
]


PUZZLE_THEMES_URL = "https://raw.githubusercontent.com/lichess-org/lila/refs/heads/master/translation/source/puzzleTheme.xml"
PUZZLE_THEMES_FILE = ASSETS.joinpath("themes.yaml")
PUZZLE_THEMES: dict[str, Theme] = {}


def get_difficulty(difficulty: str | int | None) -> str | None:
    if (
        isinstance(difficulty, str)
        and (name := difficulty.lower().strip()) in PUZZLE_DIFFICULTIES
    ):
        return name
    elif isinstance(difficulty, int) and 0 <= difficulty < len(PUZZLE_DIFFICULTIES):
        return PUZZLE_DIFFICULTIES[difficulty]
    else:
        return None


def get_puzzle_themes(
    refresh: bool = False,
    name_contains: str | None = None,
    desc_contains: str | None = None,
) -> list[Theme]:
    """Get a list of valid Lichess puzzle themes."""

    def valid(theme):
        result = True
        if name_contains is not None:
            result = result and name_contains.lower() in theme.name.lower()
        if desc_contains is not None:
            result = result and (
                desc_contains.lower() in theme.description.lower()
                or desc_contains.lower() in theme.summary.lower()
            )
        return result

    global PUZZLE_THEMES
    if refresh or not PUZZLE_THEMES_FILE.is_file():
        logger.info("Downloading puzzle themes from URL %s", PUZZLE_THEMES_URL)
        PUZZLE_THEMES.clear()
        response = requests.get(PUZZLE_THEMES_URL)
        response.raise_for_status()
        xml = ETree.fromstring(response.content.decode())
        themes = {}
        for node in xml.findall("string"):
            name = node.attrib.get("name")
            if name is not None and name.endswith("Description"):
                name = name.removesuffix("Description")
                themes.setdefault(name, {}).update(description=node.text, name=name)
            else:
                themes.setdefault(name, {}).update(summary=node.text, name=name)
        while themes:
            name, theme = themes.popitem()
            try:
                PUZZLE_THEMES[name] = Theme.from_dict(theme)
            except KeyError:
                # invalid theme (e.g., general information node)
                pass
        with PUZZLE_THEMES_FILE.open("w") as outfile:
            yaml.dump([theme.to_dict() for theme in PUZZLE_THEMES.values()], outfile)
    elif not PUZZLE_THEMES:
        logger.info("Reading puzzle themes from file %s", PUZZLE_THEMES_FILE)
        with PUZZLE_THEMES_FILE.open() as file:
            PUZZLE_THEMES = {
                theme.name: theme
                for theme in map(Theme.from_dict, yaml.safe_load(file))
            }
    return list(filter(valid, PUZZLE_THEMES.values()))


def get_valid_theme(theme: str) -> str | None:
    try:
        return next(
            name
            for name in get_puzzle_themes()
            if name.lower() == theme.lower().strip()
        )
    except StopIteration:
        return None
