# CareLine Backend Architecture

## 1. Security-First Layering
- API Layer (`app/routers/*`): request parsing, auth dependencies, response shaping only.
- Policy Layer (`app/security.py`): authentication, role authorization, resource ownership checks, rate limiting.
- Service Layer (`app/services/*`): business workflows and orchestration.
- Repository Layer (`app/repositories/*`): Firestore access only. No direct `db.collection(...)` in routers.
- Integration Layer (`app/services/transcription.py`, `app/services/extraction.py`, `app/routers/scanner.py`): external AI provider interaction with sanitized failures.

## 2. Data Model and Storage
Primary collections:
- `users`
- `care_links`
- `link_codes`
- `prescriptions`
- `nudges`
- `call_logs`

Recommended shared fields for all documents:
- `id`, `status`, `created_at`, `updated_at`, `created_by`, `updated_by`, `version`

Prescription model (core):
- Identity: `id`, `user_id`, `caretaker_id`
- Clinical: `medicines[]`, `diagnosis[]`, `symptoms[]`, `dosage_instructions`
- Lifecycle: `status`, `start_date`, `expiry_date`, `duration_days`, `reviewed`, `source`
- Meta: `prescription_date`, `doctor_name`, `clinic_name`, `notes`

Nudge model (core):
- Identity: `id`, `user_id`, `caretaker_id`, `prescription_id?`
- Scheduling: `date`, `time_bucket`, `target_role`
- Action: `type`, `status`, `actions[]`, `response`, `acknowledged_at`
- Message: `message`

## 3. Query and Index Strategy
High-frequency queries should have Firestore composite indexes:
- `prescriptions(caretaker_id, status, created_at desc)`
- `prescriptions(user_id, status, created_at desc)`
- `nudges(caretaker_id, date, target_role)`
- `nudges(user_id, date, target_role)`
- `nudges(caretaker_id, type, status)` for expiry-alert inbox

Retention:
- archive or TTL old `nudges` and `call_logs` to control cost and query latency.

## 4. Time and Space Complexity (Hot Paths)
- `GET /prescriptions`: `O(n)` time on matching documents, `O(n)` response memory.
- `GET /prescriptions/{id}`: `O(1)` time and space.
- `POST /nudges/sync-daily`: `O(e + b)` where `e` is existing nudge scans and `b=3` buckets.
- `GET /nudges/inbox/*`: `O(n)` time and `O(n)` memory for the day’s result set.
- Upload persistence: `O(file_size)` time and `O(chunk_size)` memory due to streaming chunks.

## 5. External API Integration Standards
For Groq/Firebase integrations:
- strict timeout and retry policy (bounded attempts, exponential backoff)
- sanitized error mapping (never expose provider raw errors to clients)
- correlation IDs in logs for tracing
- idempotency strategy for write endpoints that may retry (`finalize`, nudges generation)

## 6. Current State
- Router-to-Firestore direct access has been replaced by repositories for `prescriptions`, `nudges`, and `users`.
- AuthN/AuthZ and route-level security controls are centralized in `app/security.py`.
- Upload size controls, secure RNG, and XSS-safe rendering are implemented.

## 7. Automated Security Validation
- Endpoint registry: `tests/catalog/endpoints.json`
- Security test bot: `tests/scripts/api_security_bot.py`
- Testing guide: `tests/docs/TESTING_GUIDE.md`

This provides repeatable unauthenticated and authenticated API checks with configurable endpoint coverage by tags and endpoint IDs.

## 8. Debug/Test Surface Controls
- `AUTH_DEBUG` (default `false`): include backend token verify error details only for local debugging.
- `ENABLE_TEST_TOOLS` (default `false`): blocks `/static/auth-test.html` in normal runtime.

Keep both disabled for production deployments.
