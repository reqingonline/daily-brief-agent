from __future__ import annotations

import unittest

from daily_brief_agent import gmail_subscription_manager as manager


OWNER = "owner@example.com"


def address(local: str, domain: str) -> str:
    return f"{local}@{domain}"


def sender_headers(sender: str, **extra: str) -> dict[str, str]:
    headers = {"from": sender}
    headers.update(extra)
    return headers


class SubscriptionSenderFilterTests(unittest.TestCase):
    def test_ordinary_personal_public_or_custom_domain_is_allowed(self):
        self.assertTrue(manager.sender_is_safe(sender_headers(f"Alice <{address('alice', 'gmail.com')}>"), OWNER))
        self.assertTrue(manager.sender_is_safe(sender_headers("friend@personal.example"), OWNER))

    def test_service_and_financial_senders_are_ignored(self):
        blocked = (
            "support@service.example",
            "notification@news.example",
            "alerts@bank.example",
            "person@secure.payments.example",
            address("account", "paypal.com"),
        )
        for sender in blocked:
            with self.subTest(sender=sender):
                self.assertFalse(manager.sender_is_safe(sender_headers(sender), OWNER))

    def test_existing_automated_and_list_guards_remain(self):
        self.assertFalse(manager.sender_is_safe(sender_headers("mailer-daemon@example.com"), OWNER))
        self.assertFalse(manager.sender_is_safe(sender_headers("person@example.com", **{"list-id": "list.example"}), OWNER))
        self.assertFalse(manager.sender_is_safe(sender_headers("person@example.com", **{"auto-submitted": "auto-generated"}), OWNER))


if __name__ == "__main__":
    unittest.main()
