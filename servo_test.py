"""
servo_test.py
-------------
Final standalone arm motion script for the chess robot.

This script runs directly on the Raspberry Pi and handles the full
physical interaction loop: wait for an object to appear in front of
the sensor, wave the arm left/right to signal detection, then return
to the home position and repeat.

HOW THIS FITS IN THE PROJECT:
    servo_test.py  ← YOU ARE HERE: standalone Pi demo / integration test
    arm_controller.py → full IK-based arm controller (used by game_controller.py)

HARDWARE WIRED HERE:
    6× MG996R servos on GPIO BCM pins 17, 19, 26, 23, 24, 25
    HC-SR04 ultrasonic sensor on TRIG=5, ECHO=6
    Active buzzer on GPIO 12
    Tactile push button on GPIO 20 (pull-up, active-LOW)

HOW TO RUN:
    python servo_test.py
Press Ctrl+C to stop — cleanup() in shutdown() releases all GPIO.
"""

import RPi.GPIO as GPIO   # Raspberry Pi GPIO library (software PWM + digital I/O)
import time               # time.sleep() for delays and PWM timing

# ── GPIO Setup ────────────────────────────────────────────────────────────────

GPIO.setmode(GPIO.BCM)       # use BCM (Broadcom) pin numbers, not physical board numbers
GPIO.setwarnings(False)      # suppress "channel already in use" warnings on re-runs

# ── PWM Frequency ─────────────────────────────────────────────────────────────
FREQ = 50   # 50 Hz = 20ms period — standard servo control frequency

# ── Pin Assignments ───────────────────────────────────────────────────────────
Buzzer  = 12   # active buzzer: HIGH = beep ON
Button1 = 20   # tactile push button (pull-up: LOW when pressed)
trig    = 5    # HC-SR04 ultrasonic trigger (output: send 10µs pulse to fire)
echo    = 6    # HC-SR04 ultrasonic echo (input: HIGH pulse duration → distance)

# ── Ultrasonic Detection Threshold ────────────────────────────────────────────
detect_distance = 50   # cm — object closer than this triggers the arm sequence

# ── Global State ──────────────────────────────────────────────────────────────
object_detected = False   # tracks whether the sensor currently sees an object

# ── GPIO Pin Mode Configuration ───────────────────────────────────────────────
GPIO.setup(trig,    GPIO.OUT)                              # trigger fires the ultrasonic burst
GPIO.setup(echo,    GPIO.IN)                               # echo reads back the reflected burst
GPIO.setup(Buzzer,  GPIO.OUT, initial=GPIO.LOW)            # buzzer off at startup
GPIO.setup(Button1, GPIO.IN,  pull_up_down=GPIO.PUD_UP)   # internal pull-up; button shorts to GND

# ── Servo Pin Map ─────────────────────────────────────────────────────────────
# Maps servo name (string) → BCM GPIO pin number.
# Joint assignments (matches arm wiring):
#   "1" = base rotation, "2" = shoulder, "3" = elbow,
#   "4" = wrist pitch,   "5" = wrist roll, "6" = gripper
Servo_Pins = {
    "1": 17,   # base rotation
    "2": 19,   # shoulder pitch
    "3": 26,   # elbow pitch
    "4": 23,   # wrist pitch
    "5": 24,   # wrist roll
    "6": 25,   # gripper open/close
}

# ── Servo Initialization ──────────────────────────────────────────────────────
# Start PWM at 0% duty cycle (signal off) so servos don't snap on power-up.
Servos = {}
for name, pin in Servo_Pins.items():
    GPIO.setup(pin, GPIO.OUT)           # configure pin as output
    pwm = GPIO.PWM(pin, FREQ)          # create software PWM object at 50 Hz
    pwm.start(0)                        # duty cycle 0 = no pulse = servo free/off
    Servos[name] = pwm                  # store PWM object keyed by servo name
    print(f"[OK] {name} initialized on GPIO {pin}")


# ── Helper: angle_to_duty ─────────────────────────────────────────────────────

def angle_to_duty(angle):
    """
    Convert servo angle (0–180°) to PWM duty cycle percentage.

    At 50 Hz (20ms period):
        0°   → 0.5ms pulse = 2.5% duty cycle
        180° → 2.5ms pulse = 12.5% duty cycle
    Linear interpolation between those endpoints.
    """
    return (angle / 180.0) * 10.0 + 2.5   # maps [0, 180] → [2.5%, 12.5%]


# ── Helper: move ──────────────────────────────────────────────────────────────

def move(name, angle, release, delay=0.5):
    """
    Command one servo to an angle and hold it there.

    Parameters:
        name    : servo key ("1"–"6")
        angle   : target angle in degrees (clamped 0–180)
        release : unused positional arg (kept for call-site compatibility)
        delay   : seconds to wait after sending the command (lets servo physically reach position)

    Note: duty cycle stays on after the delay so the servo holds position under load.
    """
    angle = max(0, min(180, angle))              # clamp to safe servo range
    Servos[name].ChangeDutyCycle(angle_to_duty(angle))   # send PWM angle command
    time.sleep(delay)                            # wait for servo to physically arrive
    if release:
        print(release)
    # signal stays ON — servo holds position


# ── Helper: beep ──────────────────────────────────────────────────────────────

