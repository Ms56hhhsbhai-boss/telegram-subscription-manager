# SCARFACE CONTROL — MongoDB edition

This version keeps the existing Telegram bot workflow and switches its storage layer from PostgreSQL to MongoDB Atlas. Inventory details remain a single multiline text field. Photos use Telegram `file_id`. Supplier, cost, sales, customer history, expenses, reports and reset functionality are retained.

## Heroku configuration
Set these Config Vars: `BOT_TOKEN`, `ADMIN_ID`, `MONGODB_URI`, and optionally `MONGODB_DATABASE` (defaults to `scarface_control`). `MONGODB_URI` is the MongoDB Atlas connection string. Never commit it or share it.

Do not remove the existing `DATABASE_URL` or delete the old PostgreSQL database until you have exported/backed up any records you need. This code does not automatically migrate PostgreSQL records; it starts using MongoDB as a new database.

## Deploy
Replace `bot.py`, `database.py`, and `requirements.txt` in the GitHub repository with the files in this ZIP, then deploy the `main` branch. Keep `Procfile` (`worker: python bot.py`) and `.python-version` unchanged. In Heroku Config Vars, add `MONGODB_URI` and set it to your Atlas connection string. Restart the worker after deployment.

## Security
Restrict Atlas database-user permissions where practical, use a unique strong password, and keep the connection string private. The bot is admin-only.
