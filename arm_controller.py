"""
arm_controller.py
-----------------
Drives the physical robot arm to pick up and place chess pieces.

HOW THIS FILE FITS IN THE PROJECT:
    chess_engine.py      → decides which squares to move between
    board_coordinates.py → converts square names to (x, y) mm positions
    arm_controller.py    → YOU ARE HERE: math + servo commands
    game_controller.py   → calls pick_and_place() and remove_to_graveyard()

WHAT THIS FILE DOES:
    1. Inverse kinematics (IK): converts a 3D target position (x, y, z) in mm
       into angles for all 6 servo joints.
    2. Smooth motion: uses cubic polynomial interpolation so servos ramp up and
       slow down instead of snapping instantly (inspired by Adrianoxzzz/ChessRobotArm).
    3. Servo control: sends PWM signals via either PCA9685 or direct GPIO pigpio.
    4. Chess moves: pick_and_place() and remove_to_graveyard() orchestrate the
       full sequence of arm movements for each type of chess action.

ARM JOINTS (6 total):
    0 — Base rotation    : sweeps arm left/right in the horizontal plane
    1 — Shoulder pitch   : lifts the upper arm up/down
    2 — Elbow pitch      : bends the forearm relative to the upper arm
    3 — Wrist pitch      : auto-computed to keep gripper pointing straight down
    4 — Wrist roll       : fixed at 0° for chess (no gripper spin needed)
    5 — Gripper          : opens and closes to grab/release pieces

HARDWARE AUTO-DETECTION:
    This file tries hardware drivers in this order:
        1. PCA9685 via adafruit ServoKit (best — dedicated PWM chip, most stable)
        2. lgpio library on Raspberry Pi GPIO (modern replacement for pigpio)
        3. Dry-run fallback (prints commands, no hardware — works on Windows)

SMOOTH MOTION (cubic polynomial):
    Instead of commanding a servo to jump instantly to a new angle, we interpolate
    using a cubic polynomial that starts and ends with zero velocity:
        θ(t) = θ_start + a2·t² + a3·t³
        a2 = 3·Δθ / tf²        (Δθ = angle change, tf = movement duration)
        a3 = −2·Δθ / tf³
    This guarantees the arm accelerates smoothly and decelerates to a stop,
    which prevents jerk, reduces mechanical stress, and makes the motion look natural.

IK OVERVIEW (2R planar + base rotation):
    With the wrist always pointing straight down:
        θ_base     = atan2(x, y)                 → aim arm at target direction
        θ_shoulder + θ_elbow = 2R IK in (r, z)  → reach the correct distance/height
        θ_wrist_pitch = −90° − (θ_shoulder + θ_elbow)  → keep gripper vertical

CALIBRATION:
    Each servo is mounted at some physical orientation. SERVO_ZERO and SERVO_DIR
    below map mathematical angles to physical servo PWM angles.
    See the calibration section for how to set these.

HOW TO HOOK INTO game_controller.py:
    In arm_pick_and_place() and arm_remove_piece(), replace the TODO lines with:
        import arm_controller
        arm_controller.pick_and_place(from_sq, to_sq)
        arm_controller.remove_to_graveyard(square, color)

Dependencies (Raspberry Pi):
    OPTION A (PCA9685): pip install adafruit-circuitpython-servokit adafruit-blinka
    OPTION B (GPIO):    lgpio is pre-installed on modern Raspberry Pi OS (no setup needed)
"""

import math   # atan2, acos, sqrt, pi — used throughout the IK solver
import time   # sleep() pauses used during smooth motion steps

from config import (
    # Arm geometry
    LINK_SHOULDER_MM, LINK_ELBOW_MM, LINK_WRIST_MM, BASE_TO_SHOULDER_MM,

    # Movement heights
    TRAVEL_Z_MM, GRAB_Z_MM, PLACE_Z_MM, GRAVEYARD_Z_MM,

    # PCA9685 channel numbers (Option A)
    SERVO_CH_BASE, SERVO_CH_SHOULDER, SERVO_CH_ELBOW,
    SERVO_CH_WRIST_PITCH, SERVO_CH_WRIST_ROLL, SERVO_CH_GRIPPER,
    PCA9685_I2C_ADDRESS, PCA9685_PWM_FREQ_HZ,

    # GPIO pin numbers (Option B)
    GPIO_PIN_BASE, GPIO_PIN_SHOULDER, GPIO_PIN_ELBOW,
    GPIO_PIN_WRIST_PITCH, GPIO_PIN_WRIST_ROLL, GPIO_PIN_GRIPPER,

    # Gripper limits
    GRIPPER_OPEN_DEG, GRIPPER_CLOSED_DEG,

    # Servo pulse width range (MG996R: 500–2500 µs)
    SERVO_PULSE_MIN_US, SERVO_PULSE_MAX_US,
)
from board_coordinates import square_to_mm, graveyard_mm