def beep():
    """Fire the buzzer once for 0.5 seconds as an audible feedback signal."""
    GPIO.output(Buzzer, GPIO.HIGH)   # buzzer on
    time.sleep(0.5)
    GPIO.output(Buzzer, GPIO.LOW)    # buzzer off


# ── Helper: get_distance ──────────────────────────────────────────────────────

def get_distance():
    """
    Measure distance to the nearest object using the HC-SR04 ultrasonic sensor.

    Sequence:
        1. Pull TRIG LOW briefly to clear any stale signal.
        2. Pulse TRIG HIGH for 10µs to fire an ultrasonic burst.
        3. Time how long ECHO stays HIGH — that duration is the round-trip travel time.
        4. distance (cm) = duration × speed_of_sound / 2
           = pulse_duration × 34300 cm/s / 2 = pulse_duration × 17150

    Returns:
        float  : distance in centimeters, rounded to 2 decimal places
        None   : if ECHO doesn't respond within 40ms (sensor timeout / no object)
    """
    GPIO.output(trig, False)     # ensure trigger is LOW before firing
    time.sleep(0.05)             # 50ms settle time

    GPIO.output(trig, True)      # send 10µs trigger pulse
    time.sleep(0.00001)
    GPIO.output(trig, False)

    # Wait for ECHO to go HIGH (rising edge = burst sent by sensor)
    timeout_start = time.time()
    while GPIO.input(echo) == 0:
        if time.time() - timeout_start > 0.04:   # 40ms timeout
            return None
    pulse_start = time.time()

    # Wait for ECHO to go LOW (falling edge = echo received)
    timeout_start = time.time()
    while GPIO.input(echo) == 1:
        if time.time() - timeout_start > 0.04:   # 40ms timeout
            return None
    pulse_end = time.time()

    pulse_duration = pulse_end - pulse_start        # time for sound to travel to object and back
    distance = pulse_duration * 17150               # convert to cm (speed of sound ÷ 2)
    distance = round(distance, 2)
    return distance


# ── device_test: arm wave sequence ────────────────────────────────────────────

def device_test(detect=True):
    """
    Run the arm wave sequence triggered when an object is detected.

    Sequence:
        1. Pre-position wrist and gripper to an open/raised state.
        2. Wait for Button1 to be pressed (signals "move left").
        3. Rotate base left.
        4. Close wrist / gripper (pick gesture).
        5. Beep to acknowledge.
        6. Return to home position via begin().

    Parameters:
        detect : if True, run the full detection-triggered sequence (default)
    """
    if detect:
        print("Press Button1 once for left")

        # Pre-position wrist to raised/open state before waiting for button
        move("4", 135, False)    # wrist pitched back
        time.sleep(.5)
        move("6", 180, False)    # gripper fully open
        time.sleep(0.5)
        move("4", 45, False)     # wrist pitched forward

        # Block until Button1 is pressed (LOW = pressed on pull-up circuit)
        while True:
            time.sleep(0.25)
            if GPIO.input(Button1) == GPIO.LOW:
                print("Button1 pressed")
                move("1", 90, False)    # rotate base to center/left position
                time.sleep(.5)
                break

        move("4", 135, False)    # wrist back
        time.sleep(0.5)

        move("6", 0, False)      # gripper closed (pick gesture)
        time.sleep(.5)
        beep()                   # audible feedback: piece grabbed
        time.sleep(0.25)
        move("4", 45, False)     # wrist forward
        time.sleep(0.5)
        move("1", 0, False)      # return base to home rotation
        time.sleep(.5)
        begin()                  # reset all joints to home position


# ── check_detection ───────────────────────────────────────────────────────────

def check_detection():
    """
    Poll the ultrasonic sensor once and update the global object_detected flag.

    Sets object_detected = True if an object is within detect_distance cm,
    False otherwise. No-ops on sensor timeout (dist=None).
    """
    global object_detected
    dist = get_distance()

    if dist is None:
        return   # sensor timeout — no update, keep previous state
    if dist < detect_distance:
        object_detected = True
        print("Object Detected")
    else:
        object_detected = False


# ── shutdown ──────────────────────────────────────────────────────────────────

def shutdown():
    """Stop all servo PWM signals and release all GPIO resources."""
    for pwm in Servos.values():
        pwm.stop()       # stop PWM output (servos go slack)
    GPIO.cleanup()       # release all GPIO pin reservations
    print("GPIO cleaned up.")


# ── begin: home position + detection loop ─────────────────────────────────────

def begin():
    """
    Move all joints to the home/idle position, then poll the ultrasonic sensor
    in a loop until an object is detected. Once detected, run device_test().

    Home position:
        Servo 3 (elbow) = 0°    — arm folded
        Servo 4 (wrist) = 45°   — wrist angled forward
        Servo 6 (gripper) = 0°  — gripper closed / resting
    """
    # Return all joints to home position sequentially
    move("3", 0,  False)   # elbow to home
    time.sleep(.5)
    move("4", 45, False)   # wrist to home
    time.sleep(.5)
    move("6", 0,  False)   # gripper to home
    time.sleep(.5)
    print("done")

    # Poll until object detected, then trigger the arm sequence
    while True:
        check_detection()

        if object_detected:
            device_test()
            break   # exit detection loop after one sequence; begin() is called again by device_test()


# ── Entry Point ───────────────────────────────────────────────────────────────
begin()      # start the detection and motion loop
shutdown()   # clean up GPIO after begin() returns (Ctrl+C or natural exit)
