# Chess Trainer

## Summary

This project aims to create a chess trainer which combines the best aspects of several existing tools and platforms, including:

- [Lichess tactics trainer](https://lichess.org/training)
- [Chessable](https://www.chessable.com/)
- [Chess Endgame Training app](https://play.google.com/store/apps/details?id=com.supertorpe.chessendgametraining&hl=en_US)
- [Anki flashcards](https://apps.ankiweb.net/)
- The ["Woodpecker Method"](https://www.chess.com/blog/SheldonOfOsaka/the-woodpecker-method-a-review) for tactics training

Specifically, the types of chess training this app is intended to support are:

- Opening theory;
- Tactics training;
- Theoretical endgame drills;
- Strategic drills that test understanding of key positional ideas, sourced from chess books, analysis of master games, Chessable courses, and the like;
- Use of spaced repetition across all exercise types to reinforce pattern recognition and learning.

## Goals and Overall Vision

There are three main goals:

1. Reducing cognitive load by eliminating the need for context-switching to support different types of training;
1. Increasing the overall effectiveness of training by forcing the user to identify the type of position in each drill--i.e., tactical, theoretical, or strategic / positional--before solving it; and
1. Maximizing the efficiency of training using spaced-repetition and adaptive drilling techniques.

## Key Problems

### Lack of Public APIs

As far as I can tell, Lichess is the only platform among those listed above with a well-documented public API for fetching puzzles, games, and related metadata.  Thus, in order to fully support endgame, positional, and opening training, I'll need to either identify comparable platforms with public APIs, or build my own database of such positions, along with a corresponding framework for importing new positions for training from chess literature in various forms.

- Lack of Chessable API
- Ingestion of chess books and commentary in different forms:
  - PDFs: potentially requires an optical character recognition component, especially for older works written using descriptive notation
  - PGNs
