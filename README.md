# Board Game Robot — Chess
**ENGR 353: Programmable Systems | Project II**

A robotic arm that physically plays chess against a human opponent. The robot uses the free [Stockfish](https://stockfishchess.org/) chess engine to decide its moves, then executes them on a real physical board using a 6-DOF robotic arm controlled by a Raspberry Pi.

---

## How It Works

The project is split into four layers. Each layer is independent — you can work on one without touching the others.

```
Human types their move
        ↓
[ chess_engine.py ]      Validates the move. Asks Stockfish for the robot's response.
        ↓
[ board_coordinates.py ] Converts a square name (e.g. "e4") to physical (x, y, z) coordinates in mm.
        ↓
[ arm_controller.py ]    Computes joint angles from coordinates (inverse kinematics). Drives servos.
        ↓
Physical arm moves the piece on the board
```

**The "seeing the board" problem:** The robot does not use a camera. Instead, the human types their move into the terminal (e.g. `e2e4`). The software maintains a perfect internal board state using python-chess, so it always knows where every piece is without needing any sensors.

---

## Project Status

| File | Status | Description |
|------|--------|-------------|
| `chess_engine.py` | ✅ Done | Chess logic, move validation, Stockfish integration |
| `game_controller.py` | ✅ Done | Main game loop, arm stub functions |
| `board_coordinates.py` | 🔲 Not started | Maps square names → physical (x, y, z) positions |
| `arm_controller.py` | 🔲 Not started | Inverse kinematics, servo control via GPIO |
| `config.py` | 🔲 Not started | Hardware configuration (pin numbers, arm dimensions, board origin) |

The chess logic is fully working and testable right now — no hardware needed. Run it on any machine with Python.

---

## Hardware

- **Platform:** Raspberry Pi (any model with GPIO)
- **Arm:** 6 DOF robotic arm (frame built, motors not yet installed)
- **End effector:** Gripper
- **Servo driver:** PCA9685 I2C board (recommended — controls all 6 servos over 2 wires)
- **Chess board:** Standard tournament size (57.15 mm squares) — not yet purchased

### Arm joint layout
```
Joint 1 — Base rotation (spins the whole arm left/right)
Joint 2 — Shoulder pitch (raises/lowers the upper arm)
Joint 3 — Elbow pitch
Joint 4 — Wrist pitch
Joint 5 — Wrist roll
Joint 6 — Gripper open/close
```
For chess, the wrist always points straight down, which simplifies the inverse kinematics significantly.

---

## Software Dependencies

Install on the Raspberry Pi:
```bash
pip install chess pigpio
sudo apt install stockfish
sudo systemctl enable pigpiod && sudo systemctl start pigpiod
```

For local development on Windows/Mac (no Pi needed):
```bash
pip install chess
# Download Stockfish from https://stockfishchess.org/download/
# Update STOCKFISH_PATH in chess_engine.py to point at the downloaded .exe
```

---

## Running the Code

### Play a game (software only, no arm)
```bash
python game_controller.py
```
This runs in **dry-run mode** by default. The arm actions are printed to the terminal instead of being executed. Safe to run on any machine — no Raspberry Pi or motors needed.

### Play a game (with real arm)
```bash
python game_controller.py --live
```
Only use `--live` once `arm_controller.py` is written and the motors are connected.

### How to enter moves
The game accepts two notation formats:

| Format | Example | Meaning |
|--------|---------|---------|
| UCI | `e2e4` | Move the piece from e2 to e4 |
| UCI | `e7e8q` | Move pawn from e7 to e8, promote to queen |
| SAN | `e4` | Pawn to e4 (standard chess notation) |
| SAN | `Nf3` | Knight to f3 |
| SAN | `O-O` | Kingside castle |
| SAN | `O-O-O` | Queenside castle |

Type `quit` at any time to exit.

---

## File-by-File Overview

### `chess_engine.py`
Contains the `ChessGame` class. Everything chess-related lives here.

Key methods:
- `parse_human_move(user_input)` — validates a typed move, returns a `chess.Move` or an error string
- `get_move_details(move)` — returns a dict with from/to squares, whether it's a capture, castling info, en passant info, and promotion info — everything `arm_controller.py` will need
- `get_best_move()` — launches Stockfish and returns its chosen move
- `push_move(move)` — applies a move to the internal board state (call this AFTER the arm finishes moving)
- `get_board_string()` — returns a labeled text representation of the board for the terminal

### `game_controller.py`
The main game loop. Ties everything together.

- Human always plays White. Robot always plays Black.
- The arm stub functions (`arm_pick_and_place`, `arm_remove_piece`) at the top of this file are the only things that need to change when `arm_controller.py` is ready. The game loop itself stays the same.
- Handles all special moves: captures, en passant, castling (moves both king and rook), and promotion (prints a reminder for the human to physically swap the piece).

### `board_coordinates.py` *(to be written)*
Will map chess square names to physical coordinates in millimeters.

What it needs:
- The position of the board origin (corner of a1) relative to the arm base
- The square size in mm (57.15 mm for standard boards)
- Three Z heights: travel height (above pieces), pick height (gripping), place height (releasing)

### `arm_controller.py` *(to be written)*
Will handle all hardware interaction.

What it needs to do:
- Inverse kinematics: given a target (x, y, z), compute the 6 joint angles
- Servo control: convert joint angles to PWM pulse widths and send them via PCA9685
- Motion sequencing: move smoothly between positions without knocking pieces over

### `config.py` *(to be written)*
Will hold all hardware constants in one place so nothing is hardcoded elsewhere. Things like:
- GPIO/I2C pin numbers
- Servo pulse width min/max for each joint
- Arm link lengths (needed for IK math)
- Board origin position and square size
- Graveyard positions (where captured pieces are dropped)

---

## Coordinate System

The arm's workspace uses a standard right-hand coordinate system:
- **Origin:** base center of the arm
- **X:** forward (toward the board)
- **Y:** left/right
- **Z:** up/down

Each chess square maps to a specific (x, y) position. Z changes depending on the action:
- `Z_TRAVEL` — safe height for moving between squares (above all pieces)
- `Z_GRIP` — height to close/open the gripper around a piece
- `Z_PLACE` — height to release a piece onto a square

These values get calibrated once the board is physically placed and the arm link lengths are known.

---

## Special Move Handling

| Move type | What the arm does |
|-----------|-------------------|
| Normal | Pick from source square, place on destination square |
| Capture | Remove captured piece to graveyard first, then move attacker |
| En passant | Captured pawn is NOT on the destination square — its actual location is computed separately |
| Castling | Move king, then move rook (two separate pick-and-place operations) |
| Promotion | Move pawn normally; print a reminder for the human to swap it for a queen |

---

## Next Steps

1. Measure arm link lengths once motors are mounted
2. Decide on and purchase servo motors + PCA9685 driver board
3. Write `config.py` with all hardware constants
4. Write `board_coordinates.py` with the square → coordinate mapping
5. Write `arm_controller.py` with IK math and servo control
6. Calibrate: position the arm at known squares and record the servo angles
7. Integration test: play a full game with the physical arm

---

## Contributing

If you're joining this project:
- All configuration (pin numbers, arm dimensions, etc.) will live in `config.py` — that's the first place to look if something hardware-related needs changing
- The chess logic in `chess_engine.py` does not need to change unless you want to adjust Stockfish's strength (change `THINK_TIME`) or add features like move history
- To swap in real arm control, find the two TODO comments in `game_controller.py` inside `arm_pick_and_place()` and `arm_remove_piece()` and replace them with calls to `arm_controller.py`
- Run `python game_controller.py` (dry-run mode) to test any changes without needing the physical hardware
