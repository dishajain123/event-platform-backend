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

import httpx

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


@dataclass(slots=True)
class GatewayPaymentSnapshot:
    payment_id: str
    order_id: str
    status: str
    amount: int
    currency: str


@dataclass(slots=True)
class GatewayRefundSnapshot:
    refund_id: str
    payment_id: str
    status: str
    amount: int


class PaymentGatewayClient:
    def create_order(self, *, amount: int, currency: str, receipt: str) -> GatewayOrder:
        raise NotImplementedError

    def verify_payment(
        self,
        *,
        order_id: str,
        payment_id: str,
        signature: str,
        expected_amount: int | None = None,
        expected_currency: str | None = None,
    ) -> bool:
        raise NotImplementedError

    def payment_signature(self, *, order_id: str, payment_id: str) -> str:
        raise NotImplementedError

    def verify_webhook_signature(self, body: bytes, signature: str) -> bool:
        raise NotImplementedError

    def initiate_refund(self, *, payment_id: str, amount: int) -> GatewayRefund:
        raise NotImplementedError

    def fetch_payment(self, *, payment_id: str | None = None, order_id: str | None = None) -> GatewayPaymentSnapshot | None:
        raise NotImplementedError

    def fetch_refund(self, *, refund_id: str) -> GatewayRefundSnapshot | None:
        raise NotImplementedError


class RazorpayPaymentGatewayClient(PaymentGatewayClient):
    def __init__(self) -> None:
        self.settings = get_settings()

    def _sign(self, order_id: str, payment_id: str) -> str:
        secret = self.settings.payment_gateway_key_secret.encode()
        payload = f"{order_id}|{payment_id}".encode()
        return hmac.new(secret, payload, hashlib.sha256).hexdigest()

    def verify_webhook_signature(self, body: bytes, signature: str) -> bool:
        expected = hmac.new(
            self.settings.payment_gateway_webhook_secret.encode(), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    @property
    def _live(self) -> bool:
        return self.settings.environment.lower() in {"production", "staging"}

    def _request(self, method: str, path: str, **kwargs):
        response = httpx.request(
            method,
            f"{self.settings.payment_gateway_api_url.rstrip('/')}{path}",
            auth=(self.settings.payment_gateway_key_id, self.settings.payment_gateway_key_secret),
            timeout=15.0,
            **kwargs,
        )
        response.raise_for_status()
        return response.json()

    def create_order(self, *, amount: int, currency: str, receipt: str) -> GatewayOrder:
        if self._live:
            data = self._request(
                "POST", "/v1/orders", json={"amount": amount, "currency": currency, "receipt": receipt}
            )
            return GatewayOrder(
                order_id=data["id"],
                amount=int(data["amount"]),
                currency=data["currency"],
                receipt=data["receipt"],
            )
        return GatewayOrder(
            order_id=f"order_{secrets.token_hex(12)}",
            amount=amount,
            currency=currency,
            receipt=receipt,
        )

    def verify_payment(
        self,
        *,
        order_id: str,
        payment_id: str,
        signature: str,
        expected_amount: int | None = None,
        expected_currency: str | None = None,
    ) -> bool:
        if not hmac.compare_digest(self._sign(order_id, payment_id), signature):
            return False
        if not self._live:
            return True
        data = self._request("GET", f"/v1/payments/{payment_id}")
        return (
            data.get("order_id") == order_id
            and data.get("status") == "captured"
            and (expected_amount is None or int(data.get("amount", -1)) == expected_amount)
            and (expected_currency is None or data.get("currency") == expected_currency)
        )

    def payment_signature(self, *, order_id: str, payment_id: str) -> str:
        return self._sign(order_id, payment_id)

    def initiate_refund(self, *, payment_id: str, amount: int) -> GatewayRefund:
        if self._live:
            data = self._request("POST", f"/v1/payments/{payment_id}/refund", json={"amount": amount})
            return GatewayRefund(
                refund_id=data["id"], payment_id=data["payment_id"], amount=int(data["amount"])
            )
        return GatewayRefund(
            refund_id=f"rfnd_{secrets.token_hex(12)}",
            payment_id=payment_id,
            amount=amount,
        )

    def fetch_payment(self, *, payment_id: str | None = None, order_id: str | None = None) -> GatewayPaymentSnapshot | None:
        if not self._live:
            return None
        if payment_id:
            data = self._request("GET", f"/v1/payments/{payment_id}")
        elif order_id:
            payments = self._request("GET", "/v1/payments", params={"order_id": order_id})
            items = payments.get("items", []) if isinstance(payments, dict) else []
            data = items[0] if items else None
        else:
            return None
        if not data:
            return None
        return GatewayPaymentSnapshot(
            payment_id=str(data["id"]),
            order_id=str(data.get("order_id") or order_id or ""),
            status=str(data.get("status", "unknown")),
            amount=int(data.get("amount", 0)),
            currency=str(data.get("currency", "")),
        )

    def fetch_refund(self, *, refund_id: str) -> GatewayRefundSnapshot | None:
        if not self._live:
            return None
        data = self._request("GET", f"/v1/refunds/{refund_id}")
        return GatewayRefundSnapshot(
            refund_id=str(data["id"]),
            payment_id=str(data["payment_id"]),
            status=str(data.get("status", "unknown")),
            amount=int(data.get("amount", 0)),
        )


def get_payment_gateway_client() -> PaymentGatewayClient:
    return RazorpayPaymentGatewayClient()
