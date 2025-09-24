import pandas as pd
import re

# ---------- helpers ----------
SUFFIXES = [" jr", " jr.", " sr", " sr.", " ii", " iii", " iv", " v"]

def normalize_name(s: str) -> str:
    if pd.isna(s): return ""
    s = s.strip()
    # Handle "Last, First" -> "First Last"
    if "," in s:
        parts = [p.strip() for p in s.split(",")]
        if len(parts) >= 2:
            s = f"{parts[1]} {parts[0]}"
    s = s.lower()
    # Remove punctuation and collapse spaces
    s = re.sub(r"[.\'`’\-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # Remove common suffixes (jr, sr, ii, iii, etc.)
    for suf in SUFFIXES:
        if s.endswith(suf):
            s = s[: -len(suf)].strip()
    return s

def to_number(x):
    if pd.isna(x): return None
    return pd.to_numeric(str(x).replace("$","").replace(",","").strip(), errors="coerce")

# ---------- load ----------
salaries = pd.read_csv("nba_salaries_2024_25.csv")
stats    = pd.read_csv("season_stats.csv")

# ---------- coerce/standardize salary ----------
if "Salary" in salaries.columns:
    salary_col = "Salary"
else:
    # find column that looks like salary (e.g., "2024-25 Salary", "salary")
    candidates = [c for c in salaries.columns if "salary" in c.lower()]
    if not candidates:
        raise ValueError("No salary column found in salaries CSV.")
    salary_col = candidates[0]
    if salary_col != "Salary":
        salaries.rename(columns={salary_col: "Salary"}, inplace=True)
        salary_col = "Salary"

salaries["Salary"] = salaries["Salary"].apply(to_number)

# ---------- pick latest season in stats ----------
if "Year" not in stats.columns:
    raise ValueError("Expected 'Year' column in season_stats.csv.")
latest_year = int(stats["Year"].max())
stats = stats[stats["Year"] == latest_year].copy()

# ---------- normalize names ----------
if "Player" not in salaries.columns or "Player" not in stats.columns:
    raise ValueError("Both CSVs must have a 'Player' column.")
salaries["Player_norm"] = salaries["Player"].apply(normalize_name)
stats["Player_norm"]    = stats["Player"].apply(normalize_name)

# ---------- select/rename key stat columns ----------
needed_stats_cols = [
    "Player","Player_norm","Tm","Pos","G","MP","PTS","TRB","AST","STL","BLK",
    "FGA","FG","FTA","FT","TOV","Year"
]
have_cols = [c for c in needed_stats_cols if c in stats.columns]
stats = stats[have_cols].copy()
if "Tm" in stats.columns:
    stats.rename(columns={"Tm":"Team"}, inplace=True)

# ---------- merge on normalized name ----------
merged = pd.merge(
    salaries,
    stats,
    on="Player_norm",
    how="inner",
    suffixes=("_sal","_stats")
)

# Display name preference
merged["Player"] = merged.get("Player_sal", merged.get("Player_stats"))

# Prefer team from salaries if present, else from stats
if "Team" not in merged.columns:
    # Some salary datasets use 'Team' or 'Tm'—try to surface one
    salary_team_col = next((c for c in salaries.columns if c.lower() in ("team","tm")), None)
    if salary_team_col and salary_team_col in merged.columns:
        merged.rename(columns={salary_team_col: "Team"}, inplace=True)

# ---------- numeric coercions for stat fields ----------
for col in ["PTS","TRB","AST","STL","BLK","FGA","FG","FTA","FT","TOV"]:
    if col in merged.columns:
        merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0)

# ---------- efficiency ----------
merged["Efficiency"] = (
    merged.get("PTS",0) + merged.get("TRB",0) + merged.get("AST",0) +
    merged.get("STL",0) + merged.get("BLK",0)
    - (merged.get("FGA",0) - merged.get("FG",0))
    - (merged.get("FTA",0) - merged.get("FT",0))
    - merged.get("TOV",0)
)

# ---------- salary per efficiency ----------
# Use pd.NA for divide-by-zero to avoid Inf
merged["Salary_per_Efficiency"] = merged["Salary"] / merged["Efficiency"].replace(0, pd.NA)

# ---------- debug: report matches and export unmatched BEFORE trimming ----------
print(f"Matched rows: {len(merged):,}")
if "Player_norm" in salaries.columns and "Player_norm" in merged.columns:
    matched_norms = set(merged["Player_norm"].dropna().unique())
    unmatched = salaries[~salaries["Player_norm"].isin(matched_norms)]
    unmatched[["Player","Salary"]].to_csv("unmatched_salaries.csv", index=False)
    print("Wrote unmatched_salaries.csv for any players that didn’t match.")
else:
    print("Skipping unmatched export (Player_norm not available).")

# ---------- final column order for Tableau ----------
preferred_order = [
    "Player","Team","Pos","Year","Salary","PTS","TRB","AST","STL","BLK",
    "FGA","FG","FTA","FT","TOV","Efficiency","Salary_per_Efficiency"
]
final_cols = [c for c in preferred_order if c in merged.columns]
# Append any remaining useful columns (skip technical merge helpers)
final_cols += [c for c in merged.columns if c not in final_cols and c not in ["Player_norm","Player_sal","Player_stats"]]
merged = merged[final_cols]

# save output
merged.to_csv("nba_salary_performance_2024.csv", index=False)
print("Cleaned data saved as nba_salary_performance_2024.csv")
