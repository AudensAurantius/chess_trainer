// Chess Trainer — Training page interaction

let board = null;
let game = null;
let playerColor = 'white';
let exerciseActive = false;
let awaitingRating = false;

// ─── Session control ───────────────────────────────────────────────

async function startSession() {
    const maxNew = parseInt(document.getElementById('max-new').value) || 10;
    const maxReviews = parseInt(document.getElementById('max-reviews').value) || 50;
    const tagsInput = document.getElementById('include-tags').value.trim();
    const includeTags = tagsInput ? tagsInput.split(',').map(t => t.trim()).filter(t => t) : null;

    try {
        const body = { max_new: maxNew, max_reviews: maxReviews };
        if (includeTags && includeTags.length > 0) {
            body.include_tags = includeTags;
        }
        const res = await fetch('/api/session/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });

        if (!res.ok) {
            const text = await res.text();
            console.error('Start session failed:', res.status, text);
            showStartFeedback('Failed to start session (server error).', 'error');
            return;
        }

        const data = await res.json();

        if (data.queue_size === 0) {
            showStartFeedback('No cards due for review. <a href="/import">Import some puzzles</a> first!', 'info');
            return;
        }

        document.getElementById('start-panel').style.display = 'none';
        document.getElementById('session-panel').style.display = 'block';

        loadNextExercise();
    } catch (error) {
        console.error('Error starting session:', error);
        showStartFeedback('Failed to start session: ' + error.message, 'error');
    }
}

async function endSession() {
    try {
        const res = await fetch('/api/session/end', { method: 'POST' });
        if (!res.ok) {
            console.error('End session failed:', res.status);
            return;
        }
        const data = await res.json();
        showSessionComplete(data.stats || {});
    } catch (error) {
        console.error('Error ending session:', error);
    }
}

// ─── Exercise loading ──────────────────────────────────────────────

async function loadNextExercise() {
    exerciseActive = false;
    awaitingRating = false;
    hideFeedback();
    document.getElementById('rating-panel').style.display = 'none';
    document.getElementById('controls').style.display = 'flex';

    try {
        const res = await fetch('/api/session/next');
        if (!res.ok) {
            console.error('Load next exercise failed:', res.status);
            showFeedback('Failed to load exercise.', 'error');
            return;
        }
        const data = await res.json();

        if (data.status === 'complete') {
            showSessionComplete(data.stats || {});
            return;
        }

        // Update header
        document.getElementById('progress-text').textContent =
            'Exercise ' + data.exercise_num;
        document.getElementById('remaining-text').textContent =
            data.remaining + ' remaining';
        document.getElementById('challenge-text').textContent = data.challenge;

        // Display game context if available (own-game exercises)
        const contextEl = document.getElementById('game-context');
        if (data.game_context) {
            contextEl.textContent = formatGameContext(data.game_context);
            contextEl.style.display = 'block';
        } else {
            contextEl.style.display = 'none';
        }

        // Determine player color from side to move
        playerColor = data.side_to_move === 'White' ? 'white' : 'black';

        // Initialize chess.js with the position
        game = new Chess(data.fen);

        // Initialize or update chessboard
        const boardConfig = {
            position: data.fen,
            orientation: playerColor,
            draggable: true,
            pieceTheme: '/static/vendor/img/chesspieces/wikipedia/{piece}.png',
            onDragStart: onDragStart,
            onDrop: onDrop,
            onSnapEnd: onSnapEnd,
        };

        if (board === null) {
            board = Chessboard('board', boardConfig);
        } else {
            board.orientation(playerColor);
            board.position(data.fen, false);
            // Re-enable dragging
            board = Chessboard('board', boardConfig);
        }

        exerciseActive = true;
    } catch (error) {
        console.error('Error loading exercise:', error);
        showFeedback('Failed to load exercise: ' + error.message, 'error');
    }
}

// ─── Board interaction ─────────────────────────────────────────────

function onDragStart(source, piece, position, orientation) {
    if (!exerciseActive) return false;

    // Only allow dragging own pieces
    if (playerColor === 'white' && piece.search(/^b/) !== -1) return false;
    if (playerColor === 'black' && piece.search(/^w/) !== -1) return false;

    // Only allow legal moves
    const moves = game.moves({ square: source, verbose: true });
    if (moves.length === 0) return false;

    return true;
}

async function onDrop(source, target) {
    // Construct UCI move
    let moveUci = source + target;

    // Check for promotion
    const piece = game.get(source);
    if (piece && piece.type === 'p') {
        const targetRank = target.charAt(1);
        if ((piece.color === 'w' && targetRank === '8') ||
            (piece.color === 'b' && targetRank === '1')) {
            moveUci += 'q'; // Auto-promote to queen
        }
    }

    // Validate locally with chess.js first
    const localMove = game.move({
        from: source,
        to: target,
        promotion: 'q',
    });
    if (localMove === null) return 'snapback';

    try {
        // Submit to server
        const res = await fetch('/api/session/move', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ move: moveUci }),
        });

        if (!res.ok) {
            console.error('Submit move failed:', res.status);
            game.undo();
            return 'snapback';
        }

        const data = await res.json();

        if (!data.valid) {
            game.undo();
            return 'snapback';
        }

        if (data.finished) {
            exerciseActive = false;

            if (data.correct) {
                showFeedback(data.feedback || 'Correct!', 'correct');
                // If there's an opponent move to animate first
                if (data.opponent_move) {
                    await animateOpponentMove(data.opponent_move);
                }
            } else {
                showFeedback(data.feedback || 'Incorrect.', 'wrong');
            }

            // Show solution and rating panel
            await showSolutionAndRate();
        } else {
            // Correct but more moves needed
            showFeedback(data.feedback || 'Correct! Keep going...', 'correct');

            if (data.opponent_move) {
                await animateOpponentMove(data.opponent_move);
            }
        }
    } catch (error) {
        console.error('Error submitting move:', error);
        game.undo();
        return 'snapback';
    }
}

