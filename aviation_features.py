"""Pure Python flight-operation helpers kept independent from the UI/build system."""

import math


def normalize_heading(value):
    return float(value) % 360.0


def heading_difference(a, b):
    return abs((normalize_heading(a) - normalize_heading(b) + 180.0) % 360.0 - 180.0)


def top_of_descent_nm(altitude_ft, target_altitude_ft, groundspeed_kt, descent_fpm=1500):
    delta = max(0.0, float(altitude_ft) - float(target_altitude_ft))
    if delta <= 0 or groundspeed_kt <= 20 or descent_fpm <= 0:
        return None
    return groundspeed_kt * delta / descent_fpm / 60.0


def stabilized_approach(altitude_ft, speed_kt, vertical_speed_fpm):
    if altitude_ft > 3000:
        return "NOT YET"
    issues = []
    if speed_kt > 190:
        issues.append("FAST")
    if vertical_speed_fpm < -1200:
        issues.append("HIGH SINK")
    return "STABLE" if not issues else "UNSTABLE: " + ", ".join(issues)
