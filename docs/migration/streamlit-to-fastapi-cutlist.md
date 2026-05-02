# Streamlit -> FastAPI cut list

## Goal
Move reusable Python business logic out of Streamlit UI code, and expose it as JSON APIs.

## Phase 1 (implemented in this migration skeleton)
- `get_upcoming_races` (legacy/race_catalog.py)
- `resolve_race_id` (legacy/race_catalog.py)
- `fetch_race_csv` (legacy/get_keiba_info.py)
- minimal odds endpoint via fetched CSV (`/api/v1/races/{race_id}/odds`)

## Phase 2 (recommended next)
- race characteristics extraction
- cache read/write wrappers
- training data normalization endpoints

## Phase 3 (later, external API heavy)
- Tavily + Gemini web analysis
- YouTube extraction/analysis
- X search/analysis
- integrated bet plan generation

### Phase 3 current status (incremental)
- External API abstraction layer added (T-M4-01):
  - `app/clients/tavily_client.py`
  - `app/clients/gemini_client.py`
  - `app/services/external_analysis_service.py`
- Minimal validation APIs:
  - `GET /api/v1/external/providers`
  - `POST /api/v1/external/web-summary`
- YouTube / X incremental endpoints added (T-M4-02):
  - `POST /api/v1/external/youtube/search`
  - `POST /api/v1/external/youtube/summary`
  - `POST /api/v1/external/youtube/horse-analysis`
  - `GET /api/v1/external/x/accounts`
  - `POST /api/v1/external/x/search`
  - `POST /api/v1/external/x/summary`
  - `POST /api/v1/external/x/horse-analysis`

## Notes
- Keep Streamlit-specific UI/session functions in `legacy/streamlit_app/app.py`.
- Move only pure or service-like logic to `backend/app/services`.
