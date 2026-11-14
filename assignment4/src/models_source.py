from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class SourceBase(DeclarativeBase):
    pass


class Country(SourceBase):
    __tablename__ = "country"
    country_id: Mapped[int] = mapped_column(primary_key=True)
    country: Mapped[str]
    last_update: Mapped[datetime]


class City(SourceBase):
    __tablename__ = "city"
    city_id: Mapped[int] = mapped_column(primary_key=True)
    city: Mapped[str]
    country_id: Mapped[int] = mapped_column(ForeignKey("country.country_id"))
    last_update: Mapped[datetime]
    country: Mapped[Country] = relationship()


class Address(SourceBase):
    __tablename__ = "address"
    address_id: Mapped[int] = mapped_column(primary_key=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("city.city_id"))
    last_update: Mapped[datetime]
    city: Mapped[City] = relationship()


# --- 影片相关 ---
class Language(SourceBase):
    __tablename__ = "language"
    language_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    last_update: Mapped[datetime]


class Film(SourceBase):
    __tablename__ = "film"
    film_id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    release_year: Mapped[Optional[int]]
    language_id: Mapped[int] = mapped_column(ForeignKey("language.language_id"))
    length: Mapped[Optional[int]]
    rating: Mapped[Optional[str]]
    last_update: Mapped[datetime]
    language: Mapped[Language] = relationship()


class Actor(SourceBase):
    __tablename__ = "actor"
    actor_id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str]
    last_name: Mapped[str]
    last_update: Mapped[datetime]


class Category(SourceBase):
    __tablename__ = "category"
    category_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    last_update: Mapped[datetime]


class FilmActor(SourceBase):
    __tablename__ = "film_actor"
    actor_id: Mapped[int] = mapped_column(ForeignKey("actor.actor_id"), primary_key=True)
    film_id: Mapped[int] = mapped_column(ForeignKey("film.film_id"), primary_key=True)
    last_update: Mapped[datetime]


class FilmCategory(SourceBase):
    __tablename__ = "film_category"
    film_id: Mapped[int] = mapped_column(ForeignKey("film.film_id"), primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("category.category_id"), primary_key=True)
    last_update: Mapped[datetime]


class Store(SourceBase):
    __tablename__ = "store"
    store_id: Mapped[int] = mapped_column(primary_key=True)
    address_id: Mapped[int] = mapped_column(ForeignKey("address.address_id"))
    last_update: Mapped[datetime]
    address: Mapped[Address] = relationship()


class Staff(SourceBase):
    __tablename__ = "staff"
    staff_id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("store.store_id"))
    last_update: Mapped[datetime]
    store: Mapped[Store] = relationship()


class Inventory(SourceBase):
    __tablename__ = "inventory"
    inventory_id: Mapped[int] = mapped_column(primary_key=True)
    film_id: Mapped[int] = mapped_column(ForeignKey("film.film_id"))
    store_id: Mapped[int] = mapped_column(ForeignKey("store.store_id"))
    last_update: Mapped[datetime]


class Customer(SourceBase):
    __tablename__ = "customer"
    customer_id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str]
    last_name: Mapped[str]
    address_id: Mapped[int] = mapped_column(ForeignKey("address.address_id"))
    active: Mapped[int]
    last_update: Mapped[datetime]
    address: Mapped[Address] = relationship()


class Rental(SourceBase):
    __tablename__ = "rental"
    rental_id: Mapped[int] = mapped_column(primary_key=True)
    rental_date: Mapped[datetime]
    inventory_id: Mapped[int] = mapped_column(ForeignKey("inventory.inventory_id"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customer.customer_id"))
    return_date: Mapped[Optional[datetime]]
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff.staff_id"))
    last_update: Mapped[datetime]
    inventory: Mapped[Inventory] = relationship()


class Payment(SourceBase):
    __tablename__ = "payment"
    payment_id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customer.customer_id"))
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff.staff_id"))
    rental_id: Mapped[Optional[int]] = mapped_column(ForeignKey("rental.rental_id"))
    amount: Mapped[Decimal]
    payment_date: Mapped[datetime]
    last_update: Mapped[datetime]
    rental: Mapped[Optional[Rental]] = relationship()
    staff: Mapped[Staff] = relationship()