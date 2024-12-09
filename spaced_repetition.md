# Spaced Repetition Algorithms

## General Notes

- compromise between rate of review and rate of forgetting
  - requires metrics for both, tailored to specific categories of knowledge

## Questions

- How does "rate of understanding" differ from rate of (rote) retention?

## Implementations

### SM-0 (Wozniak)

- I(1) = 1 day
- I(2) = 7 days
- I(3) = 16 days
- I(4) = 35 days
- I(k) = 2 * I(k-1) for k > 4
- Forgotten items are "demoted" to new items for the first several levels

### SM-2 (Anki)

Refinement of SM-0 based on the concepts of an "ease factor" EF and a user-provided "quality grade" for each review. The lower the ease factor, the slower review intervals grow.

- I(1) = 1 day
- I(2) = 6 days
- I(k) = I(k-1) * EF for k > 2
  - EF := "Ease Factor", with initial value of 2.5
  - EF_new := EF_old + (0.1 - (5 - Q) * (0.08 + 0.02 * (5-Q)))
  - Q := "Quality grade of review", ranging from 0 - 5
    - 0 - 2: forgot
    - 3 - 5: remembered
- Forgotten items are demoted to level 1 with the same EF

### SM-4

Refinement of SM-2 based on the idea of an "OI matrix", a matrix of optimal review intervals dynamically updated with each review. For example, if a user waits 2 days past the recommended review period to review an item but still remembers it with a high grade, the corresponding entry in the OI matrix should be lengthened. The dimensions of the OI table are difficulty vs. number of repetitions applied so far.

## Models

### General Terms

t := time elapsed since last review
P := probability of recall for a single item
R := rate of retention, i.e., the average of P over a collection of items
S := "memory strength" or "memory stability", i.e., the time required for P to drop from 100% to 90%
S_n := value of S after n intervals
c_n := multiplicative adjustment factor for S after n intervals, so S_n = S_0 * c_1 * ... * c_{n-1}
D := some metric of the item's "difficulty" or "complexity"

### Forgetting Curve

The following model is inspired by a dataset gathered from the language-learning app MailMemo:

P = exp(t * ln(0.9) / S)

This can be refined by accounting for adjustments to S over time:

P_n = exp(t * ln(0.9) / (S_0 * c_1 * ... * c_{n-1}))

### Relationships Between Parameters

- As S increases, c decreases: memory stabilization becomes increasingly difficult
- As P_n decreases, c_n increases: successful recall at low retrieval probability leads to greater gains than at high retrieval probability
- As D increases, c decreases

## References

[^1]: https://github.com/open-spaced-repetition/fsrs4anki/wiki/spaced-repetition-algorithm:-a-three%E2%80%90day-journey-from-novice-to-expert
