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

    const res = await fetch('/api/session/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ max_new: maxNew, max_reviews: maxReviews }),
    });
    const data = await res.json();

    if (data.queue_size === 0) {
        showFeedback('No cards due for review. Import some puzzles first!', 'info');
        return;
    }

    document.getElementById('start-panel').style.display = 'none';
    document.getElementById('session-panel').style.display = 'block';

    loadNextExercise();
}

async function endSession() {
    const res = await fetch('/api/session/end', { method: 'POST' });
    const data = await res.json();
    showSessionComplete(data.stats || {});
}

// ─── Exercise loading ──────────────────────────────────────────────

async function loadNextExercise() {
    exerciseActive = false;
    awaitingRating = false;
    hideFeedback();
    document.getElementById('rating-panel').style.display = 'none';
    document.getElementById('controls').style.display = 'flex';

    const res = await fetch('/api/session/next');
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

    // Submit to server
    const res = await fetch('/api/session/move', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ move: moveUci }),
    });
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
    const res = await fetch('/api/session/solution');
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
}

async function rateExercise(rating) {
    if (!awaitingRating) return;
    awaitingRating = false;

    // Disable buttons immediately
    const buttons = document.querySelectorAll('.rating-buttons .btn');
    buttons.forEach(b => b.disabled = true);

    const res = await fetch('/api/session/rate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rating: rating }),
    });
    const data = await res.json();

    // Show next review time briefly
    const nextText = document.getElementById('next-review-text');
    nextText.textContent = 'Next review: ' + data.next_review;
    nextText.style.display = 'block';

    // Load next exercise after brief pause
    await new Promise(resolve => setTimeout(resolve, 800));
    buttons.forEach(b => b.disabled = false);
    loadNextExercise();
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
