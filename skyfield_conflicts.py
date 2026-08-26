from skyfield.api import wgs84, load
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Patch
import json 
from datetime import datetime

#                  [NPP, NOAA20, NOAA21, MET-B, MET-C, AQUA, MET-SGA1, GCOM-W1, AWS]
TARGET_NORAD_IDS = {37849, 43013, 54234, 38771, 43689, 27424, 65159, 38337, 60543}

tle_url = "https://proto.gina.alaska.edu/distro/tle/weather.txt"
try:
    satellites = load.tle_file(tle_url, filename="weather_tle.txt", reload=True)
    satellites = [sat for sat in satellites if sat.model.satnum in TARGET_NORAD_IDS]
    print(f"Loaded {len(satellites)} satellites from GINA TLE feed.")
except Exception as e:
    print(f"Failed to load TLEs from URL: {e}")
    satellites = []

ts = load.timescale()
now_utc = pd.Timestamp.now(tz='UTC')
start_date = (now_utc - pd.Timedelta(days=1)).floor('D')
end_date = start_date + pd.Timedelta(days=4)

t0 = ts.from_datetime(start_date)
t1 = ts.from_datetime(end_date)

stations = {
    'uaf5': wgs84.latlon(+64.85558159769603, -147.81771958730937, elevation_m=146.304),
    'gilmore': wgs84.latlon(+64.97759214618662, -147.51070745767092, elevation_m=304.8)
}

passes = []
min_el_deg = 5.0

for sat in satellites:
    for st_name, station in stations.items():
        times, events = sat.find_events(station, t0, t1, altitude_degrees=min_el_deg)
        aos_time = None
        for t, event in zip(times, events):
            if event == 0:
                aos_time = t
            elif event == 2 and aos_time is not None:
                passes.append({
                    'station': st_name,
                    'sat': sat.name.strip(),
                    'aos': aos_time.utc_datetime(),
                    'los': t.utc_datetime()
                })
                aos_time = None

df_passes = pd.DataFrame(passes, columns=['station', 'sat', 'aos', 'los'])

if df_passes.empty:
    print("No passes found for the specified period.")
else:
    df_passes = df_passes.sort_values('aos')
    print(f"Calculated {len(df_passes)} passes total over 4 days.")


def find_3plus_conflicts(st_passes):
    events = []
    for _, row in st_passes.iterrows():
        events.append((row['aos'], +1, row['sat']))
        events.append((row['los'], -1, row['sat']))

    events.sort(key=lambda x: x[0])

    active_sats = set()
    prev_time = None
    conflicts_3plus = []

    for time, event_type, sat in events:
        if prev_time is not None and time > prev_time:
            if len(active_sats) >= 2:
                conflicts_3plus.append({
                    'start': prev_time,
                    'end': time,
                    'sats': set(active_sats)
                })

        if event_type == +1:
            active_sats.add(sat)
        else:
            active_sats.discard(sat)

        prev_time = time

    return pd.DataFrame(conflicts_3plus)


dates = pd.date_range(start_date, periods=4, freq='D')

for station_name in df_passes['station'].unique():
    st_passes = df_passes[df_passes['station'] == station_name]
    df_3plus = find_3plus_conflicts(st_passes)

    fig, axes = plt.subplots(nrows=4, ncols=1, figsize=(16, 9), sharex=False, sharey=True)

    sats = sorted(st_passes['sat'].unique())
    sat_y = {sat: i for i, sat in enumerate(sats)}

    for i, day in enumerate(dates):
        ax = axes[i]
        day_start = day.tz_convert('UTC') if day.tzinfo else day.tz_localize('UTC')
        day_end = day_start + pd.Timedelta(days=1)

        d_passes = st_passes[(st_passes['aos'] < day_end) & (st_passes['los'] > day_start)]

        if not df_3plus.empty:
            d_3plus = df_3plus[(df_3plus['start'] < day_end) & (df_3plus['end'] > day_start)]
        else:
            d_3plus = pd.DataFrame()

        for _, row in d_passes.iterrows():
            dur = row['los'] - row['aos']
            ax.barh(sat_y[row['sat']], dur, left=row['aos'], color='#2ca02c', height=0.5, zorder=2)

        if not d_3plus.empty:
            for _, row in d_3plus.iterrows():
                dur = row['end'] - row['start']
                for sat in row['sats']:
                    if sat in sat_y:
                        ax.barh(sat_y[sat], dur, left=row['start'], color='#d62728', height=0.65, zorder=3)

        ax.set_yticks(range(len(sats)))
        ax.set_yticklabels(sats, fontsize=8, fontweight='bold')
        ax.set_title(f"{day.strftime('%A, %b %d')}", fontsize=9, fontweight='bold', loc='left', pad=2)

        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
        ax.set_xlim(day_start, day_end)
        ax.grid(True, axis='x', linestyle='--', alpha=0.4)

    plt.suptitle(f"4-Day Passes/Conflicts - Station: {station_name.upper()}", fontsize=13, fontweight='bold', y=0.995)

    fig.legend(handles=[
        Patch(facecolor='#2ca02c', label='No Conflicts'),
        Patch(facecolor='#d62728', label='2+ Satellite Overlap')
    ], loc='upper right', bbox_to_anchor=(0.99, 0.995), fontsize=9)

    plt.tight_layout(rect=[0, 0, 1, 0.98])
    filename = f"daily_4day_3plus_{station_name}.png"
    plt.savefig(filename, dpi=300)
    print(f"Saved schedule plot: {filename}")
    plt.close()

with open('/home/processing/gits/schedule/forward_plots/schedule/timestamp.json', 'w') as f:
    json.dump({'timestamp': datetime.utcnow().isoformat() + 'Z'}, f)
