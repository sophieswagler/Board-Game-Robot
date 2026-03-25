"""
chess_engine.py
---------------
Handles all chess logic: board state, move validation, and Stockfish integration.
Completely independent of hardware — safe to run on any machine for testing.

HOW THIS FILE FITS IN THE PROJECT:
    This is the "brain" layer. It knows chess rules and uses an AI engine to
    decide moves. It does NOT know anything about the physical robot.
    game_controller.py calls into this file, then passes the result to
    arm_controller.py (which will handle actual motor movement).

CHESS CONCEPTS USED HERE:
    - Board state: which pieces are on which squares at any point in the game
    - UCI notation: a move format like "e2e4" meaning "from e2, move to e4"
    - SAN notation: a human-friendly format like "e4" or "Nf3" (what you'd write on a scoresheet)
    - Capture: a move where one piece takes another off the board
    - En passant: a special pawn capture where the captured pawn is NOT on the destination square
    - Castling: a special move where the king and a rook swap positions simultaneously
    - Promotion: when a pawn reaches the opposite back rank, it becomes a queen (or other piece)

Dependencies:
    pip install chess
    sudo apt install stockfish       (on Raspberry Pi)
    -- OR on Windows for testing --
    Download stockfish from https://stockfishchess.org/download/ and set STOCKFISH_PATH below
"""

import chess         # the python-chess library — handles all board logic, rules, and notation
import chess.engine  # sub-module of python-chess specifically for communicating with chess engines
                     # (Stockfish uses the UCI protocol, which chess.engine speaks)

# ── Constants ────────────────────────────────────────────────────────────────

# Path to the Stockfish binary (the actual chess-playing program).
# Stockfish is a separate executable — python-chess just talks to it via stdin/stdout.
# On Raspberry Pi after `sudo apt install stockfish`, it lands at /usr/games/stockfish.
# On Windows for local testing, download from stockfishchess.org and update this path.
STOCKFISH_PATH = "/usr/games/stockfish"   # e.g. r"C:\Users\sophi\stockfish\stockfish.exe" on Windows

# How many seconds Stockfish gets to think before it must pick a move.
# 1.0 second is strong enough for a class demo. Increase for harder play, decrease for faster games.
# Stockfish can search millions of positions per second, so even 0.1s gives decent play.
THINK_TIME = 1.0


