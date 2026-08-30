"""
Weight Provider Abstraction for Prima Bascol Weighbridge System.
Enables clean separation between weight input (manual, serial, TCP/IP, REST API) and business models.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
from enum import Enum

class WeightUnit(str, Enum):
    KG = "kg"
    TON = "ton"

class ConnectionStatus(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    MANUAL_ONLY = "manual_only"
    ERROR = "error"

@dataclass
class WeightResult:
    weight: Decimal
    unit: WeightUnit = WeightUnit.KG
    is_stable: bool = True
    provider_name: str = "Manual"
    raw_response: Optional[str] = None
    error_message: Optional[str] = None

class BaseWeightProvider(ABC):
    """
    Abstract interface for weight indicators and providers.
    In future phases, SerialWeightProvider, TcpIpWeightProvider, and ApiWeightProvider
    can implement this class without modifying weighbridge views or models.
    """
    @abstractmethod
    def get_weight(self, raw_input: Optional[any] = None) -> WeightResult:
        """Fetch or parse weight from the provider."""
        pass

    @abstractmethod
    def check_connection(self) -> ConnectionStatus:
        """Check connection health with weighing hardware/source."""
        pass

class ManualWeightProvider(BaseWeightProvider):
    """
    Standard provider for Phase 1: operator enters weight manually.
    Validates positive numbers and converts to Decimal.
    """
    def __init__(self, unit: WeightUnit = WeightUnit.KG):
        self.unit = unit

    def get_weight(self, raw_input: Optional[any] = None) -> WeightResult:
        if raw_input is None or str(raw_input).strip() == "":
            return WeightResult(
                weight=Decimal("0"),
                unit=self.unit,
                is_stable=True,
                provider_name="Manual",
                error_message="مقدار وزن وارد نشده است."
            )
        try:
            # Clean string, replace commas, remove non-numeric chars except dot
            clean_val = str(raw_input).replace(",", "").strip()
            # translate Persian digits if needed
            from core.jalali import to_english_digits
            clean_val = to_english_digits(clean_val)
            dec_weight = Decimal(clean_val)
            if dec_weight < 0:
                return WeightResult(
                    weight=Decimal("0"),
                    unit=self.unit,
                    is_stable=False,
                    provider_name="Manual",
                    error_message="وزن نمی‌تواند منفی باشد."
                )
            return WeightResult(
                weight=dec_weight,
                unit=self.unit,
                is_stable=True,
                provider_name="Manual"
            )
        except Exception as e:
            return WeightResult(
                weight=Decimal("0"),
                unit=self.unit,
                is_stable=False,
                provider_name="Manual",
                error_message=f"خطا در خواندن وزن: {str(e)}"
            )

    def check_connection(self) -> ConnectionStatus:
        return ConnectionStatus.MANUAL_ONLY

def get_active_weight_provider() -> BaseWeightProvider:
    """
    Factory function to return the configured weight provider.
    Defaults to ManualWeightProvider in Phase 1.
    """
    return ManualWeightProvider()
