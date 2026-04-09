"""
config.py
---------
All hardware constants for the chess robot in one place.

WHY A SEPARATE CONFIG FILE?
    If numbers are scattered across chess_engine.py, arm_controller.py, etc.,
    changing one physical measurement means hunting through every file.
    Instead, every number that describes the real world lives here.
    All other files import what they need from this file.

HOW TO USE:
    from config import SQUARE_SIZE_MM, BOARD_ORIGIN_MM, TRAVEL_Z_MM

WHEN TO EDIT THIS FILE:
    - When you physically measure the board placement relative to the arm base
    - When you buy/receive the chess board and confirm the square size
    - When you install motors and determine servo channel assignments
    - When you calibrate the arm link lengths

COORDINATE SYSTEM:
    We use a right-handed 3D coordinate system centered at the arm's base.

          Z (up)
          |
          |______ Y (away from arm, toward board)
         /
        X (to the right, along the a→h file direction)

    The chess board is placed in front of the arm so that:
        - a1 is the nearest-left corner square (closest to the arm base)
        - h1 is the nearest-right corner square
        - a8 is the far-left corner square (farthest from arm)
        - h8 is the far-right corner square

    This means:
        - Increasing X  →  moving from a-file toward h-file
        - Increasing Y  →  moving from rank 1 toward rank 8 (away from arm)
        - Increasing Z  →  moving upward

    If your physical setup is different (e.g., a8 is nearest), swap or negate
    axes in board_coordinates.py rather than changing all the arm code.
"""

# ── Board Dimensions ──────────────────────────────────────────────────────────

# Side length of one square in millimeters.
# 57.15 mm = 2.25 inches, the accepted North American tournament standard.
# FIDE official recommendation is 60 mm (2.375"). Update this if your board differs.
# The full 8×8 playable area is: 8 × SQUARE_SIZE_MM = 457.2 mm per side.
SQUARE_SIZE_MM: float = 57.15

# ── Board Origin ──────────────────────────────────────────────────────────────
# Position of the CENTER of square a1 in the arm's coordinate frame (mm).
#
# HOW TO CALIBRATE:
#   1. Place the board in its permanent position in front of the arm.
#   2. Manually jog the arm tip to the center of a1.
#   3. Read off the (x, y, z) from your servo/encoder readings.
#   4. Replace the zeros below with those measured values.
#
# Until the arm is built and motors are installed, these are placeholder zeros.
# The BOARD_ORIGIN_Z is the z-height of the board surface (top of the board).
BOARD_ORIGIN_X_MM: float = 0.0    # placeholder — measure after physical setup
BOARD_ORIGIN_Y_MM: float = 0.0    # placeholder — measure after physical setup
BOARD_ORIGIN_Z_MM: float = 0.0    # placeholder — height of board surface from arm base

# Height from the bottom of the base to the shoulder joint pivot center.
# Measured: 3.5 inches = 88.9 mm ≈ 89 mm.
# This is the vertical offset added to all z calculations — the shoulder is the
# origin of the 2-link planar IK, so everything is measured relative to it.
BASE_TO_SHOULDER_MM: float = 89.0  # 3.5 inches, measured 2026-04-09

# ── Piece Heights (from diagram, standard Staunton for 2.25" squares) ─────────
# These are reference heights for a standard tournament Staunton set.
# Source: Official Staunton sizing chart for a 57.15mm (2.25") square board.
# Used to set arm travel height and to decide gripper grab height per piece type.
PIECE_HEIGHT_PAWN_MM:   float = 44.0   # ~1.75" — shortest piece, sets minimum grab height
PIECE_HEIGHT_ROOK_MM:   float = 64.0   # ~2.50"
PIECE_HEIGHT_KNIGHT_MM: float = 70.0   # ~2.75" — estimated; knights vary by set
PIECE_HEIGHT_BISHOP_MM: float = 76.0   # ~3.00"
PIECE_HEIGHT_QUEEN_MM:  float = 89.0   # ~3.50"
PIECE_HEIGHT_KING_MM:   float = 95.0   # ~3.75" — tallest piece; drives TRAVEL_Z_MM

