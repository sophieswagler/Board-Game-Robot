"""
game_controller.py
------------------
Main game loop for the chess-playing robot.

HOW THIS FILE FITS IN THE PROJECT:
    This is the "orchestrator." It ties together:
        chess_engine.py   → knows chess rules and generates moves
        arm_controller.py → (not yet written) will physically move the robot arm

    You can think of this file as the "game referee." It:
        1. Shows the board to the human player
        2. Accepts and validates the human's move
        3. Tells the arm to physically execute that move
        4. Asks Stockfish (via chess_engine.py) what the robot wants to play
        5. Tells the arm to physically execute the robot's move
        6. Repeats until someone wins or the game draws

HARDWARE STATUS:
    The arm controller is not written yet (motors not installed).
    Right now, the arm functions in this file are STUBS — they just print
    what the arm would do instead of sending real motor commands.
    When arm_controller.py is ready, you only need to replace 2–3 lines
    in the stub functions below. Everything else stays the same.

HOW TO RUN:
    python game_controller.py            ← dry-run mode (default, no arm movement)
    python game_controller.py --live     ← live mode (requires arm_controller.py + motors)
"""

import argparse                     # standard library module for parsing command-line flags
import sys                          # standard library module — used for sys.exit() to stop the program cleanly
from chess_engine import ChessGame  # our chess logic wrapper defined in chess_engine.py


# ─────────────────────────────────────────────────────────────────────────────
# ARM STUB FUNCTIONS
# These three functions are placeholders. Each one prints what the arm WOULD do.
#
# HOW TO UPGRADE LATER:
#   When arm_controller.py is written, replace the `print(...)` lines inside
#   the `if dry_run:` blocks with the real arm_controller function calls.
#   The rest of the code (game loop, logic, etc.) does NOT need to change.
# ─────────────────────────────────────────────────────────────────────────────

def arm_pick_and_place(from_sq: str, to_sq: str, dry_run: bool = True):
    """
    Tell the arm to pick up a piece from one square and place it on another.

    This is the most common arm action — used for every normal move.

    Parameters:
        from_sq  : source square name, e.g. "e2" (where the piece currently is)
        to_sq    : destination square name, e.g. "e4" (where it should go)
        dry_run  : if True, just print the action — don't send motor commands

    Physical sequence the arm should eventually do (in order):
        1. Move arm above from_sq at a safe travel height (avoid hitting pieces)
        2. Lower arm down to the piece
        3. Close gripper to grab the piece
        4. Raise arm back up to travel height
        5. Move arm above to_sq
        6. Lower arm down to the board
        7. Open gripper to release the piece
        8. Raise arm back up to travel height (home/idle position)
    """
    if dry_run:
        # Dry-run: just announce the intended movement
        print(f"  [ARM] Pick from {from_sq} → place on {to_sq}")
    else:
        # TODO: Replace this block with a real arm_controller call, e.g.:
        #   import arm_controller
        #   arm_controller.pick_and_place(from_sq, to_sq)
        raise NotImplementedError("Real arm control not implemented yet. Run without --live flag.")


def arm_remove_piece(square: str, color: str, dry_run: bool = True):
    """
    Tell the arm to remove a captured piece from the board and put it in the graveyard.

    The "graveyard" is a designated area off the side of the board where taken pieces go.
    We have two graveyard zones — one for captured White pieces, one for captured Black pieces.

    Parameters:
        square   : the square the captured piece is sitting on, e.g. "d5"
        color    : "white" or "black" — tells the arm which graveyard zone to use
        dry_run  : if True, just print the action

    WHY REMOVE BEFORE MOVING THE ATTACKER?
        The arm needs physical space to set a piece down. If we moved the attacker
        to the destination first, it would land on top of the captured piece.
        So: always remove the captured piece first, then move the attacker.
    """
    if dry_run:
        print(f"  [ARM] Remove {color} piece from {square} → graveyard")
    else:
        # TODO: Replace with real arm_controller call, e.g.:
        #   arm_controller.remove_to_graveyard(square, color)
        raise NotImplementedError("Real arm control not implemented yet. Run without --live flag.")


