"""
board_coordinates.py
--------------------
Converts chess square names (e.g. "e4") into physical (x, y) coordinates
in millimeters, relative to the robot arm's base frame.

HOW THIS FILE FITS IN THE PROJECT:
    chess_engine.py  → tells us WHICH squares to move between (e.g. "e2" → "e4")
    board_coordinates.py → converts those names to PHYSICAL POSITIONS in mm
    arm_controller.py → takes those mm positions and drives the servos

WHY SEPARATE FROM arm_controller.py?
    This file does only geometry — no motor code, no hardware.
    It can be tested and verified on any laptop without a robot attached.
    arm_controller.py then calls into this file when it needs real-world coordinates.

COORDINATE SYSTEM (matches config.py):
    Origin: center of square a1
    X: increases from a-file → h-file  (left → right when facing the board)
    Y: increases from rank 1 → rank 8  (near arm → far from arm)
    Z: not handled here — z heights are in config.py; arm_controller.py applies them

    File index:  a=0, b=1, c=2, d=3, e=4, f=5, g=6, h=7
    Rank index:  1=0, 2=1, 3=2, 4=3, 5=4, 6=5, 7=6, 8=7

    Example — square "e4":
        file 'e' → index 4  →  x = BOARD_ORIGIN_X + 4 * SQUARE_SIZE_MM
        rank '4' → index 3  →  y = BOARD_ORIGIN_Y + 3 * SQUARE_SIZE_MM

Dependencies:
    config.py  (SQUARE_SIZE_MM, BOARD_ORIGIN_X_MM, BOARD_ORIGIN_Y_MM,
                GRAVEYARD_WHITE_X_MM, etc.)
"""

from config import (
    SQUARE_SIZE_MM,         # side length of one square in mm (57.15 mm)
    BOARD_ORIGIN_X_MM,      # x of a1 center in arm frame (set after calibration)
    BOARD_ORIGIN_Y_MM,      # y of a1 center in arm frame (set after calibration)
    GRAVEYARD_WHITE_X_MM,   # x of white graveyard drop zone
    GRAVEYARD_WHITE_Y_MM,   # y of white graveyard drop zone
    GRAVEYARD_BLACK_X_MM,   # x of black graveyard drop zone
    GRAVEYARD_BLACK_Y_MM,   # y of black graveyard drop zone
)


def square_to_mm(square: str) -> tuple[float, float]:
    """
    Convert a chess square name to physical (x, y) coordinates in millimeters.

    Parameters:
        square : a two-character string like "e4", "a1", or "h8"
                 First character = file letter (a–h)
                 Second character = rank digit (1–8)

    Returns:
        (x_mm, y_mm) — the center of that square in arm frame millimeters

    Raises:
        ValueError if the square string is not a valid chess square

    Example:
        square_to_mm("a1") → (BOARD_ORIGIN_X_MM, BOARD_ORIGIN_Y_MM)
        square_to_mm("b1") → (BOARD_ORIGIN_X_MM + 57.15, BOARD_ORIGIN_Y_MM)
        square_to_mm("a2") → (BOARD_ORIGIN_X_MM, BOARD_ORIGIN_Y_MM + 57.15)
        square_to_mm("e4") → (BOARD_ORIGIN_X_MM + 4*57.15, BOARD_ORIGIN_Y_MM + 3*57.15)
    """
    # ── Input validation ──────────────────────────────────────────────────────
    # A valid square is exactly 2 characters: a letter (a–h) then a digit (1–8).
    # We check this explicitly so errors are caught early with a clear message.
    if len(square) != 2:
        raise ValueError(f"Invalid square '{square}': must be exactly 2 characters (e.g. 'e4')")

    file_char = square[0].lower()   # the file letter — force lowercase so 'E4' works too
    rank_char  = square[1]          # the rank digit

    if file_char not in "abcdefgh":
        raise ValueError(f"Invalid square '{square}': file must be a–h, got '{file_char}'")

    if rank_char not in "12345678":
        raise ValueError(f"Invalid square '{square}': rank must be 1–8, got '{rank_char}'")

    # ── Compute file and rank indices ─────────────────────────────────────────
    # ord() returns the ASCII integer for a character.
    # ord('a') = 97, so ord('e') - ord('a') = 4 — the 0-based column index.
    file_index = ord(file_char) - ord('a')   # a→0, b→1, ..., h→7

    # The rank digit is a character ('1'–'8'), so subtract '1' to get 0-based index.
    rank_index = int(rank_char) - 1          # '1'→0, '2'→1, ..., '8'→7

    # ── Compute (x, y) in mm ─────────────────────────────────────────────────
    # a1 is the origin. Each step right adds SQUARE_SIZE_MM to x.
    # Each step away from the arm adds SQUARE_SIZE_MM to y.
    x_mm = BOARD_ORIGIN_X_MM + file_index * SQUARE_SIZE_MM   # x grows left→right (a→h)
    y_mm = BOARD_ORIGIN_Y_MM + rank_index * SQUARE_SIZE_MM   # y grows near→far  (1→8)

    return x_mm, y_mm


