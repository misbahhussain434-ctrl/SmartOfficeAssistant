# Smart Office Assistant (Streamlit)

An interactive Streamlit app to:
- Upload an email CSV (or paste a single email)
- Generate an email summary (uses a Hugging Face summarization model with a safe fallback)
- Create and manage tasks in a local SQLite database
- Suggest the next available meeting time based on saved calendar events

## Run

1. Install dependencies:
   - `pip install -r requirements.txt`
2. Start the app:
   - `streamlit run app.py`

The app will create `office_assistant.db` in the project directory by default (path is configurable in the sidebar).

## Notes

- Summarization may download a model on first run. If downloads fail (offline environment, missing dependencies, etc.), the app falls back to a simple heuristic summary.
- CSV support is column-based: choose which column contains the email body/text.


