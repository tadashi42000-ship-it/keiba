# keiba

This branch prepares the repository for a Next.js + FastAPI migration while preserving the current Streamlit app.

## Structure

- `legacy/streamlit_app/` : existing Streamlit implementation
- `backend/` : new FastAPI backend workspace
- `frontend/` : new Next.js frontend workspace
- `docs/` : project and migration documents

## Run Legacy Streamlit App

```bash
cd legacy/streamlit_app
streamlit run app.py
```

## Notes

- Current Streamlit files were moved with `git mv` where possible.
- New migration work should be developed under `backend/` and `frontend/`.
