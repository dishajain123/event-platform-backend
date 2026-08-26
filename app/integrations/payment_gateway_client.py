"""
Generic payment gateway client interface.

The business logic speaks to this interface only. The concrete
Razorpay-style implementation is intentionally tiny and deterministic
so the rest of the app can verify and reconcile payments without
hardcoding provider behavior everywhere.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

from app.config import get_settings


@dataclass(slots=True)
class GatewayOrder:
    order_id: str
    amount: int
    currency: str
    receipt: str


@dataclass(slots=True)
class GatewayRefund:
    refund_id: str
    payment_id: str
    amount: int


class PaymentGatewayClient:
    def create_order(self, *, amount: int, currency: str, receipt: str) -> GatewayOrder:
        raise NotImplementedError

    def verify_payment(self, *, order_id: str, payment_id: str, signature: str) -> bool:
        raise NotImplementedError

    def initiate_refund(self, *, payment_id: str, amount: int) -> GatewayRefund:
        raise NotImplementedError


class RazorpayPaymentGatewayClient(PaymentGatewayClient):
    def __init__(self) -> None:
        self.settings = get_settings()

    def _sign(self, order_id: str, payment_id: str) -> str:
        secret = self.settings.payment_gateway_key_secret.encode()
        payload = f"{order_id}|{payment_id}".encode()
        return hmac.new(secret, payload, hashlib.sha256).hexdigest()

    def create_order(self, *, amount: int, currency: str, receipt: str) -> GatewayOrder:
        return GatewayOrder(
            order_id=f"order_{secrets.token_hex(12)}",
            amount=amount,
            currency=currency,
            receipt=receipt,
        )

    def verify_payment(self, *, order_id: str, payment_id: str, signature: str) -> bool:
        return hmac.compare_digest(self._sign(order_id, payment_id), signature)

    def initiate_refund(self, *, payment_id: str, amount: int) -> GatewayRefund:
        return GatewayRefund(
            refund_id=f"rfnd_{secrets.token_hex(12)}",
            payment_id=payment_id,
            amount=amount,
        )


def get_payment_gateway_client() -> PaymentGatewayClient:
    return RazorpayPaymentGatewayClient()
