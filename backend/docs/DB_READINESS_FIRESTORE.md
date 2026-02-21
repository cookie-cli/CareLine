# Firestore DB Readiness

This backend uses Firestore directly (no SQL migrations). Readiness means consistent schema, required indexes, and recovery plans.

## Collections
- `users`
- `prescriptions`
- `nudges`
- `link_codes`

## Required index posture
- Query patterns in repositories/services that can require Firestore indexes:
  - `prescriptions.where("caretaker_id","==",...).order_by("created_at", desc)`
  - `prescriptions.where("user_id","==",...).order_by("created_at", desc)`
  - `prescriptions.where("expiry_date","<=",...).where("expiry_date",">=",...).where("status","==",...).where("expiry_alert_sent","!=",True)`
  - `nudges` queries with multiple `where` clauses + ordering (from `backend/app/repositories/nudges.py`)

## How to validate indexes
1. Run endpoint suites that touch prescriptions, status, nudges, and linking.
2. In GCP console, verify no index-related errors in Firestore logs.
3. Add missing indexes in Firestore Indexes and re-run tests.

## Data constraints (enforce at write layer)
- `users`:
  - `role` in `admin|caretaker|user`
  - `caretaker_id` present for linked users
- `prescriptions`:
  - `created_at` set for every write
  - ownership fields (`user_id` and/or `caretaker_id`) set consistently
  - `status` uses controlled values (at least `active`)
- `link_codes`:
  - hash-only storage for code values (already in service layer)
  - expiration timestamp and single-use semantics

## Backup and restore
- Enable scheduled Firestore export to GCS bucket (daily recommended).
- Keep at least 7-30 days retention depending on compliance needs.
- Test restore monthly in a staging project.

## Release gate
- No missing Firestore index errors during full auth test run.
- Backup job configured and last run successful.
- Restore drill performed at least once in staging.