class ChessGame:
    """
    Manages one complete chess game from start to finish.

    This class wraps the python-chess library to give us a clean interface.
    python-chess does the heavy lifting: it knows every chess rule, tracks
    the full board state, and can validate any move. We just call its methods.

    The board internally represents each square as an integer 0–63 (a1=0, h8=63).
    We convert to/from human-readable strings like "e2" using helper functions.
    """

    def __init__(self, stockfish_path: str = STOCKFISH_PATH, think_time: float = THINK_TIME):
        """
        Set up a new game. Called once at the start.

        chess.Board() automatically places all 32 pieces in their starting positions
        and sets it to White's turn, move 1, with full castling rights and no en passant.
        """
        # The board object holds the entire game state.
        # Every time a move is made (push_move), this object updates automatically.
        self.board = chess.Board()

        # Store these so they can be overridden in tests or via command-line args
        self.stockfish_path = stockfish_path  # where to find the Stockfish binary
        self.think_time = think_time          # seconds Stockfish can think per move

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 1: Move Input and Validation
    # ─────────────────────────────────────────────────────────────────────────

    def parse_human_move(self, user_input: str):
        """
        Convert a string typed by the human into a chess.Move object.

        WHY TWO FORMATS?
            UCI ("e2e4") is easy for a program to generate — just two square names.
            SAN ("e4", "Nf3", "O-O") is what humans write in chess books and scoresheets.
            We support both so the operator can type either naturally.

        RETURN VALUE:
            (move, None)      if the move is valid and legal
            (None, "message") if the input is bad — caller prints the message and asks again

        Note: "valid" means the string parsed correctly.
              "legal" means the move is actually allowed in the current position.
              A move can be valid but illegal (e.g., "e2e4" on move 50 when that pawn has moved).
        """
        raw = user_input.strip()  # remove any accidental spaces or newlines the user typed

        # ── Attempt 1: Parse as UCI (e.g. "e2e4", "g1f3", "e7e8q" for promotion) ──
        # UCI is the simplest format: just source square + destination square + optional promotion piece.
        # chess.Move.from_uci() converts the string to a Move object without checking legality.
        try:
            move = chess.Move.from_uci(raw)   # raises InvalidMoveError if string isn't valid UCI

            # self.board.legal_moves is a generator of every move currently allowed.
            # We check if our parsed move is in that set.
            if move in self.board.legal_moves:
                return move, None  # success — return the move with no error message
            else:
                # The string was valid UCI syntax but the move isn't allowed right now.
                # Example: "e2e4" is valid UCI but illegal if White's e2 pawn already moved.
                return None, f"'{raw}' is not a legal move right now."

        except chess.InvalidMoveError:
            # The string doesn't look like UCI at all (e.g. user typed "Nf3" instead of "g1f3")
            pass  # fall through and try parsing as SAN instead

        # ── Attempt 2: Parse as SAN (e.g. "Nf3", "exd5", "O-O", "O-O-O") ──
        # SAN is trickier: "e4" could mean different things depending on which pawns can move there.
        # parse_san() uses the current board state to figure out which piece is moving.
        # It ALSO checks legality, so we don't need a separate legal_moves check.
        try:
            move = self.board.parse_san(raw)  # raises errors for invalid or illegal input
            return move, None  # success

        except chess.InvalidMoveError:
            # The string doesn't match any known move format
            return None, f"'{raw}' is not a valid move format. Use UCI (e.g. e2e4) or SAN (e.g. Nf3)."

        except chess.AmbiguousMoveError:
            # The SAN string could refer to more than one piece.
            # Example: two rooks can both move to e1, so "Re1" is ambiguous.
            # The fix is to add the source file/rank: "Rae1" or "Rce1".
            return None, f"'{raw}' is ambiguous — add more detail (e.g. Rae1 instead of Re1)."

        except chess.IllegalMoveError:
            # The string was valid SAN syntax but the move isn't allowed in this position
            return None, f"'{raw}' is an illegal move in this position."

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 2: Move Metadata (for the arm controller)
    # ─────────────────────────────────────────────────────────────────────────

    def get_move_details(self, move: chess.Move) -> dict:
        """
        Return a dictionary with everything the arm needs to know about a move,
        BEFORE that move is applied to the board.

        WHY BEFORE?
            Once we call board.push(move), the board updates immediately.
            Captured pieces disappear, castling rights change, en passant info is cleared.
            So we must extract all the physical details FIRST, then push.

        WHAT THE ARM NEEDS TO KNOW:
            - Which square to pick up FROM
            - Which square to place the piece ON
            - Is there a piece to remove first (capture)?
            - WHERE is the captured piece (may not be the destination square — en passant!)
            - Does the arm need to move a second piece (castling involves the rook too)?
            - Did a pawn promote (human needs to physically swap pieces)?

        Returns a dict with keys described below.
        """
        details = {}  # start with an empty dict, fill in each field below

        # ── Basic from/to squares ──
        # move.from_square and move.to_square are integers (0–63).
        # chess.square_name() converts them to strings like "e2" or "g8".
        details["from_square"] = chess.square_name(move.from_square)  # e.g. "e2"
        details["to_square"]   = chess.square_name(move.to_square)    # e.g. "e4"

        # ── What piece is moving ──
        # board.piece_at(square) returns a Piece object (or None if the square is empty).
        # piece.piece_type is an integer constant: PAWN=1, KNIGHT=2, BISHOP=3, ROOK=4, QUEEN=5, KING=6.
        # chess.piece_name() converts that to a lowercase string like "pawn" or "knight".
        piece = self.board.piece_at(move.from_square)
        details["piece_type"] = chess.piece_name(piece.piece_type) if piece else "unknown"

        # ── Is this a capture? ──
        # board.is_capture() returns True for both normal captures AND en passant.
        # We use this rather than checking board.piece_at(to_square) ourselves, because
        # en passant captures a pawn that is NOT on the destination square.
        details["is_capture"] = self.board.is_capture(move)

        # ── WHERE is the captured piece? ──
        # For normal captures: the captured piece is sitting on to_square.
        # For en passant: the captured pawn is on a DIFFERENT square (same file as to_square,
        #                 same rank as from_square). The arm needs the actual square to go there.
        if self.board.is_en_passant(move):
            # EN PASSANT EXAMPLE:
            #   White pawn on e5, Black pawn on d5. White plays e5→d6 (en passant).
            #   The Black pawn being captured is on d5, NOT d6 (the destination).
            #   So we compute: file = d (from to_square d6), rank = 5 (from from_square e5).
            ep_rank = chess.square_rank(move.from_square)  # rank of the capturing pawn (0-indexed, so rank 5 = index 4)
            ep_file = chess.square_file(move.to_square)    # file of the destination square (d = index 3)
            captured_sq = chess.square(ep_file, ep_rank)   # combine file + rank → square integer
            details["captured_square"] = chess.square_name(captured_sq)  # e.g. "d5"

        elif details["is_capture"]:
            # Normal capture: piece being taken is right on the destination square
            details["captured_square"] = details["to_square"]

        else:
            # Not a capture at all — no piece to remove
            details["captured_square"] = None

        # ── Is this castling? ──
        # Castling means the king slides two squares toward a rook, and the rook
        # jumps over to the other side of the king. The arm must move BOTH pieces.
        # board.is_castling() returns True for both kingside (O-O) and queenside (O-O-O).
        details["is_castling"] = self.board.is_castling(move)

        if details["is_castling"]:
            # Figure out which squares the rook starts and ends on
            rook_from, rook_to = self._get_castling_rook_squares(move)
            details["rook_from"] = chess.square_name(rook_from)  # e.g. "h1"
            details["rook_to"]   = chess.square_name(rook_to)    # e.g. "f1"
        else:
            details["rook_from"] = None  # not castling, no rook to move
            details["rook_to"]   = None

        # ── Is this a pawn promotion? ──
        # When a pawn reaches the opponent's back rank (rank 8 for White, rank 1 for Black),
        # it must be replaced by a queen, rook, bishop, or knight.
        # move.promotion is None for normal moves, or a piece-type integer for promotions.
        # Stockfish will automatically choose queen (the strongest option) for the robot's moves.
        # For human moves, UCI format encodes the promotion piece: "e7e8q" = pawn to e8, becomes queen.
        details["is_promotion"] = (move.promotion is not None)

        if details["is_promotion"]:
            # Convert the piece-type integer to a string like "queen"
            details["promotion_to"] = chess.piece_name(move.promotion)
        else:
            details["promotion_to"] = None  # not a promotion

        return details  # return the fully filled-in dictionary

    def _get_castling_rook_squares(self, move: chess.Move):
        """
        Helper method: figure out where the rook starts and ends during a castling move.

        CASTLING RULES:
            Kingside  (O-O):   King moves from e1 → g1. Rook moves from h1 → f1.
            Queenside (O-O-O): King moves from e1 → c1. Rook moves from a1 → d1.
            (Same logic for Black, but on rank 8 instead of rank 1.)

        python-chess represents castling as the KING's move only (e1→g1 or e1→c1).
        We reconstruct the rook's squares from that.

        The underscore prefix (_) is a Python convention meaning "private method" —
        it's only used internally by this class, not called from outside.
        """
        # square_rank() returns 0 for rank 1, 7 for rank 8.
        # We need this to find the correct rank for the rook squares.
        rank = chess.square_rank(move.from_square)  # 0 = White's back rank, 7 = Black's back rank

        # square_file() returns 0 for a-file, 7 for h-file.
        # The king ends on g-file (index 6) for kingside, c-file (index 2) for queenside.
        if chess.square_file(move.to_square) == 6:
            # KINGSIDE CASTLING: king goes to g-file, so rook goes from h-file to f-file
            rook_from = chess.square(7, rank)   # h1 (White) or h8 (Black) — file 7, rank 0 or 7
            rook_to   = chess.square(5, rank)   # f1 (White) or f8 (Black) — file 5, rank 0 or 7
        else:
            # QUEENSIDE CASTLING: king goes to c-file, so rook goes from a-file to d-file
            rook_from = chess.square(0, rank)   # a1 (White) or a8 (Black) — file 0, rank 0 or 7
            rook_to   = chess.square(3, rank)   # d1 (White) or d8 (Black) — file 3, rank 0 or 7

        return rook_from, rook_to  # both are integer square indices

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 3: Applying Moves to the Board
    # ─────────────────────────────────────────────────────────────────────────

    def push_move(self, move: chess.Move):
        """
        Apply a move to the internal board, updating all game state.

        WHEN TO CALL THIS:
            Call push_move() AFTER get_move_details() and AFTER the arm has
            physically moved the piece. Order matters:
              1. get_move_details(move)   ← read board state before it changes
              2. arm executes the move    ← physical piece moves on the board
              3. push_move(move)          ← software board state catches up

        WHAT board.push() DOES:
            - Moves the piece on the internal board
            - Removes any captured piece
            - Updates whose turn it is
            - Updates castling rights (e.g. if king or rook moves, can't castle that side)
            - Updates the en passant target square (set if a pawn just moved two squares)
            - Increments the move counters
        """
        self.board.push(move)  # all the above happens in this one call — python-chess handles it

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 4: Stockfish Integration (the chess AI)
    # ─────────────────────────────────────────────────────────────────────────

    def get_best_move(self) -> chess.Move:
        """
        Launch Stockfish, give it the current board position, and get its best move.

        HOW STOCKFISH WORKS:
            Stockfish is a separate program (not a Python library) that we talk to
            via a protocol called UCI (Universal Chess Interface). UCI is a text-based
            protocol: we send commands like "position fen <board_state>" and "go movetime 1000",
            and Stockfish replies with "bestmove e2e4".
            python-chess's SimpleEngine class handles all the UCI plumbing for us.

        CONTEXT MANAGER (with ... as engine):
            The `with` block starts Stockfish as a subprocess when we enter it,
            and cleanly shuts it down (sending the "quit" command) when we leave.
            This prevents orphaned Stockfish processes from piling up.

        Returns a chess.Move object for the best move Stockfish found.
        Raises RuntimeError if the Stockfish binary can't be found.
        """
        try:
            # popen_uci() starts the Stockfish executable as a child process.
            # It sets up the UCI handshake automatically.
            with chess.engine.SimpleEngine.popen_uci(self.stockfish_path) as engine:

                # engine.play() sends the current board position to Stockfish and asks for a move.
                # chess.engine.Limit(time=...) tells Stockfish how long it can think.
                # Other limit options include: depth (search X moves ahead), nodes (X positions evaluated).
                result = engine.play(self.board, chess.engine.Limit(time=self.think_time))

                # result.move is the chess.Move Stockfish chose as its best option
                return result.move

        except FileNotFoundError:
            # The Stockfish binary doesn't exist at the path we gave it
            raise RuntimeError(
                f"Stockfish not found at '{self.stockfish_path}'.\n"
                "  On Pi:      sudo apt install stockfish\n"
                "  On Windows: download from stockfishchess.org and update STOCKFISH_PATH in chess_engine.py"
            )

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 5: Game-Over Detection
    # ─────────────────────────────────────────────────────────────────────────

    def is_game_over(self) -> bool:
        """
        Return True if the game has ended for any reason.

        python-chess checks all termination conditions automatically:
            - Checkmate: the player to move is in check with no legal moves
            - Stalemate: the player to move has no legal moves but is NOT in check (draw)
            - Insufficient material: neither side has enough pieces to force checkmate (draw)
            - 75-move rule: 75 moves without a pawn move or capture (draw by rule)
            - Fivefold repetition: same position appeared 5 times (draw by rule)
        """
        return self.board.is_game_over()  # True if any of the above conditions are met

    def get_game_result(self) -> str:
        """
        Return a readable string describing how the game ended and who won.

        Should only be called after is_game_over() returns True.
        """
        outcome = self.board.outcome()  # returns a chess.Outcome object, or None if still playing

        if outcome is None:
            return "Game is still in progress."  # shouldn't happen if called correctly

        # outcome.termination is an enum like chess.Termination.CHECKMATE
        # .name gives us the string "CHECKMATE", .replace and .title() make it "Checkmate"
        termination = outcome.termination.name.replace("_", " ").title()

        # outcome.winner is chess.WHITE (True), chess.BLACK (False), or None (draw)
        if outcome.winner is chess.WHITE:
            return f"{termination} — White wins!"
        elif outcome.winner is chess.BLACK:
            return f"{termination} — Black wins!"
        else:
            return f"{termination} — Draw."  # stalemate, insufficient material, etc.

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 6: Display Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def get_board_string(self) -> str:
        """
        Return a text representation of the board, with rank numbers and file letters.

        WHY ADD LABELS?
            str(self.board) gives a raw 8x8 grid, but no labels — hard to read.
            We add rank numbers (1–8) on the left and file letters (a–h) at the bottom,
            matching standard chess notation so the operator knows where "e4" is.

        PIECE SYMBOLS:
            Uppercase = White pieces: P N B R Q K
            Lowercase = Black pieces: p n b r q k
            Dot (.) = empty square

        Example output:
            8  r n b q k b n r
            7  p p p p p p p p
            6  . . . . . . . .
            5  . . . . . . . .
            4  . . . . P . . .
            3  . . . . . . . .
            2  P P P P . P P P
            1  R N B Q K B N R

               a b c d e f g h
        """
        # str(self.board) produces 8 lines, one per rank, from rank 8 (top) to rank 1 (bottom)
        rows = str(self.board).split("\n")  # split the multi-line string into a list of 8 strings

        labeled_rows = []
        for i, row in enumerate(rows):
            # i=0 corresponds to rank 8 (the top of the board), i=7 to rank 1
            rank_number = 8 - i
            labeled_rows.append(f"  {rank_number}  {row}")  # prepend the rank number

        labeled_rows.append("")                       # blank line to visually separate the board from the labels
        labeled_rows.append("     a b c d e f g h")  # file labels, spaced to align with the board columns

        return "\n".join(labeled_rows)  # join all lines back into one multi-line string

    def get_turn_string(self) -> str:
        """
        Return whose turn it is as a readable string: "White" or "Black".

        In python-chess, board.turn is the constant chess.WHITE (True) or chess.BLACK (False).
        """
        return "White" if self.board.turn == chess.WHITE else "Black"

    def get_fullmove_number(self) -> int:
        """
        Return the current full-move number.

        A "full move" in chess counts one move by each player.
        So after White plays move 1 and Black plays move 1, the number increments to 2.
        Starts at 1 at the beginning of the game.
        """
        return self.board.fullmove_number