# ── Hardware Detection & Initialization ───────────────────────────────────────
# We try PCA9685 first (most reliable), then pigpio GPIO, then fall back to
# dry-run mode (just prints — useful for testing on Windows without hardware).

_MODE = None        # will be set to "pca9685", "rpi_gpio", or "dryrun"
_kit  = None        # holds ServoKit instance (PCA9685 mode only)
_pwm  = {}          # holds RPi.GPIO PWM objects per channel (rpi_gpio mode only)

# Map each joint channel → its GPIO BCM pin number
_GPIO_PINS = {
    SERVO_CH_BASE:        GPIO_PIN_BASE,
    SERVO_CH_SHOULDER:    GPIO_PIN_SHOULDER,
    SERVO_CH_ELBOW:       GPIO_PIN_ELBOW,
    SERVO_CH_WRIST_PITCH: GPIO_PIN_WRIST_PITCH,
    SERVO_CH_WRIST_ROLL:  GPIO_PIN_WRIST_ROLL,
    SERVO_CH_GRIPPER:     GPIO_PIN_GRIPPER,
}

# ── Try Option A: PCA9685 via ServoKit ────────────────────────────────────────
try:
    from adafruit_servokit import ServoKit
    _kit = ServoKit(channels=16, address=PCA9685_I2C_ADDRESS)
    for ch in range(6):
        # Tell ServoKit the pulse width range for MG996R (500–2500 µs = full 180°)
        _kit.servo[ch].set_pulse_width_range(SERVO_PULSE_MIN_US, SERVO_PULSE_MAX_US)
    _MODE = "pca9685"
    print("[arm_controller] Using PCA9685 via ServoKit.")

except Exception:
    # ── Try Option B: RPi.GPIO software PWM ───────────────────────────────────
    try:
        import RPi.GPIO as GPIO
        GPIO.setmode(GPIO.BCM)       # use BCM pin numbering throughout
        GPIO.setwarnings(False)
        for ch, pin in _GPIO_PINS.items():
            GPIO.setup(pin, GPIO.OUT)
            pwm = GPIO.PWM(pin, 50)  # 50Hz servo frequency
            pwm.start(0)             # start with signal off; ChangeDutyCycle drives motion
            _pwm[ch] = pwm
        _MODE = "rpi_gpio"
        print("[arm_controller] Using RPi.GPIO software PWM.")

    except Exception:
        # ── Option C: Dry-run (no hardware) ───────────────────────────────────
        _MODE = "dryrun"
        print("[arm_controller] No hardware found. Running in dry-run mode (print only).")


# ── Calibration Constants ─────────────────────────────────────────────────────
#
# WHAT THESE DO:
#   Mathematical joint angles (from IK) are in degrees relative to a reference:
#       Base:         0° = arm pointing straight toward the board (+Y)
#       Shoulder:     0° = upper arm horizontal
#       Elbow:        0° = forearm fully extended (aligned with upper arm)
#       Wrist pitch:  0° = wrist aligned with forearm
#
#   Physical servos have their own 0° position depending on how they were mounted.
#   SERVO_ZERO[ch] = the servo PWM angle (0–180°) that corresponds to the
#                    joint's mathematical 0° reference.
#   SERVO_DIR[ch]  = +1 if increasing servo angle → increasing joint angle,
#                    -1 if they are inverted (flip this if the arm goes the wrong way)
#
# HOW TO CALIBRATE (do this once, physically, after wiring):
#   1. Set SERVO_ZERO to 90 for all joints and run: python arm_controller.py --calibrate
#   2. Observe the arm. Adjust SERVO_ZERO[ch] until the joint sits at its reference:
#        Base:     arm pointing straight toward the board
#        Shoulder: upper arm perfectly horizontal
#        Elbow:    arm fully extended, forearm aligned with upper arm
#        Wrist:    wrist aligned with forearm direction
#   3. If a joint moves the WRONG direction when you test it, flip SERVO_DIR[ch] to -1.
#
# !! PLACEHOLDERS — must be calibrated physically before the arm moves correctly !!

