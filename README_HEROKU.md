
# Heroku deployment — Telegram Subscription Sales Manager

## Important database change
This Heroku version uses PostgreSQL, not SQLite. Heroku dyno filesystems are ephemeral, so SQLite data stored on a dyno can disappear after restarts/deploys. Attach Heroku Postgres and use the `DATABASE_URL` config var.

## 1. Create Telegram bot credentials
- Create a bot with `@BotFather` and copy its token.
- Get your numeric Telegram user ID.
- Never share the token or commit `.env`.

## 2. Install Heroku CLI and Git
Install the Heroku CLI and Git on your computer, then sign in:

```bash
heroku login
```

Unzip this project and open a terminal in its folder.

## 3. Create Heroku app and attach PostgreSQL
```bash
heroku create your-unique-app-name
heroku addons:create heroku-postgresql:essential-0
```

If the selected Postgres plan is unavailable on your account/region, choose an available Heroku Postgres plan from the dashboard and attach it.

## 4. Set secrets
```bash
heroku config:set BOT_TOKEN="YOUR_BOT_TOKEN"
heroku config:set ADMIN_ID="YOUR_NUMERIC_TELEGRAM_USER_ID"
```

Heroku automatically supplies `DATABASE_URL` when Postgres is attached. Check:
```bash
heroku config:get DATABASE_URL
```
Do not paste the database URL into public chats or commit it to Git.

## 5. Deploy
```bash
git init
git add .
git commit -m "Deploy Telegram subscription manager"
heroku git:remote -a your-unique-app-name
git push heroku main
```

If your local branch is named `master`, use:
```bash
git push heroku master:main
```

## 6. Start one worker dyno
```bash
heroku ps:scale worker=1
heroku ps
heroku logs --tail
```

There is no web dyno required for this Telegram long-polling bot. Run exactly one worker to avoid multiple bot polling processes.

## 7. Test
Open your bot in Telegram and send `/start`. Then test `/addstock`, `/stock`, `/sell`, `/report` and `/report month`.

## Notes
- Heroku worker dynos run continuously only while you have an active paid dyno allocation. Check current Heroku pricing and account quota.
- PostgreSQL persists records across dyno restarts; the dyno filesystem does not.
- Keep a separate database backup. Review Heroku Postgres backup options and your plan.
- This bot records product names, purchase costs, customer references and transactions. Do not store passwords, session cookies, recovery codes or other account credentials.
- Only sell/transfer software subscriptions where the provider's terms and your authorization allow it.
