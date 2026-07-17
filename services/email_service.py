"""
services/email_service.py — SMTP email sending. Moved verbatim from app.py.
"""

import os
import resend

# Email Verification Token Store (in-memory + DB backed) — kept as-is from
# the original app.py. Not currently read anywhere else in the codebase
# (verification is actually tracked via the email_tokens DB table), but
# preserved rather than silently dropped during the move.
_verify_tokens = {}  # token -> user_id

resend.api_key = os.getenv("RESEND_API_KEY")


def send_email(to_email, subject, html):
    try:
        resend.Emails.send({
            "from": os.getenv("FROM_EMAIL"),
            "to": [to_email],
            "subject": subject,
            "html": html
        })
        return True
    except Exception as e:
        print(f"[Resend] Email failed: {e}")
        return False
def send_verification_email(to_email, username, token):
    verify_url = (
        os.environ.get("APP_URL", "http://localhost:5000")
        + f"/verify_email/{token}"
    )

    html = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:auto;padding:2rem;background:#0f172a;color:#e2e8f0;border-radius:12px">
      <h2 style="color:#4d9de0">⚡ DSA Tracker</h2>
      <p>Hi <strong>{username}</strong>! Verify your email to activate your account.</p>

      <a href="{verify_url}"
         style="display:inline-block;margin:1.5rem 0;padding:.75rem 2rem;
                background:#4d9de0;color:#fff;text-decoration:none;
                border-radius:8px;font-weight:700">
        ✅ Verify Email
      </a>

      <p style="color:#64748b;font-size:.85rem">
        Link expires in 24 hours. If you did not sign up, ignore this email.
      </p>
    </div>
    """

    try:
        if send_email(
            to_email,
            "DSA Tracker — Verify your email",
            html
        ):
            print(f"[Email] Verification sent to {to_email}")
            return True

        return False
    except Exception as e:
        print(f"[Email] Failed: {e}")
        return False