SERVO_ZERO = {
    SERVO_CH_BASE:        90.0,  # placeholder: 90° = arm pointing straight ahead
    SERVO_CH_SHOULDER:    90.0,  # placeholder: 90° = upper arm horizontal
    SERVO_CH_ELBOW:       90.0,  # placeholder: 90° = arm fully extended
    SERVO_CH_WRIST_PITCH: 90.0,  # placeholder: 90° = wrist aligned with forearm
    SERVO_CH_WRIST_ROLL:  90.0,  # placeholder: 90° = neutral
    SERVO_CH_GRIPPER:     90.0,  # not used — gripper uses GRIPPER_OPEN/CLOSED_DEG directly
}

SERVO_DIR = {
    SERVO_CH_BASE:        1,   # placeholder: +1 or -1, flip if arm rotates wrong way
    SERVO_CH_SHOULDER:    1,   # placeholder
    SERVO_CH_ELBOW:       1,   # placeholder
    SERVO_CH_WRIST_PITCH: 1,   # placeholder
    SERVO_CH_WRIST_ROLL:  1,   # placeholder
    SERVO_CH_GRIPPER:     1,   # placeholder
}

# Track each servo's current angle so smooth_move() knows where to start from.
# Initialized to SERVO_ZERO (the assumed starting position at power-on).
_current_servo_angle = {ch: SERVO_ZERO[ch] for ch in SERVO_ZERO}

# Smooth motion tuning
SMOOTH_DURATION  = 1.5   # seconds for one servo to complete a standard move
GRIPPER_DURATION = 0.6   # seconds for gripper open/close

# Steps are derived from duration so each step = one 50Hz PWM cycle (20ms).
# This prevents lgpio's queue from overflowing, which causes jumpy/twitchy motion.
SMOOTH_STEPS     = int(SMOOTH_DURATION / 0.02)   # e.g. 1.5s → 75 steps at 20ms each


# ── Section 1: Low-Level Servo Hardware ───────────────────────────────────────

def _angle_to_duty(angle_deg: float) -> float:
    """
    Convert a servo angle (0–180°) to a PWM duty cycle percentage for RPi.GPIO.

    At 50Hz (20ms period):
        0°   = 0.5ms pulse = 2.5% duty cycle
        180° = 2.5ms pulse = 12.5% duty cycle
    Linear mapping: duty = 2.5 + (angle / 180) * 10.0
    """
    return 2.5 + (angle_deg / 180.0) * 10.0  # duty cycle in percent (2.5–12.5%)


def _send_servo_angle(channel: int, angle_deg: float):
    """
    Send a raw angle command to one servo — no smoothing, no calibration math.
    This is the lowest-level function; everything else calls this.

    Parameters:
        channel   : servo channel/index (use SERVO_CH_* constants)
        angle_deg : target position in degrees (0–180, physical servo range)
    """
    # Clamp to valid servo range (0–180°) to prevent mechanical damage
    clamped = max(0.0, min(180.0, angle_deg))

    if _MODE == "pca9685":
        _kit.servo[channel].angle = clamped              # ServoKit converts to PWM internally

    elif _MODE == "rpi_gpio":
        duty = _angle_to_duty(clamped)                   # convert degrees to duty cycle %
        _pwm[channel].ChangeDutyCycle(duty)              # update running PWM — smoother than reissuing

    else:  # dryrun
        print(f"    [SERVO ch={channel}] → {clamped:.1f}°")

    _current_servo_angle[channel] = clamped         # remember where this servo now is


