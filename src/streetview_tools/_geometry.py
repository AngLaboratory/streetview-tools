import math


def add_spot_info(base_pano):
    base_lat = base_pano["lat"]
    base_lon = base_pano["lon"]
    base_angle = float(base_pano.get("angle", 0))
    spots = []

    for spot in base_pano.get("spot", []):
        bearing = calc_bearing(base_lat, base_lon, spot["lat"], spot["lon"])
        is_front = resolve_position(base_angle, bearing)
        spots.append({
            **spot,
            "distance_m": calc_distance_meter(
                base_lat, base_lon, spot["lat"], spot["lon"]
            ),
            "isFrontTF": is_front,
            "position": "front" if is_front else "back",
        })

    base_pano["spot"] = spots
    return base_pano


def calc_distance_meter(lat1, lon1, lat2, lon2):
    radius = 6371000
    lat1, lat2 = math.radians(lat1), math.radians(lat2)
    dlat = lat2 - lat1
    dlon = math.radians(lon2 - lon1)
    value = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return round(2 * radius * math.asin(math.sqrt(value)), 4)


def calc_bearing(lat1, lon1, lat2, lon2):
    lat1, lat2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return round((math.degrees(math.atan2(x, y)) + 360) % 360, 4)


def resolve_position(base_angle, target_bearing):
    difference = (target_bearing - base_angle + 180) % 360 - 180
    return -90 <= difference <= 90