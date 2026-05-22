import subprocess

from config import IMESSAGE_RECIPIENT, IMESSAGE_SENDER


def _escape_applescript(s: str) -> str:
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    # AppleScript string literals cannot contain literal newlines
    s = s.replace("\n", '" & return & "')
    return s


def format_message(parsed: dict, acoustic: dict) -> str:
    rate = acoustic.get("speaking_rate_wpm")
    pause = acoustic.get("pause_ratio")
    rate_str = f"{rate:.0f} wpm" if rate is not None else "—"
    pause_str = f"{pause:.0%} pauses" if pause is not None else "—"

    return (
        f"orb · {parsed.get('mood', '?')}\n\n"
        f"{parsed.get('summary', '')}\n\n"
        f"themes: {parsed.get('themes', '—')}\n"
        f"pattern: {parsed.get('pattern', '—')}\n\n"
        f"q: {parsed.get('question', '—')}\n\n"
        f"⏱ {rate_str} · {pause_str}"
    )


def send(message: str, recipient: str = IMESSAGE_RECIPIENT) -> None:
    safe = _escape_applescript(message)
    # If IMESSAGE_SENDER is set, send from that specific Apple ID handle so the
    # recipient always sees the same sender identity. Otherwise fall back to
    # whichever iMessage service Messages happens to list first.
    if IMESSAGE_SENDER:
        service_clause = (
            f'set targetService to 1st service '
            f'whose service type = iMessage and description = "{IMESSAGE_SENDER}"'
        )
    else:
        service_clause = 'set targetService to 1st service whose service type = iMessage'
    script = (
        f'tell application "Messages"\n'
        f'  {service_clause}\n'
        f'  set targetBuddy to buddy "{recipient}" of targetService\n'
        f'  send "{safe}" to targetBuddy\n'
        f"end tell"
    )
    subprocess.run(["osascript", "-e", script], check=True)