def _math_to_servo(channel: int, math_angle_deg: float) -> float:
    """
    Convert a mathematical joint angle (from IK, can be negative) to a physical
    servo PWM angle (0–180°) using the calibration constants.

    Formula: servo_angle = SERVO_ZERO[channel] + SERVO_DIR[channel] * math_angle_deg

    Raises ValueError if the result is outside 0–180° (joint limit exceeded).
    """
    servo_angle = SERVO_ZERO[channel] + SERVO_DIR[channel] * math_angle_deg

    if not (0.0 <= servo_angle <= 180.0):
        raise ValueError(
            f"Joint {channel}: servo angle {servo_angle:.1f}° is out of range 0–180°.\n"
            f"  (math={math_angle_deg:.1f}°, zero={SERVO_ZERO[channel]}°, dir={SERVO_DIR[channel]})\n"
            f"  Adjust SERVO_ZERO or SERVO_DIR in arm_controller.py."
        )
    return servo_angle


# ── Section 2: Smooth Motion ──────────────────────────────────────────────────

def _smooth_move(channel: int, target_angle_deg: float, duration: float = SMOOTH_DURATION):
    """
    Move one servo smoothly from its current position to target_angle_deg.

    Uses cubic polynomial interpolation:
        θ(t) = θ_start + a2·t² + a3·t³
        a2 =  3·Δθ / tf²    (Δθ = total angle change, tf = duration)
        a3 = −2·Δθ / tf³

    WHY CUBIC?
        The polynomial is constructed so that:
          θ(0)  = θ_start   (starts at current position)
          θ(tf) = θ_end     (arrives at target)
          θ'(0) = 0         (zero velocity at start → no jerk)
          θ'(tf) = 0        (zero velocity at end → smooth stop)
        This is called a "cubic spline with zero endpoint velocities" — the same
        approach used in the ChessRobotArm reference project (Adrianoxzzz/ChessRobotArm).

    Parameters:
        channel          : servo channel (SERVO_CH_* constant)
        target_angle_deg : destination servo angle in degrees (0–180)
        duration         : time in seconds for the full move
    """
    start_angle = _current_servo_angle[channel]   # where the servo is right now
    delta       = target_angle_deg - start_angle  # total angle change needed

    if abs(delta) < 0.5:
        return  # already close enough — skip interpolation to avoid tiny jitter

    # Cubic polynomial coefficients (a0=start, a1=0 for zero initial velocity)
    a2 =  3 * delta / (duration ** 2)   # quadratic coefficient
    a3 = -2 * delta / (duration ** 3)   # cubic coefficient

    # Each step is exactly one 50Hz PWM cycle (20ms) so lgpio's queue never
    # accumulates more than one pending command at a time, preventing jumpy motion.
    dt    = 0.02                          # 20ms = one servo PWM cycle at 50Hz
    steps = int(duration / dt)            # how many steps fit in the duration

    for i in range(steps + 1):
        t     = i * dt                               # current time within the move
        angle = start_angle + a2 * t**2 + a3 * t**3 # cubic position at time t
        _send_servo_angle(channel, angle)            # send PWM command
        time.sleep(dt)                               # wait one full PWM cycle before next command


# ── Section 3: IK Solver ──────────────────────────────────────────────────────

