#!/usr/bin/env bash
# צעד ה-commit המשותף לכל ה-workflows שכותבים ל-alerts.db (scan / daily_summary / morning_summary / weekly_report).
# מריצים מתוך שורש ה-repo:  bash ci_commit_alerts_db.sh
#
# הפריסה נקבעת לפי db_layout בהגדרות (config.example.yaml בענן), או DB_LAYOUT בסביבה (בדיקות):
#
#   legacy (ברירת מחדל): בדיוק ההתנהגות הקודמת של scan.yml - בכל push שנדחה: reset --hard ל-origin ומיזוג ברמת SQL
#                        (resolve_alerts_db_conflict.py) כדי לא לדרוס פעולות משתמש שנכתבו לאותו קובץ.
#
#   split: נתוני המשתמש ב-user.db (כותב יחיד: המחשב המקומי), alerts.db נכתב רק כאן. קבצים שונים -> git pull --rebase
#          רגיל עובד (אין קונפליקט בינארי). הסורק רק קורא את user.db, אז שינוי מקרי בו (לא אמור לקרות) נזרק עם אזהרה.
#          ר' DB_SPLIT_PLAN.md סעיף 12.
set -u

if [ "${GITHUB_ACTIONS:-}" = "true" ]; then  # רק בענן; בבדיקות המקומיות הזהות מגיעה ממשתני GIT_AUTHOR_*/GIT_COMMITTER_*
  git config user.name "Stock Scanner Bot"
  git config user.email "actions@github.com"
fi

layout="${DB_LAYOUT:-}"
if [ -z "$layout" ]; then
  layout=$(python -c "from src.config import load_config; from src import store; load_config(); print(store.layout())" 2>/dev/null || echo legacy)
fi
echo "db_layout: $layout"
tmp="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"

if git diff --quiet -- alerts.db; then
  echo "No change in alerts.db, skipping commit."
  exit 0
fi

if [ "$layout" = "split" ]; then
  if [ -f user.db ] && ! git diff --quiet -- user.db; then
    echo "::warning::user.db was modified during the run (the scanner must only read it) - discarding the change."
    git checkout -- user.db
  fi
  cp alerts.db "$tmp"/alerts_ours.db
  git add alerts.db
  git commit -m "Update alerts.db [skip ci]" -- alerts.db
  for i in 1 2 3 4 5; do
    if git push; then
      exit 0
    fi
    echo "Push rejected (attempt $i) - pull --rebase (user pushes only touch user.db/config, not alerts.db)..."
    if ! git pull --rebase --autostash; then
      # רק כותב אחר של alerts.db יכול לגרום לזה (ריצת סורק מקבילה - concurrency אמור למנוע). הסורק מנצח, כמו קודם.
      echo "::warning::alerts.db rebase conflict (another scanner run?) - keeping this run's version on top of origin."
      git rebase --abort 2>/dev/null
      git fetch origin
      git reset --hard origin/master
      cp "$tmp"/alerts_ours.db alerts.db
      git add alerts.db
      git commit -m "Update alerts.db [skip ci]" -- alerts.db
    fi
  done
  echo "Push still failing after 5 attempts - giving up for this run."
  exit 1
fi

# ---- legacy (ללא שינוי מההתנהגות של scan.yml עד 19.11.2026) ----
cp alerts.db "$tmp"/alerts_ours.db
git add alerts.db
git commit -m "Update alerts.db [skip ci]"
success=0
for i in 1 2 3 4 5; do
  if git push; then
    success=1
    break
  fi
  echo "Push rejected (attempt $i) - resyncing with origin and merging..."
  git fetch origin
  git reset --hard origin/master
  cp alerts.db "$tmp"/alerts_fresh.db
  python resolve_alerts_db_conflict.py "$tmp"/alerts_ours.db "$tmp"/alerts_fresh.db alerts.db
  git add alerts.db
  git commit -m "Update alerts.db [skip ci]"
done
if [ "$success" -ne 1 ]; then
  echo "Push still failing after 5 attempts - giving up for this run."
  exit 1
fi