def arm_execute_move(game: ChessGame, move, player_label: str, dry_run: bool = True):
    """
    Given a validated chess move, determine what physical actions the arm needs
    to take and execute them in the correct order.

    This function handles all four special cases in chess that require non-obvious
    arm movements:
        1. Normal move:  just pick up and place (the simple case)
        2. Capture:      remove the captured piece FIRST, then move the attacker
        3. En passant:   the captured pawn is NOT on the destination square — must
                         compute its actual location before removing it
        4. Castling:     two pieces move — king first, then the rook
        5. Promotion:    pawn reaches back rank — human must physically swap the pawn
                         for a queen (or other piece). We print a reminder.

    Parameters:
        game         : the ChessGame object (so we can call get_move_details)
        move         : the chess.Move to execute
        player_label : "Human" or "Robot" — just for printing
        dry_run      : passed through to the arm stub functions
    """
    # IMPORTANT: get_move_details() must be called BEFORE push_move().
    # Once the board updates, captured pieces are gone and we can't query them anymore.
    details = game.get_move_details(move)

    # Print a summary line so the human can follow along
    print(f"\n  [{player_label} move: {details['from_square']} → {details['to_square']}]")

    # ── Special case: Pawn promotion ──────────────────────────────────────────
    # When a pawn reaches the back rank, the physical piece on the board needs to be
    # swapped for a queen (the piece Stockfish will almost always promote to).
    # The arm can move the pawn to the square normally — the human swaps it afterward.
    if details["is_promotion"]:
        print(f"  [PROMOTION] Pawn promotes to {details['promotion_to']}.")
        print(f"              >> Operator: please swap the pawn on {details['to_square']} for a {details['promotion_to']}.")

    # ── Special case: Capture ─────────────────────────────────────────────────
    # If this move takes an opponent's piece, the arm must remove it from the board
    # before placing the moving piece on that square (otherwise two pieces occupy one square).
    # For en passant, details["captured_square"] will be different from details["to_square"].
    if details["is_capture"]:
        # board.turn is True for White, False for Black.
        # The CAPTURED piece belongs to the OPPOSITE color of whoever is moving.
        captured_color = "black" if game.board.turn else "white"
        arm_remove_piece(details["captured_square"], captured_color, dry_run=dry_run)

    # ── Always: move the main piece ───────────────────────────────────────────
    # For castling, this moves the KING. The rook gets moved separately below.
    # For normal moves and captures, this is the only piece that moves.
    arm_pick_and_place(details["from_square"], details["to_square"], dry_run=dry_run)

    # ── Special case: Castling ────────────────────────────────────────────────
    # After moving the king, the rook must also be repositioned.
    # get_move_details() already calculated the rook's from/to squares for us.
    if details["is_castling"]:
        print(f"  [CASTLING] Also moving rook: {details['rook_from']} → {details['rook_to']}")
        arm_pick_and_place(details["rook_from"], details["rook_to"], dry_run=dry_run)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN GAME LOOP
# ─────────────────────────────────────────────────────────────────────────────