def compute_joint_angles(x_mm: float, y_mm: float, z_mm: float) -> dict:
    """
    Inverse kinematics: convert target gripper-tip position (x, y, z) to joint angles.

    The wrist always points straight down. This reduces the full 6DOF problem to:
      1. Base rotation:   θ_base = atan2(x, y)
      2. 2R planar IK:    θ_shoulder, θ_elbow to reach (r, z_wrist)
      3. Wrist pitch:     auto-computed so gripper stays vertical

    Parameters:
        x_mm, y_mm : horizontal position of gripper tip (mm, arm frame)
        z_mm       : height of gripper tip above table (mm)

    Returns:
        dict with keys "base", "shoulder", "elbow", "wrist_pitch", "wrist_roll" (degrees)

    Raises:
        ValueError if the position is out of reach for the shoulder+elbow links.

    MATH REFERENCE (2R planar IK):
        L1=LINK_SHOULDER_MM, L2=LINK_ELBOW_MM, target=(dr, dz) from shoulder pivot:
            cos(θe) = (dr² + dz² − L1² − L2²) / (2·L1·L2)   [law of cosines]
            θe = −acos(cos(θe))                                [negative = elbow-up]
            θs = atan2(dz, dr) − atan2(L2·sin(θe), L1+L2·cos(θe))
    """

    # ── Base: rotate horizontally to face (x, y) ─────────────────────────────
    # atan2(x, y) gives angle from +Y axis (our forward/board direction).
    # 0° = arm pointing in +Y, positive = rotate toward +X (to the right).
    theta_base_deg = math.degrees(math.atan2(x_mm, y_mm))

    # r = horizontal distance from base axis to target (the "reach" in the ground plane)
    r_mm = math.sqrt(x_mm ** 2 + y_mm ** 2)

    # ── Wrist pivot location ──────────────────────────────────────────────────
    # Gripper hangs straight down from the wrist by LINK_WRIST_MM.
    # So the wrist pivot is directly above the target at height z + LINK_WRIST_MM.
    r_wrist_mm = r_mm
    z_wrist_mm = z_mm + LINK_WRIST_MM

    # ── Vector from shoulder pivot to wrist pivot ─────────────────────────────
    # Shoulder pivot is on the base axis (r=0) at height BASE_TO_SHOULDER_MM.
    delta_r = r_wrist_mm                          # horizontal component
    delta_z = z_wrist_mm - BASE_TO_SHOULDER_MM    # vertical component (positive = wrist above shoulder)

    # Distance from shoulder to wrist — the "hypotenuse" the arm must span
    D = math.sqrt(delta_r ** 2 + delta_z ** 2)

    # ── Reachability check ────────────────────────────────────────────────────
    max_reach = LINK_SHOULDER_MM + LINK_ELBOW_MM
    min_reach = abs(LINK_SHOULDER_MM - LINK_ELBOW_MM)

    if D > max_reach:
        raise ValueError(
            f"OUT OF REACH: ({x_mm:.0f}, {y_mm:.0f}, {z_mm:.0f}) mm\n"
            f"  Shoulder→wrist = {D:.1f} mm,  arm max = {max_reach:.1f} mm.\n"
            f"  Move the board closer to the arm base."
        )
    if D < min_reach:
        raise ValueError(
            f"TOO CLOSE: ({x_mm:.0f}, {y_mm:.0f}, {z_mm:.0f}) mm\n"
            f"  Shoulder→wrist = {D:.1f} mm,  arm min = {min_reach:.1f} mm."
        )

    # ── Elbow angle ───────────────────────────────────────────────────────────
    # Law of cosines for the shoulder→elbow→wrist triangle.
    # cos(θe) = (D² − L1² − L2²) / (2·L1·L2)
    # θe = 0°   → arm straight (forearm aligned with upper arm)
    # θe = 90°  → elbow bent 90°
    cos_elbow = (D ** 2 - LINK_SHOULDER_MM ** 2 - LINK_ELBOW_MM ** 2) / \
                (2 * LINK_SHOULDER_MM * LINK_ELBOW_MM)
    cos_elbow = max(-1.0, min(1.0, cos_elbow))   # clamp: avoid floating-point crash in acos

    # Negative → elbow-UP solution: elbow bends above the shoulder-wrist line.
    # This keeps the elbow clear of the board surface and chess pieces.
    # (Positive = elbow-DOWN: elbow would point at the board, risking collisions.)
    theta_elbow_rad = -math.acos(cos_elbow)
    theta_elbow_deg = math.degrees(theta_elbow_rad)

    # ── Shoulder angle ────────────────────────────────────────────────────────
    # alpha = angle from horizontal to the shoulder→wrist line
    # beta  = how much the elbow "pulls" the shoulder angle inward
    # θ_shoulder = alpha − beta
    alpha = math.atan2(delta_z, delta_r)   # angle to wrist from horizontal
    beta  = math.atan2(
        LINK_ELBOW_MM * math.sin(theta_elbow_rad),
        LINK_SHOULDER_MM + LINK_ELBOW_MM * math.cos(theta_elbow_rad)
    )
    theta_shoulder_rad = alpha - beta
    theta_shoulder_deg = math.degrees(theta_shoulder_rad)

    # ── Wrist pitch: keep gripper pointing straight down ──────────────────────
    # The forearm points at (θ_shoulder + θ_elbow) from horizontal in world frame.
    # For the gripper to point at −90° (straight down):
    #   wrist_pitch = −90° − forearm_world_angle
    forearm_world_deg    = theta_shoulder_deg + theta_elbow_deg
    theta_wrist_pitch_deg = -90.0 - forearm_world_deg

    # Wrist roll: fixed at 0° — no gripper spin needed for chess
    theta_wrist_roll_deg = 0.0

    return {
        "base":        theta_base_deg,
        "shoulder":    theta_shoulder_deg,
        "elbow":       theta_elbow_deg,
        "wrist_pitch": theta_wrist_pitch_deg,
        "wrist_roll":  theta_wrist_roll_deg,
    }


