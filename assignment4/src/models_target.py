from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, ForeignKey, Numeric
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class TargetBase(DeclarativeBase):
    pass

# Dimensions
class DimDate(TargetBase):
    __tablename__ = "dim_date"
    date_key: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    date: Mapped[date] = mapped_column(Date)
    year: Mapped[int]
    quarter: Mapped[int]
    month: Mapped[int]
    day_of_month: Mapped[int]
    day_of_week: Mapped[int]
    is_weekend: Mapped[int]

class DimFilm(TargetBase):
    __tablename__ = "dim_film"
    film_key: Mapped[int] = mapped_column(primary_key=True)
    film_id: Mapped[int] = mapped_column(unique=True, index=True)
    title: Mapped[str]
    rating: Mapped[Optional[str]]
    length: Mapped[Optional[int]]
    language: Mapped[str]
    release_year: Mapped[Optional[int]]
    last_update: Mapped[datetime]


class DimActor(TargetBase):
    __tablename__ = "dim_actor"
    actor_key: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int] = mapped_column(unique=True, index=True)
    first_name: Mapped[str]
    last_name: Mapped[str]
    last_update: Mapped[datetime]


class DimCategory(TargetBase):
    __tablename__ = "dim_category"
    category_key: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(unique=True, index=True)
    name: Mapped[str]
    last_update: Mapped[datetime]


class DimStore(TargetBase):
    __tablename__ = "dim_store"
    store_key: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(unique=True, index=True)
    city: Mapped[str]
    country: Mapped[str]
    last_update: Mapped[datetime]


class DimCustomer(TargetBase):
    __tablename__ = "dim_customer"
    customer_key: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(unique=True, index=True)
    first_name: Mapped[str]
    last_name: Mapped[str]
    active: Mapped[int]
    city: Mapped[str]
    country: Mapped[str]
    last_update: Mapped[datetime]

# Bridges
class BridgeFilmActor(TargetBase):
    __tablename__ = "bridge_film_actor"
    film_key: Mapped[int] = mapped_column(ForeignKey("dim_film.film_key"), primary_key = True)
    actor_key: Mapped[int] = mapped_column(ForeignKey("dim_actor.actor_key"),primary_key = True)

class BridgeFilmCategory(TargetBase):
    __tablename__ = "bridge_film_category"
    film_key: Mapped[int] = mapped_column(ForeignKey("dim_film.film_key"), primary_key=True)
    category_key: Mapped[int] = mapped_column(ForeignKey("dim_category.category_key"), primary_key=True)


# Facts
class FactRental(TargetBase):
    __tablename__ = "fact_rental"
    fact_rental_key: Mapped[int] = mapped_column(primary_key=True)
    rental_id: Mapped[int] = mapped_column(unique=True, index=True)
    date_key_rented: Mapped[int] = mapped_column(ForeignKey("dim_date.date_key"), index=True)
    date_key_returned: Mapped[Optional[int]] = mapped_column(ForeignKey("dim_date.date_key"), index=True)
    film_key: Mapped[int] = mapped_column(ForeignKey("dim_film.film_key"), index=True)
    store_key: Mapped[int] = mapped_column(ForeignKey("dim_store.store_key"), index=True)
    customer_key: Mapped[int] = mapped_column(ForeignKey("dim_customer.customer_key"), index=True)
    staff_id: Mapped[int]
    rental_duration_days: Mapped[Optional[int]]


class FactPayment(TargetBase):
    __tablename__ = "fact_payment"
    fact_payment_key: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(unique=True, index=True)
    date_key_paid: Mapped[int] = mapped_column(ForeignKey("dim_date.date_key"), index=True)
    customer_key: Mapped[int] = mapped_column(ForeignKey("dim_customer.customer_key"), index=True)
    store_key: Mapped[int] = mapped_column(ForeignKey("dim_store.store_key"), index=True)
    staff_id: Mapped[int]
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))


# sync
class SyncState(TargetBase):
    __tablename__ = "sync_state"
    table_name: Mapped[str] = mapped_column(primary_key=True)
    last_update: Mapped[datetime]