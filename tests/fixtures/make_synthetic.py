"""Generate tests/fixtures/synthetic.mbox — run once to (re)create the fixture."""
import mailbox
from pathlib import Path

MESSAGES = [
    # Thread 1: medical billing (2 messages)
    (
        "From user@example.com Mon Jan 01 10:00:00 2024\n"
        "From: billing@hospital.example.com\n"
        "To: user@example.com\n"
        "Subject: Your Hospital Bill - Account #10001\n"
        "Date: Mon, 01 Jan 2024 10:00:00 +0000\n"
        "Message-ID: <syn-medical-001@hospital.example.com>\n"
        "X-Gmail-Labels: Inbox,Important\n"
        "\n"
        "Dear Patient,\n"
        "\n"
        "Please find attached your statement for services rendered on 2023-12-15.\n"
        "Balance due: $350.00. Please pay within 30 days.\n"
        "\n"
        "Thank you,\nHospital Billing Dept\n"
    ),
    (
        "From user@example.com Mon Jan 01 11:00:00 2024\n"
        "From: user@example.com\n"
        "To: billing@hospital.example.com\n"
        "Subject: Re: Your Hospital Bill - Account #10001\n"
        "Date: Mon, 01 Jan 2024 11:00:00 +0000\n"
        "Message-ID: <syn-medical-002@example.com>\n"
        "In-Reply-To: <syn-medical-001@hospital.example.com>\n"
        "References: <syn-medical-001@hospital.example.com>\n"
        "X-Gmail-Labels: Sent\n"
        "\n"
        "Hello,\n"
        "\n"
        "I have a question about line item 3 on the statement.\n"
        "Please clarify the charge for the overnight stay.\n"
        "\n"
        "Thanks\n"
    ),
    # Thread 2: USPS Informed Delivery (standalone)
    (
        "From user@example.com Tue Jan 02 08:00:00 2024\n"
        "From: auto-reply@usps.com\n"
        "To: user@example.com\n"
        "Subject: Your Informed Delivery Daily Digest\n"
        "Date: Tue, 02 Jan 2024 08:00:00 +0000\n"
        "Message-ID: <syn-usps-001@usps.com>\n"
        "X-Gmail-Labels: Inbox\n"
        "\n"
        "Here are the mail pieces scheduled for delivery today:\n"
        "- Letter from County Tax Office\n"
        "- Package from online retailer\n"
    ),
    # Thread 3: utility bill
    (
        "From user@example.com Wed Jan 03 09:00:00 2024\n"
        "From: noreply@electric.example.com\n"
        "To: user@example.com\n"
        "Subject: Your January Statement is Ready\n"
        "Date: Wed, 03 Jan 2024 09:00:00 +0000\n"
        "Message-ID: <syn-utility-001@electric.example.com>\n"
        "X-Gmail-Labels: Inbox,Bills\n"
        "\n"
        "Your statement for January 2024 is now available.\n"
        "Amount due: $124.87\n"
        "Due date: 2024-01-25\n"
        "\n"
        "Log in at electric.example.com to view your bill.\n"
    ),
    # Thread 4: personal correspondence
    (
        "From user@example.com Thu Jan 04 14:00:00 2024\n"
        "From: friend@example.net\n"
        "To: user@example.com\n"
        "Subject: Catching up\n"
        "Date: Thu, 04 Jan 2024 14:00:00 +0000\n"
        "Message-ID: <syn-personal-001@example.net>\n"
        "X-Gmail-Labels: Inbox,Personal\n"
        "\n"
        "Hey,\n"
        "\n"
        "Hope you're doing well! Been a while since we talked.\n"
        "Let me know if you're free this weekend.\n"
        "\n"
        "Cheers\n"
    ),
]


def build(dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    mbox = mailbox.mbox(str(dest), create=True)
    mbox.lock()
    try:
        for raw in MESSAGES:
            mbox.add(mailbox.mboxMessage(raw))
        mbox.flush()
    finally:
        mbox.unlock()
    print(f"Wrote {len(MESSAGES)} messages to {dest}")


if __name__ == "__main__":
    build(Path(__file__).parent / "synthetic.mbox")
