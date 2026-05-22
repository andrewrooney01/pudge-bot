"""Interactive helper to discover a bot's chat_id.

Usage:
    python src/telegram_setup.py <bot-token>

After creating a bot with @BotFather:
    1. Send any message (e.g. "hi") to the bot from the account that will
       own it.
    2. Run this script with the bot's token.
    3. It long-polls Telegram, prints the chat_id of the first incoming
       message, and exits.

Paste the chat_id into the corresponding entry in config_local.py.
"""
import sys
import time

from telegram_client import TelegramClient, TelegramError


def main(token: str) -> int:
    client = TelegramClient(token)

    # Validate token first — fail fast with a clear message.
    try:
        me = client.get_me()
    except TelegramError as e:
        print(f"ERROR: token rejected by Telegram: {e}")
        return 1
    print(f"Bot identity: @{me['username']} (id={me['id']})")
    print("Send any message to the bot now from your account…")

    # Long-poll until we see something.
    offset = None
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            updates = client.get_updates(offset=offset, timeout=20)
        except TelegramError as e:
            print(f"ERROR: getUpdates failed: {e}")
            return 1

        for u in updates:
            offset = u["update_id"] + 1
            msg = u.get("message") or u.get("edited_message")
            if not msg:
                continue
            chat = msg.get("chat", {})
            chat_id = chat.get("id")
            sender = msg.get("from", {}).get("username") or msg.get("from", {}).get("id")
            print(f"\n✓ Got message from @{sender}: {msg.get('text', '<no text>')!r}")
            print(f"  chat_id = {chat_id}")
            print(f"\nPaste this into config_local.py:")
            print(f'    "chat_id": {chat_id},')
            return 0

    print("Timed out after 120s without seeing a message.")
    return 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python src/telegram_setup.py <bot-token>")
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
