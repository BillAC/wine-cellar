import smtplib
import logging
from datetime import datetime
from email.message import EmailMessage

from env_settings import get_settings, load_app_env

load_app_env()

logger = logging.getLogger("wine_app.email")
EMAIL_LOG_FILE = get_settings().email_log_file


class EmailService:
    """
    Email delivery service for The Local AI Wine Hub.

    Supports standard SMTP (STARTTLS or SSL) when configured.
    When SMTP is not configured or fails, gracefully falls back to logging the
    full email (including activation / reset links) to `sent_emails.log`
    so the system remains 100% operational in offline / local environments.
    """

    def __init__(self):
        self.settings = get_settings()
        self.smtp_host = self.settings.smtp_host
        self.smtp_port = self.settings.smtp_port
        self.smtp_user = self.settings.smtp_user
        self.smtp_password = self.settings.smtp_password
        self.smtp_from = self.settings.smtp_from
        self.smtp_tls = self.settings.smtp_tls
        self.smtp_ssl = self.settings.smtp_ssl
        self.base_url = self.settings.public_base_url or "http://localhost:8000"

    def _log_email_locally(self, to_email: str, subject: str, content: str, action_url: str | None = None) -> None:
        timestamp = datetime.now().isoformat()
        log_entry = (
            f"================================================================================\n"
            f"TIMESTAMP: {timestamp}\n"
            f"TO:        {to_email}\n"
            f"FROM:      {self.smtp_from}\n"
            f"SUBJECT:   {subject}\n"
        )
        if action_url:
            log_entry += f"LINK:      {action_url}\n"
        log_entry += f"CONTENT:\n{content}\n"
        log_entry += f"================================================================================\n\n"

        try:
            EMAIL_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(EMAIL_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(log_entry)
        except Exception as e:
            logger.error("Could not write to local email log: %s", e)

    def send_email(
        self,
        to_email: str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
        action_url: str | None = None,
    ) -> bool:
        """Sends an email via SMTP if configured, and records it to `sent_emails.log`."""
        self._log_email_locally(to_email, subject, body_text, action_url)

        if not self.smtp_host:
            logger.info("SMTP not configured. Email to %s saved to local log: %s", to_email, subject)
            return True

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.smtp_from
        msg["To"] = to_email
        msg.set_content(body_text)

        if body_html:
            msg.add_alternative(body_html, subtype="html")

        try:
            if self.smtp_ssl:
                with smtplib.SMTP_SSL(
                    self.smtp_host,
                    self.smtp_port,
                    timeout=self.settings.smtp_timeout_seconds,
                ) as server:
                    if self.smtp_user and self.smtp_password:
                        server.login(self.smtp_user, self.smtp_password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(
                    self.smtp_host,
                    self.smtp_port,
                    timeout=self.settings.smtp_timeout_seconds,
                ) as server:
                    if self.smtp_tls:
                        server.starttls()
                    if self.smtp_user and self.smtp_password:
                        server.login(self.smtp_user, self.smtp_password)
                    server.send_message(msg)

            logger.info("Successfully sent email to %s: %s", to_email, subject)
            return True
        except Exception as e:
            logger.warning(
                "Failed to send email via SMTP (%s:%s): %s. Email was recorded in local log.",
                self.smtp_host,
                self.smtp_port,
                e,
            )
            return False

    def send_approval_email(self, to_email: str, username: str, reset_token: str | None = None) -> bool:
        """Notifies user that their access request has been approved."""
        subject = "🍷 Cellar Access Approved - Welcome to The Local AI Wine Hub"
        login_url = f"{self.base_url}/"

        if reset_token:
            action_url = f"{self.base_url}/?token={reset_token}#set-password"
            body_text = (
                f"Hello {username},\n\n"
                f"Your access request for The Local AI Wine Hub has been approved by the cellar administrator.\n\n"
                f"To complete your registration and set your account password, please visit:\n"
                f"{action_url}\n\n"
                f"If you did not request access, please disregard this email.\n\n"
                f"Cheers,\nThe Cellar Team"
            )
        else:
            action_url = login_url
            body_text = (
                f"Hello {username},\n\n"
                f"Your access request for The Local AI Wine Hub has been approved by the cellar administrator.\n\n"
                f"You can now sign in with your credentials at:\n"
                f"{login_url}\n\n"
                f"Cheers,\nThe Cellar Team"
            )

        return self.send_email(to_email, subject, body_text, action_url=action_url)

    def send_password_reset_email(self, to_email: str, username: str, reset_token: str) -> bool:
        """Sends password reset link to user."""
        subject = "🍷 Password Reset - The Local AI Wine Hub"
        reset_url = f"{self.base_url}/?token={reset_token}#reset-password"
        body_text = (
            f"Hello {username},\n\n"
            f"A password reset was requested for your account at The Local AI Wine Hub.\n\n"
            f"Please visit the following link to choose a new password:\n"
            f"{reset_url}\n\n"
            f"This link will expire in 1 hour. If you did not request a password reset, you can safely ignore this email.\n\n"
            f"Cheers,\nThe Cellar Team"
        )
        return self.send_email(to_email, subject, body_text, action_url=reset_url)