def play_game(dry_run: bool = True):
    """
    Run a complete chess game from the opening position to game over.

    PLAYER ASSIGNMENTS:
        Human → plays White (always moves first in chess)
        Robot → plays Black (Stockfish decides its moves)

    The loop alternates between human input and Stockfish analysis until one
    side wins or the game draws. After each move, the physical arm (or arm stub)
    executes the corresponding piece movement on the real board.

    Parameters:
        dry_run : if True, arm actions are only printed (safe for software testing).
                  if False, arm_controller.py must be available and motors must be connected.
    """
    # ── Print startup banner ──────────────────────────────────────────────────
    print("=" * 50)
    print("  Chess Robot — ENGR 353 Project II")
    print(f"  Mode: {'DRY RUN (no arm movement)' if dry_run else 'LIVE (arm active)'}")
    print("  You play White. Robot plays Black.")
    print("  Enter moves in UCI format (e.g. e2e4) or SAN (e.g. e4, Nf3, O-O).")
    print("  Type 'quit' to exit at any time.")
    print("=" * 50)

    # ── Initialize the game ───────────────────────────────────────────────────
    # ChessGame() sets up the board and stores the Stockfish path.
    # If Stockfish is missing, it won't fail here — only when get_best_move() is called.
    try:
        game = ChessGame()
    except Exception as e:
        # Something went wrong during initialization (shouldn't happen normally)
        print(f"Error initializing game: {e}")
        sys.exit(1)  # sys.exit(1) means "exited with an error" (non-zero = error by convention)

    # ── Main loop ─────────────────────────────────────────────────────────────
    # Keep going until checkmate, stalemate, or draw.
    # is_game_over() checks all termination conditions automatically.
    while not game.is_game_over():

        # Show the board and whose turn it is at the start of every iteration
        print(f"\nMove {game.get_fullmove_number()} — {game.get_turn_string()} to play")
        print(game.get_board_string())

        # ── Human's turn (White) ──────────────────────────────────────────────
        # game.board.turn is chess.WHITE (True) when it's White's turn
        if game.board.turn:

            # Inner loop: keep asking for input until we get a valid, legal move.
            # This handles typos, illegal moves, etc. without crashing.
            while True:
                try:
                    raw = input("\n  Your move: ").strip()  # wait for the human to type something
                except (KeyboardInterrupt, EOFError):
                    # KeyboardInterrupt = user pressed Ctrl+C
                    # EOFError = input stream ended (e.g. running from a script with piped input)
                    print("\nGame interrupted.")
                    sys.exit(0)  # sys.exit(0) means "exited cleanly, no error"

                # Allow the human to quit mid-game
                if raw.lower() in ("quit", "exit", "q"):
                    print("Game aborted.")
                    sys.exit(0)

                # Try to parse the typed string into a legal chess move
                move, error = game.parse_human_move(raw)

                if error:
                    # Invalid or illegal move — tell the human why and ask again
                    print(f"  Invalid: {error}")
                    continue  # go back to the top of the while True loop

                # Move is valid — send it to the arm (real or simulated)
                arm_execute_move(game, move, player_label="Human", dry_run=dry_run)

                # IMPORTANT ORDER: push AFTER arm executes so the arm reads pre-move board state
                game.push_move(move)
                break  # valid move accepted — exit the inner while loop and continue the game

        # ── Robot's turn (Black) ──────────────────────────────────────────────
        else:
            print("\n  Robot is thinking...")

            try:
                # Ask Stockfish to analyze the current position and return its best move.
                # This may take up to THINK_TIME seconds (default 1.0s).
                robot_move = game.get_best_move()
            except RuntimeError as e:
                # Stockfish binary is missing — print install instructions and stop
                print(f"\nError: {e}")
                sys.exit(1)

            # Send the robot's move to the arm (real or simulated)
            arm_execute_move(game, robot_move, player_label="Robot", dry_run=dry_run)

            # Update the internal board state to reflect the robot's move
            game.push_move(robot_move)

    # ── Game over ─────────────────────────────────────────────────────────────
    # The while loop exited because is_game_over() returned True.
    # Show the final board state and the result.
    print("\n" + "=" * 50)
    print("  GAME OVER")
    print(f"  {game.get_game_result()}")   # e.g. "Checkmate — White wins!"
    print("=" * 50)
    print(game.get_board_string())         # show the final board position


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# This block only runs when you execute this file directly:
#     python game_controller.py
# It does NOT run if another file imports game_controller (e.g. in tests).
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":

    # Set up command-line argument parsing.
    # argparse reads sys.argv (the words after "python game_controller.py") automatically.
    parser = argparse.ArgumentParser(
        description="Chess Robot game controller — ENGR 353 Project II"
    )

    parser.add_argument(
        "--live",
        action="store_true",   # if --live is present, args.live = True; if absent, args.live = False
        help=(
            "Enable real arm movement. Requires arm_controller.py to be written and motors to be connected. "
            "Default (without this flag) is dry-run mode: arm actions are printed but not executed."
        )
    )

    args = parser.parse_args()  # actually parse the command line — fills in args.live

    # dry_run is the OPPOSITE of --live:
    #   python game_controller.py           → dry_run=True  (safe, software-only)
    #   python game_controller.py --live    → dry_run=False (real hardware)
    play_game(dry_run=not args.live)
