---
name: pvlib
description: >-
  Solar energy calculations (pvlib): where the sun is at any time and place,
  sunrise, solar noon, and sunset, cloudless-sky irradiance over a day, typical-
  year weather for any land location (PVGIS), and the annual and monthly energy
  of a rooftop or ground-mounted PV system (PVWatts model: specific yield,
  capacity factor, performance ratio). Use for "how much will 5 kW of panels
  produce here", panel tilt and orientation choices, sun angles for shading or
  daylighting, and day length.
---

## Recipes

- **Yield of a PV system:** `pvgis_weather(lat, lon)` → `pv_energy(lat, lon,
  weather="weather.csv", capacity_kw=5)`; report kWh/year, kWh/kWp, and the
  monthly plot. Try a few `tilt_deg` / `azimuth_deg` values to compare
  orientations (azimuth 180 = south, 90 = east, 270 = west).
- **Offline:** `sample_weather()` gives bundled US typical years; `weather=
  "clearsky"` is a cloudless upper bound, not an estimate.
- **Sun angles:** `solar_position(lat, lon, ["2024-12-21T12:00"], "Europe/Paris")`;
  zenith 90 = horizon.
- **Day length:** `sun_times(lat, lon, ["2024-06-21", "2024-12-21"], timezone)`.

## Interpreting

- Specific yield (kWh/kWp/year) compares sites independently of system size:
  roughly 800-1000 in northern Europe, 1300-1700 in sunny mid-latitudes, 1800+ in
  deserts.
- Performance ratio 0.75-0.85 is typical; lower means hot panels, high losses,
  or clipping.

## Pitfalls

- Times without an offset are read in `timezone`; use IANA names
  ("America/Denver") so daylight saving is handled.
- `pvgis_weather` needs internet; the CSV it writes can be reused offline.
- Shading from nearby objects is not modelled; raise `losses_percent` for it.
