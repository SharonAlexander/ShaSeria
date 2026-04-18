# config.py — fill these in before running bot.py

# ── Telegram ───────────────────────────────────────────────────────────────────
BOT_TOKEN    = "YOUR_BOT_TOKEN_HERE"      # from @BotFather
YOUR_CHAT_ID = 123456789                  # from @userinfobot

# ── GitHub ─────────────────────────────────────────────────────────────────────
GITHUB_USER  = "your-github-username"     # e.g. "sharon"
GITHUB_REPO  = "ddmalar-serials"          # your repo name
GITHUB_TOKEN = ""                         # only needed if repo is PRIVATE
                                          # create at github.com/settings/tokens

# ── Schedule ───────────────────────────────────────────────────────────────────
TIMEZONE     = "Asia/Kolkata"

# GitHub Actions runs at 9:00 AM IST (3:30 AM UTC set in scrape.yml)
# Bot pushes to your chat 30 minutes later to let Actions finish
PUSH_HOUR          = 9
PUSH_MINUTE        = 30
PUSH_DELAY_MINUTES = 0    # extra wait inside the push job (usually 0 is fine)