# ── Z-Height Levels ───────────────────────────────────────────────────────────
# The arm operates at three distinct heights during a piece move:
#
#   TRAVEL_Z:  Safe cruising altitude. High enough to clear all standing pieces.
#              King = 95 mm + 35 mm safety margin = 130 mm.
#              The arm moves horizontally at this height between pick and place.
#
#   PLACE_Z:   Height at which the gripper opens to release a piece.
#              Should be just above the board surface — a few mm gap so the piece
#              seats itself under gravity without the arm slamming it down.
#
#   GRAB_Z:    Height at which the gripper closes to grab a piece.
#              Set to mid-height of the shortest piece (pawn at 44mm → grab at ~22mm).
#              arm_controller.py may refine this per piece type once physically tested.
#
# All values are ABSOLUTE z in the arm's frame, NOT relative to BOARD_ORIGIN_Z.
# Add BOARD_ORIGIN_Z to these if your origin is not at the board surface.
TRAVEL_Z_MM: float = 130.0   # king (95mm) + 35mm clearance — update after measuring arm reach
PLACE_Z_MM:  float = 5.0     # just above board surface to release cleanly; tune after testing
GRAB_Z_MM:   float = 22.0    # mid-height of a pawn (44mm / 2); tune per piece after testing

# ── Graveyard Positions ───────────────────────────────────────────────────────
# The graveyard is the off-board area where captured pieces are deposited.
# We keep two zones: one for captured White pieces, one for captured Black pieces.
#
# Each value is the (x, y) center of the graveyard drop zone in mm.
# The arm will deposit captured pieces at GRAVEYARD_Z_MM height.
#
# Layout suggestion (adjust to your physical table setup):
#   White graveyard: to the LEFT of the board (negative X side)
#   Black graveyard: to the RIGHT of the board (positive X side)
GRAVEYARD_WHITE_X_MM: float = -80.0   # placeholder — left of board
GRAVEYARD_WHITE_Y_MM: float = 200.0   # placeholder — mid-depth of board
GRAVEYARD_BLACK_X_MM: float = 540.0   # placeholder — right of board (457mm board + margin)
GRAVEYARD_BLACK_Y_MM: float = 200.0   # placeholder — mid-depth of board
GRAVEYARD_Z_MM:       float = 30.0    # placeholder — height to release piece into graveyard

# ── Arm Link Lengths ──────────────────────────────────────────────────────────
# The physical length of each rigid segment of the robot arm, in millimeters.
# These are used by arm_controller.py for inverse kinematics (IK) calculations.
#
# A 6-DOF arm typically has these segments (proximal → distal):
#   BASE    : the rotating base (no translation; rotation only)
#   SHOULDER: from shoulder joint to elbow joint
#   ELBOW   : from elbow joint to wrist joint
#   WRIST   : from wrist joint to gripper tip
#
# !! IMPORTANT !!
#   These values are placeholders (0.0). You MUST measure the physical arm
#   once motors are installed and record the true link lengths here.
#   Wrong link lengths will cause the IK solver to command wrong positions.
LINK_SHOULDER_MM: float = 102.0  # shoulder pivot → elbow pivot; measured 4 inches (2026-04-09)
LINK_ELBOW_MM:    float = 114.0  # elbow pivot → wrist pivot; derived 4.5 inches from total check (2026-04-09)
LINK_WRIST_MM:    float = 178.0  # wrist pivot → gripper tip (closed); measured 7 inches (2026-04-09)

