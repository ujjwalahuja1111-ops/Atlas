# Atlas Command Cheatsheet

## Daily
```
cd backend && uvicorn server:app --reload
cd frontend && npm start
```

## Database
```
cd backend && python -m scripts.bootstrap --reset
cd backend && python -m scripts.bootstrap
cd backend && python -m scripts.db_reset --yes
cd backend && python -m scripts.bootstrap --verify
```

## Tests
```
cd backend && python -m pytest tests/test_acdp_catalog.py tests/test_acdp_dev_wiring.py tests/test_bootstrap.py tests/test_cre_architecture_guards.py tests/test_cre_projections.py tests/test_cre_rules.py tests/test_dev02_bootstrap_reliability.py -q
cd frontend && npx tsc --noEmit
cd frontend && npm run lint
```

## Production
```
POST /api/auth/register  {"phone": "...", "name": "..."}
GET /api/
cd backend && python -m scripts.bootstrap --verify
```

## Development
```
cd backend && pip install -r requirements.txt
cd frontend && npm install
cd frontend && npx expo install --check
cd frontend && npx expo install --fix
cd frontend && npx expo start --clear
cd frontend && npm run android
cd frontend && npm run ios
cd frontend && npm run web
```
