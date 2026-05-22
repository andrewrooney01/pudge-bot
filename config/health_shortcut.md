# Apple Health iOS Shortcut Setup

The orb reads daily health + location data from a JSON file the Shortcut writes
to iCloud Drive.  One file per day, named `YYYY-MM-DD.json`, saved to:

```
iCloud Drive / Health / YYYY-MM-DD.json
```

On your Mac this resolves to:
```
~/Library/Mobile Documents/com~apple~CloudDocs/Health/
```

---

## Step 1 — Create the Shortcut

Open **Shortcuts** on your iPhone, tap **+**, name it **"Orb Health Export"**.

Add the following actions in order:

### 1. Set variable `today`
- Action: **Format Date**
- Date: Current Date
- Format: Custom → `yyyy-MM-dd`
- Save result as variable → `today`

### 2. Fetch step count
- Action: **Find Health Samples**
- Type: **Step Count**
- Grouped by: **Day**
- Start: Beginning of Today  →  End: Current Date
- Save as variable → `steps_samples`

- Action: **Get Numbers from** `steps_samples` → Get **Sum** → Save as `steps`

### 3. Fetch active energy
- Action: **Find Health Samples**
- Type: **Active Energy Burned**
- Grouped by: Day, Start: Beginning of Today, End: Current Date
- **Get Numbers** → Sum → Save as `active_energy`

### 4. Fetch exercise minutes
- Action: **Find Health Samples**
- Type: **Apple Exercise Time**
- Grouped by: Day, Start: Beginning of Today, End: Current Date
- **Get Numbers** → Sum → Save as `exercise_minutes`

### 5. Fetch stand hours
- Action: **Find Health Samples**
- Type: **Apple Stand Hour**
- Grouped by: Day, Start: Beginning of Today, End: Current Date
- **Get Numbers** → Sum → Save as `stand_hours`

### 6. Fetch resting heart rate
- Action: **Find Health Samples**
- Type: **Resting Heart Rate**
- Grouped by: Day, Start: Beginning of Today, End: Current Date
- **Get Numbers** → Average → Save as `rhr`

### 7. Fetch HRV
- Action: **Find Health Samples**
- Type: **Heart Rate Variability**
- Grouped by: Day, Start: Beginning of Today, End: Current Date
- **Get Numbers** → Average → Save as `hrv`

### 8. Fetch respiratory rate
- Action: **Find Health Samples**
- Type: **Respiratory Rate**
- Grouped by: Day, Start: Beginning of Today, End: Current Date
- **Get Numbers** → Average → Save as `resp_rate`

### 9. Fetch workouts
- Action: **Find Workouts**
- Filter: Start Date is after Beginning of Today
- Save as variable → `workouts`

### 10. Build the metrics dictionary
- Action: **Dictionary**
  - `steps` → `steps`
  - `active_energy_kcal` → `active_energy`
  - `exercise_minutes` → `exercise_minutes`
  - `stand_hours` → `stand_hours`
  - `resting_heart_rate` → `rhr`
  - `hrv_ms` → `hrv`
  - `respiratory_rate` → `resp_rate`
- Save as `metrics_dict`

### 11. Build workouts list (repeat block)
- Action: **Repeat with each item** in `workouts`
  - Inside loop, build a Dictionary:
    - `type` → Repeat Item → Workout Type
    - `start` → Repeat Item → Start Date (ISO 8601)
    - `end` → Repeat Item → End Date (ISO 8601)
    - `duration_min` → Repeat Item → Duration (minutes)
    - `distance_km` → Repeat Item → Total Distance (km)
    - `active_energy_kcal` → Repeat Item → Active Energy Burned
  - Append Dictionary to variable `workouts_list`

### 12. Build the root payload
- Action: **Dictionary**
  - `date` → `today`
  - `exported_at` → Current Date (ISO 8601)
  - `metrics` → `metrics_dict`
  - `workouts` → `workouts_list`
- Save as `payload`

### 13. Convert to JSON and save
- Action: **Get Text from** `payload` (converts dict to JSON)
- Action: **Save File**
  - Destination: iCloud Drive → Health → (file name: `today`)
  - If file exists: **Replace**
  - File extension: `.json`

---

## Step 2 — Automate it

1. In Shortcuts → **Automation** tab → **+** → **Time of Day**
2. Set to run at **11:55 PM**, every day
3. Run Shortcut: **Orb Health Export**
4. Turn off "Ask Before Running"

This ensures a full day's data is captured before midnight.

---

## Step 3 — Verify

After the Shortcut runs once (tap to run manually first), check:

```bash
ls ~/Library/Mobile\ Documents/com\~apple\~CloudDocs/Health/
```

You should see a file like `2024-01-15.json`.  Then sync it into the orb:

```bash
cd ~/Projects/the-orb
.venv/bin/python src/health.py
```

---

## Location data

The Shortcut captures **workout GPS routes** automatically when you have a
workout tracked with GPS (outdoor runs, walks, cycling).  Each workout entry
includes a `route` array with lat/lon/timestamp points.

For coarser significant-place tracking (home / gym / office), Apple's
Significant Locations are not programmatically accessible without a native
signed app — workout routes are the best Apple provides via Shortcuts.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Health export directory not found` | Run the Shortcut at least once; iCloud may take a minute to sync |
| Steps = 0 | Check iPhone Settings → Privacy → Health → Shortcuts → allow Step Count |
| File not appearing on Mac | Open Files app on iPhone, confirm iCloud Drive / Health folder exists |