# ── Servo Driver: Two Options ─────────────────────────────────────────────────
#
# OPTION A — PCA9685 (recommended for 6+ servos):
#   A small I2C board that generates hardware PWM for up to 16 servos.
#   Plugs into Pi via 4 wires (VCC, GND, SDA, SCL). Servos plug into the board.
#   Buy one if you don't have it: search "PCA9685 servo driver" (~$5).
#
# OPTION B — Direct GPIO via pigpio (no extra hardware needed):
#   The Pi can drive servos straight from its GPIO pins using the pigpio library.
#   pigpio uses DMA (Direct Memory Access) to generate accurate PWM without
#   blocking the CPU. Accurate enough for hobby servos.
#   Install: sudo apt install pigpio python3-pigpio && sudo pigpiod
#
# arm_controller.py will auto-detect which option is available and use it.
# ─────────────────────────────────────────────────────────────────────────────

# ── Option A: PCA9685 Settings ────────────────────────────────────────────────
PCA9685_I2C_ADDRESS: int = 0x40  # default I2C address; check solder jumpers if changed
PCA9685_PWM_FREQ_HZ: int = 50   # 50 Hz = standard servo frequency (20ms period)

# PCA9685 channel numbers (which slot each servo plugs into on the board, 0–15)
SERVO_CH_BASE:        int = 0  # base rotation — sweeps arm left/right
SERVO_CH_SHOULDER:    int = 1  # shoulder pitch — lifts arm up/down
SERVO_CH_ELBOW:       int = 2  # elbow pitch — bends forearm
SERVO_CH_WRIST_PITCH: int = 3  # wrist pitch — keeps gripper pointing straight down
SERVO_CH_WRIST_ROLL:  int = 4  # wrist roll — fixed for chess
SERVO_CH_GRIPPER:     int = 5  # gripper open/close

# ── Option B: Direct GPIO Pin Assignments (BCM numbering) ─────────────────────
# BCM pin numbers are the GPIO numbers printed on pinout diagrams (NOT the physical pin numbers).
# These avoid I2C (GPIO 2,3), SPI (GPIO 9,10,11), and UART (GPIO 14,15) pins.
# Swap these if any pins are already in use on your Pi.
GPIO_PIN_BASE:        int = 17  # BCM 17 = physical pin 11
GPIO_PIN_SHOULDER:    int = 27  # BCM 27 = physical pin 13
GPIO_PIN_ELBOW:       int = 22  # BCM 22 = physical pin 15
GPIO_PIN_WRIST_PITCH: int = 23  # BCM 23 = physical pin 16
GPIO_PIN_WRIST_ROLL:  int = 24  # BCM 24 = physical pin 18
GPIO_PIN_GRIPPER:     int = 25  # BCM 25 = physical pin 22

# SERVO PULSE WIDTH RANGE (microseconds):
#   These define the minimum and maximum pulse widths for your specific servos.
#   Typical hobby servos: 500–2500 µs (0°–180°).
#   Check your servo datasheet — exceeding the range can strip gears.
# Servo model: Deegoo-FPV MG996R digital high-torque servo
#   Operating voltage: 4.8V – 7.2V (use 5V supply)
#   Stall torque:      9.4 kg/cm @ 4.8V,  11 kg/cm @ 6V
#   Stall current:     up to 2.5A per servo — MUST use separate power supply, NOT Pi 5V pin
#   PWM frequency:     50 Hz (standard)
#   Pulse width range: 500 µs (0°) to 2500 µs (180°)
SERVO_PULSE_MIN_US: int = 500    # 0°   position — confirmed for MG996R
SERVO_PULSE_MAX_US: int = 2500   # 180° position — confirmed for MG996R

# ── Gripper ───────────────────────────────────────────────────────────────────
# Servo angle (degrees, 0–180) for gripper fully open vs. fully closed.
# "Closed" should grip the thinnest piece (a pawn) without crushing it.
# Adjust after physical testing with your specific gripper and pieces.
GRIPPER_OPEN_DEG:   float = 90.0   # placeholder — gripper wide open, safe travel position
GRIPPER_CLOSED_DEG: float = 45.0   # placeholder — gripper clamped on a pawn-width piece