function onSnapEnd() {
    board.position(game.fen());
}

async function animateOpponentMove(moveUci) {
    // Small delay for visual effect
    await new Promise(resolve => setTimeout(resolve, 300));

    const from = moveUci.substring(0, 2);
    const to = moveUci.substring(2, 4);
    const promotion = moveUci.length > 4 ? moveUci.charAt(4) : undefined;

    game.move({ from, to, promotion });
    board.position(game.fen(), true); // animate = true
}

// ─── Solution & Rating ─────────────────────────────────────────────

async function showSolution() {
    exerciseActive = false;
    await showSolutionAndRate();
}

async function showSolutionAndRate() {
    try {
        const res = await fetch('/api/session/solution');
        if (!res.ok) {
            console.error('Get solution failed:', res.status);
            return;
        }
        const data = await res.json();

        if (data.solution_san) {
            document.getElementById('solution-text').textContent =
                'Solution: ' + data.solution_san;
        }

        // Animate to final position
        if (data.final_fen) {
            game = new Chess(data.final_fen);
            board.position(data.final_fen, true);
        }

        document.getElementById('rating-panel').style.display = 'block';
        document.getElementById('controls').style.display = 'none';
        awaitingRating = true;
    } catch (error) {
        console.error('Error getting solution:', error);
    }
}

async function rateExercise(rating) {
    if (!awaitingRating) return;
    awaitingRating = false;

    // Disable buttons immediately
    const buttons = document.querySelectorAll('.rating-buttons .btn');
    buttons.forEach(b => b.disabled = true);

    try {
        const res = await fetch('/api/session/rate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ rating: rating }),
        });

        if (!res.ok) {
            console.error('Rate exercise failed:', res.status);
            buttons.forEach(b => b.disabled = false);
            awaitingRating = true;
            return;
        }

        const data = await res.json();

        // Show next review time briefly
        const nextText = document.getElementById('next-review-text');
        nextText.textContent = 'Next review: ' + data.next_review;
        nextText.style.display = 'block';

        // Load next exercise after brief pause
        await new Promise(resolve => setTimeout(resolve, 800));
        buttons.forEach(b => b.disabled = false);
        loadNextExercise();
    } catch (error) {
        console.error('Error rating exercise:', error);
        buttons.forEach(b => b.disabled = false);
        awaitingRating = true;
    }
}

// ─── Session complete ──────────────────────────────────────────────

function showSessionComplete(stats) {
    document.getElementById('session-panel').style.display = 'none';
    document.getElementById('start-panel').style.display = 'none';

    const panel = document.getElementById('complete-panel');
    panel.style.display = 'block';

    const statsHtml = `
        <div class="stat-card">
            <div class="stat-value">${stats.exercises_shown || 0}</div>
            <div class="stat-label">Exercises</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">${stats.correct || 0}</div>
            <div class="stat-label">Correct</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">${stats.incorrect || 0}</div>
            <div class="stat-label">Incorrect</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">${(stats.accuracy || 0).toFixed(1)}%</div>
            <div class="stat-label">Accuracy</div>
        </div>
    `;
    document.getElementById('session-stats').innerHTML = statsHtml;
}

// ─── UI helpers ────────────────────────────────────────────────────

function showFeedback(message, type) {
    const el = document.getElementById('feedback-area');
    el.textContent = message;
    el.className = 'feedback feedback-' + type;
    el.style.display = 'block';
}

function hideFeedback() {
    document.getElementById('feedback-area').style.display = 'none';
}

function showStartFeedback(message, type) {
    const el = document.getElementById('start-feedback');
    el.innerHTML = message;
    el.className = 'feedback feedback-' + type;
    el.style.display = 'block';
}

function formatGameContext(ctx) {
    const parts = [];
    if (ctx.player_color) {
        parts.push('You played as ' + ctx.player_color.charAt(0).toUpperCase() + ctx.player_color.slice(1));
    }
    if (ctx.opponent) {
        parts.push('vs ' + ctx.opponent);
    }
    if (ctx.time_control) {
        parts.push('(' + ctx.time_control + ')');
    }
    if (ctx.game_date) {
        parts.push(ctx.game_date);
    }
    return parts.join(' ');
}
