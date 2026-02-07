from dash import Dash, dcc, html
from pathlib import Path
import json
from collections import Counter
from matplotlib import pyplot as plt

DATA = Path(__file__).parent.joinpath("data/puzzle_history.10000.json")
if not DATA.exists():
    raise FileNotFoundError(f"Datafile not found: {DATA}")

puzzles = []
with DATA.open("r") as f:
    puzzles = list(map(json.loads, f.readlines()))

total, correct = Counter(), Counter()
for p in puzzles:
    total[round(p["puzzle"]["rating"], -2)] += 1
    if p["win"]:
        correct[round(p["puzzle"]["rating"], -2)] += 1

bins = list(range(round(min(total), -2), max(total) + 100, 100))
percent = [100 * correct[r] / total[r] for r in bins[:-1]]
fig = plt.stairs(percent, bins)

labels = [f"{b} - {b + 100}" for b in bins]
L = max(len(l) for l in labels)
labels = [l.ljust(L) for l in labels]
bars = [round(p) * "x" for p in percent]
for l, b in zip(labels, bars):
    print(f"{l}|{b}")


app = Dash()
app.layout = [
    html.Div(children="Percentages solved by rating bucket"),
    dcc.Graph(figure=fig),
]


if __name__ == "__main__":
    app.run(debug=True)