# ── Section 4: Mid-Level Arm Control ─────────────────────────────────────────

def move_to(x_mm: float, y_mm: float, z_mm: float):
    """
    Move the gripper tip to position (x, y, z) in mm with smooth motion.

    Steps:
        1. Compute IK → joint angles
        2. Convert each mathematical angle to a servo PWM angle (via calibration)
        3. Send smooth cubic-interpolated motion commands to each servo

    Joint command order: wrist pitch first (so gripper stays vertical throughout),
    then shoulder + elbow (they change reach), then base (rotates everything).
    This order minimizes the chance of the arm sweeping through pieces during motion.
    """
    angles = compute_joint_angles(x_mm, y_mm, z_mm)   # IK: get joint angles in degrees

    # Convert mathematical angles → physical servo angles using calibration constants
    servo_wrist_pitch = _math_to_servo(SERVO_CH_WRIST_PITCH, angles["wrist_pitch"])
    servo_shoulder    = _math_to_servo(SERVO_CH_SHOULDER,    angles["shoulder"])
    servo_elbow       = _math_to_servo(SERVO_CH_ELBOW,       angles["elbow"])
    servo_base        = _math_to_servo(SERVO_CH_BASE,        angles["base"])
    servo_wrist_roll  = _math_to_servo(SERVO_CH_WRIST_ROLL,  angles["wrist_roll"])

    # Move each joint smoothly to its target angle
    _smooth_move(SERVO_CH_WRIST_PITCH, servo_wrist_pitch)  # wrist first — stays vertical
    _smooth_move(SERVO_CH_SHOULDER,    servo_shoulder)
    _smooth_move(SERVO_CH_ELBOW,       servo_elbow)
    _smooth_move(SERVO_CH_BASE,        servo_base)
    _smooth_move(SERVO_CH_WRIST_ROLL,  servo_wrist_roll)   # hold fixed position


def gripper_open():
    """
    Open the gripper to release a piece or prepare for a grab.
    GRIPPER_OPEN_DEG is set in config.py.
    """
    _smooth_move(SERVO_CH_GRIPPER, GRIPPER_OPEN_DEG, duration=GRIPPER_DURATION)


def gripper_close():
    """
    Close the gripper to grab a piece.
    GRIPPER_CLOSED_DEG is set in config.py — tune it so the gripper grips
    firmly without crushing the piece.
    """
    _smooth_move(SERVO_CH_GRIPPER, GRIPPER_CLOSED_DEG, duration=GRIPPER_DURATION)


# ── Section 5: High-Level Chess API ──────────────────────────────────────────
# These two functions are the only ones called by game_controller.py.

def pick_and_place(from_sq: str, to_sq: str):
    """
    Pick up the piece on from_sq and set it down on to_sq.

    Full movement sequence:
        1. Rise to TRAVEL_Z above source square (clear all pieces)
        2. Lower to GRAB_Z (mid-height of piece)
        3. Close gripper
        4. Rise to TRAVEL_Z
        5. Move horizontally to above destination square
        6. Lower to PLACE_Z (just above board surface)
        7. Open gripper
        8. Rise to TRAVEL_Z (arm clear for next move)

    Parameters:
        from_sq : source square, e.g. "e2"
        to_sq   : destination square, e.g. "e4"
    """
    from_x, from_y = square_to_mm(from_sq)   # physical center of source square
    to_x,   to_y   = square_to_mm(to_sq)     # physical center of destination square

    print(f"  [ARM] pick_and_place: {from_sq} → {to_sq}")

    move_to(from_x, from_y, TRAVEL_Z_MM)   # rise above source at safe height
    move_to(from_x, from_y, GRAB_Z_MM)     # descend to piece grab height
    gripper_close()                          # grab piece
    move_to(from_x, from_y, TRAVEL_Z_MM)   # lift piece clear of other pieces
    move_to(to_x,   to_y,   TRAVEL_Z_MM)   # carry piece horizontally to destination
    move_to(to_x,   to_y,   PLACE_Z_MM)    # lower to just above board surface
    gripper_open()                           # release piece
    move_to(to_x,   to_y,   TRAVEL_Z_MM)   # return to travel height


