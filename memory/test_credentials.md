# Test Credentials — Construction Site Assistant Pilot

Auth is simple phone+name login (no OTP). Any phone/name combination creates an account if not exists.

## Seed Test User
- Phone: `9999988888`
- Name: `Test User`
- Role: `supervisor`

## Other example test users (auto-create on first login)
- Phone: `9111111111`, Name: `Rajesh Kumar`, Role: `supervisor`
- Phone: `9222222222`, Name: `Priya Coordinator`, Role: `coordinator`
- Phone: `9333333333`, Name: `Mr. Sharma`, Role: `management`

## Login Endpoint
POST /api/auth/login
```json
{ "phone": "9999988888", "name": "Test User", "role": "supervisor" }
```
Returns: `{ token, user }`. Use `Authorization: Bearer <token>` for all subsequent calls.

## Known Limitation
EMERGENT_LLM_KEY budget shows 0 — AI structuring (GPT-4o & Whisper) falls back gracefully but won't produce structured fields until user tops up balance in Profile → Universal Key → Add Balance.
