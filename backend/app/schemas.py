from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field


# ===== Registration (multi-step) =====
class RegisterStep1(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)


class RegisterStep2(BaseModel):
    email: EmailStr
    phone: str = Field(..., min_length=8, max_length=30)


class RegisterStep3(BaseModel):
    monthly_salary: float = Field(..., gt=0)


class RegisterVerify(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=4, max_length=10)


class LoginRequest(BaseModel):
    email: EmailStr
    # For OTP login after registration, or password if set
    code: Optional[str] = None
    password: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class UserOut(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: str
    phone: str
    monthly_salary: float
    is_verified: bool
    is_admin: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class ProfileUpdate(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    phone: str = Field(..., min_length=8, max_length=30)
    monthly_salary: float = Field(..., gt=0)


# ===== Cart =====
class CartItemIn(BaseModel):
    vehicle_id: int
    brand: str
    model: str
    year: int
    price: float
    monthly: float = 0
    image: str = ""


class CartItemOut(BaseModel):
    id: int
    vehicle_id: int
    brand: str
    model: str
    year: int
    price: float
    monthly: float
    image: str
    added_at: datetime

    class Config:
        from_attributes = True


class CartOut(BaseModel):
    items: List[CartItemOut]
    total: float
    count: int


# ===== Orders / Financing =====
class CheckoutIn(BaseModel):
    cart_item_id: int
    payment_type: str = Field(..., pattern="^(full|monthly)$")
    months: Optional[int] = Field(None, ge=3, le=84)  # for monthly


class InstallmentOut(BaseModel):
    id: int
    number: int
    amount: float
    due_date: datetime
    paid: bool
    paid_at: Optional[datetime]
    payment_status: str = "unpaid"
    claimed_at: Optional[datetime] = None
    admin_note: str = ""

    class Config:
        from_attributes = True


class DeliveryEventOut(BaseModel):
    id: int
    status: str
    location: str
    message: str
    created_at: datetime

    class Config:
        from_attributes = True


class DeliveryOut(BaseModel):
    id: int
    status: str
    tracking_number: str
    carrier: str
    estimated_delivery: Optional[datetime]
    current_location: str
    notes: str
    recipient_first_name: str = ""
    recipient_last_name: str = ""
    recipient_phone: str = ""
    delivery_address: str = ""
    events: List[DeliveryEventOut] = []

    class Config:
        from_attributes = True


class OrderOut(BaseModel):
    id: int
    vehicle_id: int
    brand: str
    model: str
    year: int
    image: str
    total_price: float
    payment_type: str
    monthly_amount: float
    months_total: int
    amount_paid: float
    status: str
    created_at: datetime
    paid_at: Optional[datetime]
    installments: List[InstallmentOut] = []
    delivery: Optional[DeliveryOut] = None

    class Config:
        from_attributes = True


class PayInstallmentIn(BaseModel):
    installment_id: int


class DeliveryDetailsIn(BaseModel):
    recipient_first_name: str = Field(..., min_length=1, max_length=100)
    recipient_last_name: str = Field(..., min_length=1, max_length=100)
    recipient_phone: str = Field(..., min_length=8, max_length=30)
    delivery_address: str = Field(..., min_length=5, max_length=1000)
