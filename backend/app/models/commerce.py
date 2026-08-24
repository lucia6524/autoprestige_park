from datetime import datetime
from sqlalchemy import String, Integer, Float, Boolean, DateTime, Text, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.time_utils import utc_now_naive
import enum

class PaymentType(str, enum.Enum):
    FULL = "full"           # paiement comptant
    MONTHLY = "monthly"     # paiement mensuel

class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"           # échéancier en cours
    PAID = "paid"               # soldé
    DELIVERING = "delivering"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"

class DeliveryStatus(str, enum.Enum):
    PREPARING = "preparing"
    SHIPPED = "shipped"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"

# unpaid = à payer | claimed = client a déclaré le virement | paid = validé admin | rejected = refusé
class InstallmentPaymentStatus(str, enum.Enum):
    UNPAID = "unpaid"
    CLAIMED = "claimed"
    PAID = "paid"
    REJECTED = "rejected"

class VehicleCategory(str, enum.Enum):
    VOITURE = "voiture"
    CAMPING_CAR = "camping-car"
    MACHINE_AGRICOLE = "machine-agricole"


class Vehicle(Base):
    """Catalogue véhicules géré depuis le dashboard admin."""
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    category: Mapped[str] = mapped_column(String(30), default=VehicleCategory.VOITURE.value, index=True)
    brand: Mapped[str] = mapped_column(String(100))
    model: Mapped[str] = mapped_column(String(150))
    year: Mapped[int] = mapped_column(Integer, default=2024)
    fuel: Mapped[str] = mapped_column(String(50), default="")
    transmission: Mapped[str] = mapped_column(String(50), default="")
    mileage: Mapped[int] = mapped_column(Integer, default=0)
    price: Mapped[float] = mapped_column(Float, default=0)
    monthly: Mapped[float] = mapped_column(Float, default=0)
    type: Mapped[str] = mapped_column(String(30), default="occasion")  # neuf | occasion
    body_category: Mapped[str] = mapped_column(String(50), default="")  # Berline, SUV...
    power: Mapped[int] = mapped_column(Integer, default=0)
    featured: Mapped[bool] = mapped_column(Boolean, default=False)
    promo: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    image: Mapped[str] = mapped_column(String(500), default="")
    images: Mapped[str] = mapped_column(Text, default="")  # JSON array as string
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)


class CartItem(Base):
    __tablename__ = "cart_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    vehicle_id: Mapped[int] = mapped_column(Integer)  # id from catalog
    brand: Mapped[str] = mapped_column(String(100))
    model: Mapped[str] = mapped_column(String(150))
    year: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)
    monthly: Mapped[float] = mapped_column(Float, default=0)
    image: Mapped[str] = mapped_column(String(500), default="")
    added_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)

    user = relationship("User", back_populates="carts")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    vehicle_id: Mapped[int] = mapped_column(Integer)
    brand: Mapped[str] = mapped_column(String(100))
    model: Mapped[str] = mapped_column(String(150))
    year: Mapped[int] = mapped_column(Integer)
    image: Mapped[str] = mapped_column(String(500), default="")

    total_price: Mapped[float] = mapped_column(Float)
    payment_type: Mapped[str] = mapped_column(String(20))  # full | monthly
    monthly_amount: Mapped[float] = mapped_column(Float, default=0)
    months_total: Mapped[int] = mapped_column(Integer, default=0)
    amount_paid: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(30), default=OrderStatus.PENDING.value)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user = relationship("User", back_populates="orders")
    installments = relationship("Installment", back_populates="order", cascade="all, delete-orphan")
    delivery = relationship("Delivery", back_populates="order", uselist=False, cascade="all, delete-orphan")


class Installment(Base):
    __tablename__ = "installments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    number: Mapped[int] = mapped_column(Integer)  # 1, 2, 3...
    amount: Mapped[float] = mapped_column(Float)
    due_date: Mapped[datetime] = mapped_column(DateTime)
    paid: Mapped[bool] = mapped_column(Boolean, default=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # unpaid | claimed | paid | rejected
    payment_status: Mapped[str] = mapped_column(String(20), default=InstallmentPaymentStatus.UNPAID.value)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    admin_note: Mapped[str] = mapped_column(Text, default="")

    order = relationship("Order", back_populates="installments")


class Delivery(Base):
    __tablename__ = "deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), unique=True)
    status: Mapped[str] = mapped_column(String(30), default=DeliveryStatus.PREPARING.value)
    tracking_number: Mapped[str] = mapped_column(String(100), default="")
    carrier: Mapped[str] = mapped_column(String(100), default="AutoPrestige Logistics")
    estimated_delivery: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    current_location: Mapped[str] = mapped_column(String(255), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    recipient_first_name: Mapped[str] = mapped_column(String(100), default="")
    recipient_last_name: Mapped[str] = mapped_column(String(100), default="")
    recipient_phone: Mapped[str] = mapped_column(String(30), default="")
    delivery_address: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)

    order = relationship("Order", back_populates="delivery")
    events = relationship("DeliveryEvent", back_populates="delivery", cascade="all, delete-orphan", order_by="DeliveryEvent.created_at")


class DeliveryEvent(Base):
    __tablename__ = "delivery_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    delivery_id: Mapped[int] = mapped_column(ForeignKey("deliveries.id"))
    status: Mapped[str] = mapped_column(String(30))
    location: Mapped[str] = mapped_column(String(255), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)

    delivery = relationship("Delivery", back_populates="events")


class Notification(Base):
    """Notifications admin (ex: client a déclaré un paiement d'échéance)."""
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(50), default="payment_claim")
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text, default="")
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    installment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