def graveyard_mm(color: str) -> tuple[float, float]:
    """
    Return the (x, y) drop position of the graveyard zone for a given piece color.

    The graveyard is an off-board area where captured pieces are deposited.
    We keep two separate zones so captured white and black pieces don't pile together.

    Parameters:
        color : "white" or "black"
                (same string that arm_remove_piece() uses in game_controller.py)

    Returns:
        (x_mm, y_mm) — center of the appropriate graveyard drop zone

    Raises:
        ValueError if color is not "white" or "black"

    Example usage in arm_controller.py:
        x, y = graveyard_mm("black")
        # move arm to (x, y) at GRAVEYARD_Z_MM to deposit a captured black piece
    """
    if color == "white":
        # White graveyard: the zone for pieces that the ROBOT (Black) has captured
        # (i.e., White pieces that have been taken off the board)
        return GRAVEYARD_WHITE_X_MM, GRAVEYARD_WHITE_Y_MM

    elif color == "black":
        # Black graveyard: the zone for pieces that the HUMAN (White) has captured
        return GRAVEYARD_BLACK_X_MM, GRAVEYARD_BLACK_Y_MM

    else:
        raise ValueError(f"Invalid color '{color}': must be 'white' or 'black'")


def board_square_names() -> list[str]:
    """
    Return all 64 square names in order from a1 to h8.

    Useful for testing, printing the board layout, or iterating all squares.
    Order: rank 1 first (a1, b1, ... h1), then rank 2, ..., then rank 8.

    Example output: ['a1', 'b1', 'c1', ..., 'h1', 'a2', ..., 'h8']
    """
    squares = []
    for rank in "12345678":              # iterate ranks 1→8
        for file in "abcdefgh":          # iterate files a→h within each rank
            squares.append(file + rank)  # build the square name, e.g. 'e4'
    return squares


# ── Self-test ─────────────────────────────────────────────────────────────────
# Run this file directly to verify coordinate math before connecting hardware:
#     python board_coordinates.py
#
# With placeholder origins at (0, 0):
#     a1 → (  0.00,   0.00)  ← this is the origin by definition
#     h1 → (400.05,   0.00)  ← 7 * 57.15 = 400.05
#     a8 → (  0.00, 400.05)  ← 7 * 57.15 = 400.05
#     h8 → (400.05, 400.05)  ← far corner of the board
if __name__ == "__main__":

    print("=== board_coordinates.py self-test ===\n")

    # Print the four corner squares to verify the geometry is correct
    corners = ["a1", "h1", "a8", "h8"]
    print("Corner squares:")
    for sq in corners:
        x, y = square_to_mm(sq)
        print(f"  {sq}  →  x={x:7.2f} mm,  y={y:7.2f} mm")

    print()

    # Print a few key squares for sanity checking
    spot_checks = ["e1", "e4", "e8", "d4", "d5"]
    print("Spot-check squares:")
    for sq in spot_checks:
        x, y = square_to_mm(sq)
        print(f"  {sq}  →  x={x:7.2f} mm,  y={y:7.2f} mm")

    print()

    # Print graveyard positions
    print("Graveyard drop zones:")
    for color in ("white", "black"):
        x, y = graveyard_mm(color)
        print(f"  {color:5s} graveyard  →  x={x:7.2f} mm,  y={y:7.2f} mm")

    print()

    # Print the full board layout as a grid
    print("Full board coordinate grid (x, y in mm):")
    print(f"  {'':4s}", end="")
    for file in "abcdefgh":
        print(f"  {file:^13s}", end="")     # column headers
    print()

    for rank in "87654321":                  # top of board (rank 8) first, matches how a board looks
        print(f"  {rank} ", end="")
        for file in "abcdefgh":
            x, y = square_to_mm(file + rank)
            print(f"  ({x:6.1f},{y:5.1f})", end="")   # compact (x,y) pair
        print()                             # newline after each rank

    print("\n=== All checks passed ===")
