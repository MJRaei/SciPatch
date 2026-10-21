"""Solar energy with pvlib: sun position, sunrise and sunset, clear-sky irradiance, and PV output.

Sun positions use NREL's Solar Position Algorithm (SPA). PV output uses the PVWatts
model (as in NREL's PVWatts calculator): Perez transposition to the panel plane,
reflection losses, SAPM cell temperature, a temperature coefficient, system losses,
and an inverter with clipping. Weather comes from a typical-year file (EPW, TMY3,
or a CSV, e.g. from pvgis_weather) or an idealized clear sky.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Literal

import pandas as pd

WEATHER_COLUMNS = ["ghi", "dni", "dhi", "temp_air", "wind_speed"]
MOUNTS = {"open_rack": "open_rack_glass_polymer", "roof": "insulated_back_glass_polymer"}


def _quiet() -> None:
    import warnings

    warnings.filterwarnings("ignore")


def _times(times: list[str], timezone: str) -> pd.DatetimeIndex:
    try:
        parsed = [pd.Timestamp(text) for text in times]
    except ValueError as exc:
        raise ValueError(f"Could not read the times: {exc}") from exc
    localized = [t.tz_localize(timezone) if t.tzinfo is None else t for t in parsed]
    return pd.DatetimeIndex([t.tz_convert(timezone) for t in localized])


def _location(latitude: float, longitude: float, timezone: str, altitude_m: float | None):
    from pvlib.location import Location, lookup_altitude

    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("latitude must be within ±90 and longitude within ±180 degrees.")
    if altitude_m is None:
        altitude_m = float(lookup_altitude(latitude, longitude))
    return Location(latitude, longitude, tz=timezone, altitude=altitude_m)


def _round(value: float, digits: int = 6) -> float | None:
    return None if value is None or not math.isfinite(value) else round(float(value), digits)


def solar_position(
    latitude: float,
    longitude: float,
    times: list[str],
    timezone: str = "UTC",
    altitude_m: float = 0.0,
    pressure_pa: float | None = None,
    temperature_c: float = 12.0,
    delta_t_s: float | None = None,
) -> dict:
    """Sun position (NREL SPA) at given times and place.

    Args:
        latitude: Degrees north.
        longitude: Degrees east (west is negative).
        times: ISO times, e.g. "2024-06-21T12:00"; times without an offset are in
            `timezone`.
        timezone: IANA name (e.g. "Europe/Berlin", "America/Denver") or "Etc/GMT+7"
            for a fixed UTC-7.
        altitude_m: Site elevation in m.
        pressure_pa: Air pressure in Pa for refraction (default from altitude).
        temperature_c: Air temperature in °C for refraction.
        delta_t_s: TT - UT1 in s (default: estimated for the date).

    Returns:
        For each time: zenith and elevation angles with and without atmospheric
        refraction, azimuth (degrees east of north), and the equation of time.
    """
    _quiet()
    from pvlib import atmosphere, solarposition

    index = _times(times, timezone)
    pressure = pressure_pa if pressure_pa is not None else atmosphere.alt2pres(altitude_m)
    extra = {} if delta_t_s is None else {"delta_t": delta_t_s}
    position = solarposition.get_solarposition(
        index, latitude, longitude, altitude_m, pressure, temperature=temperature_c, **extra
    )
    rows = []
    for time, row in position.iterrows():
        rows.append(
            {
                "time": time.isoformat(),
                "apparent_zenith_deg": _round(row["apparent_zenith"]),
                "zenith_deg": _round(row["zenith"]),
                "apparent_elevation_deg": _round(row["apparent_elevation"]),
                "elevation_deg": _round(row["elevation"]),
                "azimuth_deg": _round(row["azimuth"]),
                "equation_of_time_min": _round(row["equation_of_time"], 4),
            }
        )
    return {"latitude": latitude, "longitude": longitude, "positions": rows}


def sun_times(latitude: float, longitude: float, dates: list[str], timezone: str = "UTC") -> dict:
    """Sunrise, solar noon, and sunset (NREL SPA; upper limb with standard refraction).

    Args:
        latitude: Degrees north.
        longitude: Degrees east (west is negative).
        dates: Days as "YYYY-MM-DD".
        timezone: IANA name for the local times, e.g. "Asia/Tokyo" or "Etc/GMT+7".

    Returns:
        For each day: local sunrise, solar noon, and sunset (ISO and decimal hours),
        and day length in hours; null on days without sunrise or sunset (polar day
        or night).
    """
    _quiet()
    from pvlib import solarposition

    days = _times([f"{date[:10]}T00:00" for date in dates], timezone)
    result = solarposition.sun_rise_set_transit_spa(days, latitude, longitude)
    rows = []
    for day, row in result.iterrows():
        entry: dict = {"date": day.date().isoformat()}
        for key, column in (
            ("sunrise", "sunrise"),
            ("solar_noon", "transit"),
            ("sunset", "sunset"),
        ):
            time = row[column]
            if pd.isna(time):
                entry[key], entry[f"{key}_hours"] = None, None
                continue
            time = pd.Timestamp(time).tz_convert(timezone)
            entry[key] = time.isoformat(timespec="seconds")
            entry[f"{key}_hours"] = round((time - day).total_seconds() / 3600, 5)
        entry["day_length_hours"] = (
            round(entry["sunset_hours"] - entry["sunrise_hours"], 5)
            if entry["sunrise_hours"] is not None and entry["sunset_hours"] is not None
            else None
        )
        rows.append(entry)
    return {"latitude": latitude, "longitude": longitude, "timezone": timezone, "days": rows}


def clear_sky(
    latitude: float,
    longitude: float,
    date: str,
    timezone: str = "UTC",
    altitude_m: float | None = None,
    model: Literal["ineichen", "haurwitz", "simplified_solis"] = "ineichen",
    linke_turbidity: float | None = None,
    step_min: int = 10,
    table: str = "clear_sky.csv",
    plot: str = "clear_sky.png",
) -> dict:
    """Cloudless-sky irradiance over a day: global, direct normal, and diffuse.

    Args:
        latitude: Degrees north.
        longitude: Degrees east.
        date: The day, "YYYY-MM-DD".
        timezone: IANA name for local time.
        altitude_m: Site elevation in m (default: looked up from latitude and longitude).
        model: "ineichen" (with climatological Linke turbidity), "haurwitz", or
            "simplified_solis".
        linke_turbidity: Fixed Linke turbidity for "ineichen" (about 2 for very
            clean air, 3-4 typical, 5+ hazy); default: monthly climatology.
        step_min: Time step in minutes.
        table: CSV of the irradiance through the day.
        plot: PNG of the irradiance through the day.

    Returns:
        Daily irradiation (kWh/m2) on a horizontal surface and normal to the sun,
        peak global irradiance (W/m2) and its time, the altitude used, and the
        file paths.
    """
    _quiet()
    site = _location(latitude, longitude, timezone, altitude_m)
    start = _times([f"{date[:10]}T00:00"], timezone)[0]
    times = pd.date_range(start, periods=int(24 * 60 / step_min), freq=f"{step_min}min")
    extra = {"linke_turbidity": linke_turbidity} if linke_turbidity is not None else {}
    sky = site.get_clearsky(times, model=model, **extra)
    sky.round(3).to_csv(table, index_label="time")
    _plot_day(sky, f"Clear sky at ({latitude}, {longitude}), {date[:10]}", plot)
    hours = step_min / 60
    peak = sky["ghi"].idxmax()
    return {
        "date": date[:10],
        "altitude_m": round(site.altitude, 1),
        "model": model,
        "ghi_kwh_m2": round(float(sky["ghi"].sum()) * hours / 1000, 4),
        "dni_kwh_m2": round(float(sky["dni"].sum()) * hours / 1000, 4),
        "dhi_kwh_m2": round(float(sky["dhi"].sum()) * hours / 1000, 4),
        "peak_ghi_w_m2": round(float(sky["ghi"].max()), 2),
        "peak_time": peak.isoformat(),
        "table": table,
        "plot": plot,
    }


def _plot_day(sky: pd.DataFrame, title: str, path: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(figsize=(7, 4))
    hours = sky.index.hour + sky.index.minute / 60
    for column, label in (
        ("ghi", "global horizontal"),
        ("dni", "direct normal"),
        ("dhi", "diffuse"),
    ):
        axes.plot(hours, sky[column], label=label)
    axes.set(xlabel="Local time (h)", ylabel="Irradiance (W/m²)", title=title, xlim=(0, 24))
    axes.legend()
    figure.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(figure)


def pvgis_weather(latitude: float, longitude: float, file: str = "weather.csv") -> dict:
    """Download a typical meteorological year from PVGIS (EU JRC) for any land location.

    Args:
        latitude: Degrees north.
        longitude: Degrees east.
        file: CSV to write (UTC times, ghi/dni/dhi in W/m2, temp_air in °C,
            wind_speed in m/s); pass it to pv_energy as `weather`.

    Returns:
        The file path, the elevation PVGIS reports, the years each month was taken
        from, and the annual global horizontal irradiation (kWh/m2).
    """
    _quiet()
    from pvlib import iotools

    try:
        result = iotools.get_pvgis_tmy(latitude, longitude, map_variables=True)
    except Exception as exc:
        raise RuntimeError(f"PVGIS did not return weather for this location: {exc}") from exc
    data, meta = result[0], result[-1]
    data = data[WEATHER_COLUMNS].tz_convert("UTC")
    data.round(3).to_csv(file, index_label="time")
    months = result[1] if len(result) > 2 else meta.get("months_selected")
    location = meta.get("location", meta.get("inputs", {}).get("location", {}))
    return {
        "file": file,
        "elevation_m": location.get("elevation"),
        "months_from_years": months,
        "ghi_kwh_m2_per_year": round(float(data["ghi"].sum()) / 1000, 1),
        "source": "PVGIS TMY (European Commission JRC), https://re.jrc.ec.europa.eu/pvg_tools/",
    }


def _weather(source: str, site) -> tuple[pd.DataFrame, str]:
    """Hourly weather indexed at the middle of each hour (where the sun is computed)."""
    from pvlib import iotools

    if source == "clearsky":
        times = pd.date_range("2025-01-01", "2026-01-01", freq="1h", tz=site.tz, inclusive="left")
        data = site.get_clearsky(times)
        data["temp_air"], data["wind_speed"] = 20.0, 1.0
        return data, "clear sky (Ineichen), 20 °C, 1 m/s"
    path = Path(source)
    if not path.is_file():
        raise ValueError(f"Weather file {source!r} not found; give a file or 'clearsky'.")
    suffix = path.suffix.lower()
    with open(path, encoding="utf-8", errors="replace") as handle:
        first = handle.readline()
    if suffix == ".epw":
        data, _ = iotools.read_epw(path, coerce_year=2025)
        data.index = data.index - pd.Timedelta("30min")  # hour-ending values
        kind = "EPW"
    elif first.count(",") in (6, 7) and "time" not in first.lower():
        data, _ = iotools.read_tmy3(path, coerce_year=2025, map_variables=True)
        data.index = data.index - pd.Timedelta("30min")
        kind = "TMY3"
    else:
        data = pd.read_csv(path, index_col=0)
        data.index = pd.to_datetime(data.index, utc=True)
        kind = "CSV"
    missing = [column for column in ("ghi", "dni", "dhi") if column not in data]
    if missing:
        raise ValueError(f"The weather file lacks {', '.join(missing)}.")
    if "temp_air" not in data:
        data["temp_air"] = 20.0
    if "wind_speed" not in data:
        data["wind_speed"] = 1.0
    return data[WEATHER_COLUMNS].astype(float), f"{kind} file {path.name}"


def pv_energy(
    latitude: float,
    longitude: float,
    weather: str = "clearsky",
    capacity_kw: float = 1.0,
    tilt_deg: float | None = None,
    azimuth_deg: float | None = None,
    losses_percent: float = 14.08,
    temperature_coefficient_per_c: float = -0.0037,
    dc_ac_ratio: float = 1.2,
    inverter_efficiency: float = 0.96,
    mounting: Literal["open_rack", "roof"] = "open_rack",
    transposition: Literal["perez", "haydavies", "isotropic"] = "perez",
    altitude_m: float | None = None,
    table: str = "pv_monthly.csv",
    plot: str = "pv_monthly.png",
) -> dict:
    """Annual and monthly energy of a fixed-tilt PV system (PVWatts model).

    Args:
        latitude: Degrees north.
        longitude: Degrees east.
        weather: Path to a typical-year file (EPW, TMY3, or CSV with time, ghi, dni,
            dhi, temp_air, wind_speed, e.g. from pvgis_weather), or "clearsky" for an
            idealized cloudless year (an upper bound).
        capacity_kw: DC nameplate power in kW (at 1000 W/m2 and 25 °C).
        tilt_deg: Panel tilt from horizontal (default: |latitude|).
        azimuth_deg: Direction the panels face, degrees east of north (default:
            180, south, in the northern hemisphere; 0, north, in the southern).
        losses_percent: System losses (soiling, shading, wiring, mismatch,
            availability, ...); 14.08% is PVWatts' default.
        temperature_coefficient_per_c: Relative power change per °C of cell
            temperature (-0.0037 for typical crystalline silicon).
        dc_ac_ratio: DC nameplate over inverter AC rating; above 1 clips peaks.
        inverter_efficiency: Nominal inverter efficiency.
        mounting: "open_rack" (ground or open frame) or "roof" (flush, hotter).
        transposition: Sky-diffuse model for the tilted plane.
        altitude_m: Site elevation in m (default: looked up).
        table: CSV with monthly energy and irradiation.
        plot: PNG of monthly energy.

    Returns:
        Annual AC energy (kWh), specific yield (kWh per kWp), capacity factor,
        performance ratio, annual irradiation on the horizontal and on the panels
        (kWh/m2), hours at the inverter's AC limit (clipping), monthly values, the
        orientation used, and the file paths.
    """
    _quiet()
    from pvlib import inverter, irradiance, pvsystem, temperature
    from pvlib.iam import physical

    if capacity_kw <= 0 or dc_ac_ratio <= 0 or not 0 < inverter_efficiency <= 1:
        raise ValueError("capacity_kw, dc_ac_ratio, and inverter_efficiency must be positive.")
    site = _location(latitude, longitude, "UTC", altitude_m)
    tilt = abs(latitude) if tilt_deg is None else tilt_deg
    azimuth = (180.0 if latitude >= 0 else 0.0) if azimuth_deg is None else azimuth_deg
    data, source = _weather(weather, site)
    sun = site.get_solarposition(data.index, temperature=data["temp_air"])
    poa = irradiance.get_total_irradiance(
        tilt,
        azimuth,
        sun["apparent_zenith"],
        sun["azimuth"],
        data["dni"],
        data["ghi"],
        data["dhi"],
        dni_extra=irradiance.get_extra_radiation(data.index),
        airmass=site.get_airmass(data.index, solar_position=sun)["airmass_relative"],
        model=transposition,
    ).fillna(0.0)
    incidence = irradiance.aoi(tilt, azimuth, sun["apparent_zenith"], sun["azimuth"])
    effective = poa["poa_direct"] * physical(incidence) + poa["poa_diffuse"]
    cell = temperature.sapm_cell(
        poa["poa_global"],
        data["temp_air"],
        data["wind_speed"],
        **temperature.TEMPERATURE_MODEL_PARAMETERS["sapm"][MOUNTS[mounting]],
    )
    pdc0 = capacity_kw * 1000
    dc = pvsystem.pvwatts_dc(effective, cell, pdc0, temperature_coefficient_per_c)
    dc = dc.clip(lower=0) * (1 - losses_percent / 100)
    ac_rating = pdc0 / dc_ac_ratio
    ac = inverter.pvwatts(dc, ac_rating / inverter_efficiency, inverter_efficiency).clip(lower=0)
    step_h = float(pd.Series(data.index).diff().median().total_seconds() / 3600)
    energy = float(ac.sum()) * step_h / 1000
    poa_kwh = float(poa["poa_global"].sum()) * step_h / 1000
    ghi_kwh = float(data["ghi"].sum()) * step_h / 1000
    hours = len(data) * step_h
    frame = pd.DataFrame(
        {"ac_kwh": ac * step_h / 1000, "poa_kwh_m2": poa["poa_global"] * step_h / 1000},
        index=data.index,
    )
    monthly = frame.groupby(frame.index.month).sum()
    rows = [
        {
            "month": int(month),
            "ac_kwh": round(float(row["ac_kwh"]), 3),
            "poa_kwh_m2": round(float(row["poa_kwh_m2"]), 3),
        }
        for month, row in monthly.iterrows()
    ]
    with open(table, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    _plot_months(rows, f"{capacity_kw:g} kW at ({latitude}, {longitude}), tilt {tilt:g}°", plot)
    return {
        "weather": source,
        "tilt_deg": tilt,
        "azimuth_deg": azimuth,
        "annual_ac_kwh": round(energy, 2),
        "specific_yield_kwh_per_kwp": round(energy / capacity_kw, 2),
        "capacity_factor": round(energy / (capacity_kw * hours), 5),
        "performance_ratio": round(energy / capacity_kw / poa_kwh, 5) if poa_kwh else None,
        "ghi_kwh_m2": round(ghi_kwh, 2),
        "poa_kwh_m2": round(poa_kwh, 2),
        "clipped_hours": round(float((ac >= 0.999 * ac_rating).sum()) * step_h, 1),
        "monthly": rows,
        "table": table,
        "plot": plot,
    }


def _plot_months(rows: list[dict], title: str, path: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(figsize=(7, 4))
    axes.bar([row["month"] for row in rows], [row["ac_kwh"] for row in rows])
    axes.set(xlabel="Month", ylabel="AC energy (kWh)", title=title, xticks=range(1, 13))
    figure.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(figure)


def sample_weather() -> dict:
    """Typical-year weather files that ship with pvlib, for trying pv_energy offline.

    Returns:
        Paths and descriptions of the bundled TMY3 files.
    """
    import pvlib

    folder = Path(pvlib.__file__).parent / "data"
    return {
        "files": {
            "Greensboro, NC, USA (TMY3 723170)": str(folder / "723170TYA.CSV"),
            "Sand Point, AK, USA (TMY3 703165)": str(folder / "703165TY.csv"),
        },
        "note": "NREL TMY3 data (1991-2005), as distributed with pvlib.",
    }