def remove_to_graveyard(square: str, color: str):
    """
    Pick up a captured piece from square and deposit it in the off-board graveyard.

    Called before moving the capturing piece onto the square, so the square is
    empty when the attacker arrives. Two graveyard zones: one per piece color.

    Parameters:
        square : square where the captured piece sits, e.g. "d5"
        color  : "white" or "black" — selects which graveyard zone to use
    """
    sq_x, sq_y = square_to_mm(square)    # where the captured piece currently is
    gy_x, gy_y = graveyard_mm(color)     # where to deposit it off the board

    print(f"  [ARM] remove_to_graveyard: {square} ({color})")

    move_to(sq_x, sq_y, TRAVEL_Z_MM)    # rise above captured piece
    move_to(sq_x, sq_y, GRAB_Z_MM)      # descend to grab
    gripper_close()                       # grab captured piece
    move_to(sq_x, sq_y, TRAVEL_Z_MM)    # lift clear
    move_to(gy_x, gy_y, TRAVEL_Z_MM)    # carry to graveyard area
    move_to(gy_x, gy_y, GRAVEYARD_Z_MM) # lower to deposit height (pieces stack loosely)
    gripper_open()                        # release
    move_to(gy_x, gy_y, TRAVEL_Z_MM)    # return to travel height


# ── Section 6: Calibration Helper & Self-Test ─────────────────────────────────
# Run this file directly for two modes:
#
#   python arm_controller.py              → IK self-test (print joint angles for key squares)
#   python arm_controller.py --calibrate  → send each servo to 90° so you can physically
#                                           verify and measure the neutral positions

if __name__ == "__main__":
    import sys

    if "--calibrate" in sys.argv:
        # Send every servo to 90° (midpoint of range).
        # Use this to physically find the neutral position of each joint.
        # Observe the arm and adjust SERVO_ZERO constants above.
        print("=== CALIBRATION MODE: sending all servos to 90° ===")
        print("Observe each joint. When done, Ctrl+C to exit.\n")
        for ch in [SERVO_CH_BASE, SERVO_CH_SHOULDER, SERVO_CH_ELBOW,
                   SERVO_CH_WRIST_PITCH, SERVO_CH_WRIST_ROLL, SERVO_CH_GRIPPER]:
            print(f"  Moving channel {ch} to 90°...")
            _send_servo_angle(ch, 90.0)
            time.sleep(1.0)
        print("\nAll servos at 90°. Adjust SERVO_ZERO[] values based on observations.")

    else:
        # IK self-test: compute and print joint angles for a set of board squares.
        # Run on any machine (Windows, Pi) — no hardware needed for this test.
        print("=== arm_controller.py IK self-test ===\n")
        print(f"  L1={LINK_SHOULDER_MM}mm  L2={LINK_ELBOW_MM}mm  "
              f"L3={LINK_WRIST_MM}mm  base_h={BASE_TO_SHOULDER_MM}mm\n")

        test_squares = ["e4", "a1", "h1", "a8", "h8"]

        print(f"  {'sq':<4}  {'x':>6}  {'y':>6}  {'z':>5}  "
              f"{'base':>7}  {'shoulder':>9}  {'elbow':>7}  {'wrist_p':>8}")
        print("  " + "─" * 70)

        for sq in test_squares:
            x, y = square_to_mm(sq)
            z = GRAB_Z_MM
            try:
                a = compute_joint_angles(x, y, z)
                print(f"  {sq:<4}  {x:6.0f}  {y:6.0f}  {z:5.0f}  "
                      f"{a['base']:7.1f}°  {a['shoulder']:8.1f}°  "
                      f"{a['elbow']:6.1f}°  {a['wrist_pitch']:7.1f}°")
            except ValueError as e:
                print(f"  {sq:<4}  {x:6.0f}  {y:6.0f}  {z:5.0f}  "
                      f"UNREACHABLE ({e.args[0].split(chr(10))[0]})")

        print("\n=== done ===")
