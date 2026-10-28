# LawNexa Admin Dashboard Fix

This bundle aligns the admin page with the saved LawNexa backend source and adds protected admin actions that the page calls.

## Files
- `main.py` — backend with aligned overview metrics, pending-lawyer route already used by the API, plus protected reject/suspend/reactivate routes.
- `models.py` — matching SQLAlchemy model set from the recent saved project version.
- `requirements.txt` — matching dependencies.
- `admin.html` — dashboard uses `/api/v1/admin/lawyers/pending` and the response's `lawyer_id`.

## Apply carefully
1. Back up the four existing files in your local `lawnexa` folder.
2. Copy these four files over the matching files in the project folder. Do not overwrite `database.py`, `index.html`, `.env`, or the database.
3. Run `python -m py_compile main.py models.py`.
4. Run `python -m pytest -q .\test_main.py`.
5. Inspect `git diff -- main.py models.py requirements.txt admin.html`; only commit these four files after reviewing.
6. Push the commit to `main`; wait for Render to deploy, then verify `/openapi.json` includes the admin routes and reload `https://lawnexa.vercel.app/admin.html`.

## Important
- This is a code bundle, not a live deployment. It does not push to GitHub or deploy to Render by itself.
- Ensure Render has `ENVIRONMENT=production`, a strong `SECRET_KEY` (32+ characters), `ALLOWED_ORIGINS=https://lawnexa.vercel.app`, and your existing database configuration. Never commit `.env` or real secrets.
- The escrow balance is deliberately `null` because this backend does not calculate a verified escrow balance.
