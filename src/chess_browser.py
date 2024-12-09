# Importing Modules
import pygame
import chess, chess.svg
import requests
import rembg
from io import BytesIO
from pathlib import Path
from .constants import (
    GAME_WIDTH,
    GAME_HEIGHT,
    PIECE_SYMBOLS,
    PIECE_NAMES,
    SPRITE_WIDTH,
    SPRITE_HEIGHT,
    SQUARE_WIDTH,
)

# Initialising pygame module
# 0 - whites turn no selection: 1-whites turn piece selected: 2- black turn no selection, 3 - black turn piece selected
turn_step = 0
selection = 100
valid_moves = []

sprites = {True: {}, False: {}}
for piece_type, symbol in PIECE_NAMES.items():
    for color in ("white", "black"):
        img = Path(f"assets/pieces/{color}/{piece_type}.svg")
        if not img.exists():
            raise FileNotFoundError(f"File {img} not found")
        piece = chess.Piece.from_symbol(symbol)
        sprites[color == "white"][piece.piece_type] = pygame.transform.scale(
            pygame.image.load(img), (SPRITE_WIDTH, SPRITE_HEIGHT)
        )


# draw main game board
def draw_board(screen):
    screen.fill([255, 255, 255])
    font = pygame.font.Font("freesansbold.ttf", 20)
    medium_font = pygame.font.Font("freesansbold.ttf", 40)
    big_font = pygame.font.Font("freesansbold.ttf", 50)

    timer = pygame.time.Clock()
    fps = 60

    for i in range(32):
        column = i % 4
        row = i // 4
        if row % 2 == 0:
            pygame.draw.rect(
                screen,
                "light gray",
                [
                    6 * SQUARE_WIDTH - (column * 2 * SQUARE_WIDTH),
                    row * SQUARE_WIDTH,
                    SQUARE_WIDTH,
                    SQUARE_WIDTH,
                ],
            )
        else:
            pygame.draw.rect(
                screen,
                "light gray",
                [
                    7 * SQUARE_WIDTH - (column * 2 * SQUARE_WIDTH),
                    row * SQUARE_WIDTH,
                    SQUARE_WIDTH,
                    SQUARE_WIDTH,
                ],
            )
    pygame.draw.rect(screen, "gray", [0, 8 * SQUARE_WIDTH, GAME_WIDTH, SQUARE_WIDTH])
    pygame.draw.rect(screen, "gold", [0, 8 * SQUARE_WIDTH, GAME_WIDTH, SQUARE_WIDTH], 5)
    pygame.draw.rect(screen, "gold", [8 * SQUARE_WIDTH, 0, 200, GAME_HEIGHT], 5)
    status_text = [
        "White: Select a Piece to Move!",
        "White: Select a Destination!",
        "Black: Select a Piece to Move!",
        "Black: Select a Destination!",
    ]
    screen.blit(big_font.render(status_text[turn_step], True, "black"), (20, 820))
    for i in range(9):
        pygame.draw.line(screen, "black", (0, 100 * i), (800, 100 * i), 2)
        pygame.draw.line(screen, "black", (100 * i, 0), (100 * i, 800), 2)
    screen.blit(medium_font.render("FORFEIT", True, "black"), (810, 830))


def run_game():
    pygame.init()

    screen = pygame.display.set_mode([GAME_WIDTH, GAME_HEIGHT])
    pygame.display.set_caption("Chess Game")
    draw_board(screen)
    run = True
    while run:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                run = False
    pygame.quit()


if __name__ == "__main__":
    run_game()
