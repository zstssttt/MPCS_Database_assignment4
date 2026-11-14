import logging
from datetime import date, datetime, timedelta

from sqlalchemy import delete, func, select

from src.config import SourceSession, TargetSession, target_engine
from src.models_source import (
    Actor, Address, Category, City, Country, Customer, Film, FilmActor,
    FilmCategory, Inventory, Language, Payment, Rental, Staff, Store,
)
from src.models_target import (
    BridgeFilmActor, BridgeFilmCategory, DimActor, DimCategory, DimCustomer,
    DimDate, DimFilm, DimStore, FactPayment, FactRental, SyncState, TargetBase,
)

log = logging.getLogger("sync")

# All source tables we track for change detection (used by sync_state).
SOURCE_TABLES = [
    "film", "actor", "category", "language", "store", "staff",
    "inventory", "customer", "address", "city", "country",
    "film_actor", "film_category", "rental", "payment",
]
EPOCH = datetime(1970, 1, 1)


# ---------- helpers ----------
def to_date_key(dt) -> int:
    """datetime/date -> YYYYMMDD integer, e.g. 2005-07-06 -> 20050706."""
    return dt.year * 10000 + dt.month * 100 + dt.day


def _date_range(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def ensure_date_keys(session, dates) -> None:
    """Insert a dim_date row for each date not already present (idempotent)."""
    existing = set(session.scalars(select(DimDate.date_key)).all())
    for d in dates:
        dk = to_date_key(d)
        if dk in existing:
            continue
        dow = d.isoweekday()  # Monday=1 ... Sunday=7
        session.add(DimDate(
            date_key=dk, date=d, year=d.year,
            quarter=(d.month - 1) // 3 + 1, month=d.month,
            day_of_month=d.day, day_of_week=dow,
            is_weekend=1 if dow >= 6 else 0,
        ))
        existing.add(dk)


def _max_last_update(rows) -> datetime:
    """Latest last_update among rows, or EPOCH if empty."""
    return max((r.last_update for r in rows), default=EPOCH)


def _set_markers(session, markers: dict) -> None:
    """Write the latest processed last_update per source table into sync_state."""
    rows = {s.table_name: s for s in session.scalars(select(SyncState)).all()}
    for name, marker in markers.items():
        if name in rows:
            rows[name].last_update = marker
        else:
            session.add(SyncState(table_name=name, last_update=marker))


# ---------- init ----------
def init() -> None:
    # 1. verify MySQL is reachable (raises if not)
    with SourceSession() as s:
        s.scalar(select(func.count()).select_from(Film))

    # 2. create all analytics tables from the ORM models
    TargetBase.metadata.create_all(target_engine)

    # 3. seed dim_date and sync_state inside one transaction
    with TargetSession() as t, t.begin():
        ensure_date_keys(t, _date_range(date(2005, 1, 1), date(2006, 12, 31)))
        existing = set(t.scalars(select(SyncState.table_name)).all())
        for name in SOURCE_TABLES:
            if name not in existing:
                t.add(SyncState(table_name=name, last_update=EPOCH))


# ---------- full load ----------
def full_load() -> None:
    # 1) READ everything from the source (MySQL), build lookup dicts
    with SourceSession() as src:
        films = src.scalars(select(Film)).all()
        actors = src.scalars(select(Actor)).all()
        categories = src.scalars(select(Category)).all()
        languages = src.scalars(select(Language)).all()
        stores = src.scalars(select(Store)).all()
        staff = src.scalars(select(Staff)).all()
        inventories = src.scalars(select(Inventory)).all()
        customers = src.scalars(select(Customer)).all()
        addresses = src.scalars(select(Address)).all()
        cities = src.scalars(select(City)).all()
        countries = src.scalars(select(Country)).all()
        film_actors = src.scalars(select(FilmActor)).all()
        film_categories = src.scalars(select(FilmCategory)).all()
        rentals = src.scalars(select(Rental)).all()
        payments = src.scalars(select(Payment)).all()

        # lookup dicts (avoid per-row lazy queries / N+1)
        lang_name = {l.language_id: l.name for l in languages}
        country_name = {c.country_id: c.country for c in countries}
        city_info = {c.city_id: (c.city, c.country_id) for c in cities}
        addr_city = {a.address_id: a.city_id for a in addresses}
        inv_info = {i.inventory_id: (i.film_id, i.store_id) for i in inventories}
        staff_store = {s.staff_id: s.store_id for s in staff}

    def geo(address_id):
        """address_id -> (city_name, country_name)."""
        city_name, country_id = city_info[addr_city[address_id]]
        return city_name, country_name[country_id]

    # 2) WRITE everything to the target (SQLite) in ONE transaction
    with TargetSession() as t, t.begin():
        # clear fact/bridge/dim tables (keep dim_date & sync_state) -> rerunnable, no dupes
        for model in (FactPayment, FactRental, BridgeFilmActor, BridgeFilmCategory,
                      DimFilm, DimActor, DimCategory, DimStore, DimCustomer):
            t.execute(delete(model))

        # --- dimensions ---
        dim_films = [DimFilm(
            film_id=f.film_id, title=f.title, rating=f.rating, length=f.length,
            language=lang_name[f.language_id], release_year=f.release_year,
            last_update=f.last_update,
        ) for f in films]

        dim_actors = [DimActor(
            actor_id=a.actor_id, first_name=a.first_name, last_name=a.last_name,
            last_update=a.last_update,
        ) for a in actors]

        dim_categories = [DimCategory(
            category_id=c.category_id, name=c.name, last_update=c.last_update,
        ) for c in categories]

        dim_stores = []
        for s in stores:
            city, country = geo(s.address_id)
            dim_stores.append(DimStore(
                store_id=s.store_id, city=city, country=country, last_update=s.last_update,
            ))

        dim_customers = []
        for c in customers:
            city, country = geo(c.address_id)
            dim_customers.append(DimCustomer(
                customer_id=c.customer_id, first_name=c.first_name, last_name=c.last_name,
                active=c.active, city=city, country=country, last_update=c.last_update,
            ))

        t.add_all(dim_films + dim_actors + dim_categories + dim_stores + dim_customers)
        t.flush()  # <-- assigns the surrogate *_key values

        # natural key -> surrogate key maps
        film_key = {d.film_id: d.film_key for d in dim_films}
        actor_key = {d.actor_id: d.actor_key for d in dim_actors}
        category_key = {d.category_id: d.category_key for d in dim_categories}
        store_key = {d.store_id: d.store_key for d in dim_stores}
        customer_key = {d.customer_id: d.customer_key for d in dim_customers}

        # --- bridges ---
        t.add_all([BridgeFilmActor(film_key=film_key[fa.film_id], actor_key=actor_key[fa.actor_id])
                   for fa in film_actors])
        t.add_all([BridgeFilmCategory(film_key=film_key[fc.film_id], category_key=category_key[fc.category_id])
                   for fc in film_categories])

        # --- ensure every date used by facts exists in dim_date ---
        used_dates = set()
        for r in rentals:
            used_dates.add(r.rental_date.date())
            if r.return_date:
                used_dates.add(r.return_date.date())
        for p in payments:
            used_dates.add(p.payment_date.date())
        ensure_date_keys(t, used_dates)

        # --- facts ---
        rental_store = {}  
        fact_rentals = []
        for r in rentals:
            f_id, s_id = inv_info[r.inventory_id]
            rental_store[r.rental_id] = s_id
            returned = r.return_date is not None
            fact_rentals.append(FactRental(
                rental_id=r.rental_id,
                date_key_rented=to_date_key(r.rental_date),
                date_key_returned=to_date_key(r.return_date) if returned else None,
                film_key=film_key[f_id],
                store_key=store_key[s_id],
                customer_key=customer_key[r.customer_id],
                staff_id=r.staff_id,
                rental_duration_days=(r.return_date.date() - r.rental_date.date()).days if returned else None,
            ))

        fact_payments = []
        for p in payments:
            if p.rental_id is not None and p.rental_id in rental_store:
                s_id = rental_store[p.rental_id]          # store via rental's inventory
            else:
                s_id = staff_store[p.staff_id]            # fallback: staff's store
            fact_payments.append(FactPayment(
                payment_id=p.payment_id,
                date_key_paid=to_date_key(p.payment_date),
                customer_key=customer_key[p.customer_id],
                store_key=store_key[s_id],
                staff_id=p.staff_id,
                amount=p.amount,
            ))

        t.add_all(fact_rentals + fact_payments)

        # --- record starting markers in sync_state ---
        _set_markers(t, {
            "film": _max_last_update(films), "actor": _max_last_update(actors),
            "category": _max_last_update(categories), "language": _max_last_update(languages),
            "store": _max_last_update(stores), "staff": _max_last_update(staff),
            "inventory": _max_last_update(inventories), "customer": _max_last_update(customers),
            "address": _max_last_update(addresses), "city": _max_last_update(cities),
            "country": _max_last_update(countries), "film_actor": _max_last_update(film_actors),
            "film_category": _max_last_update(film_categories), "rental": _max_last_update(rentals),
            "payment": _max_last_update(payments),
        })

    log.info(
        "full-load done: %d films, %d actors, %d customers, %d rentals, %d payments",
        len(dim_films), len(dim_actors), len(dim_customers), len(fact_rentals), len(fact_payments),
    )

# incremental 
def _get_markers(session) -> dict:
    """Read the last processed last_update per source table from sync_state."""
    return {s.table_name: s.last_update for s in session.scalars(select(SyncState)).all()}


def _upsert(session, model, natural_key_col, natural_key_val, values: dict):
    """Update the row with this natural key if it exists, else insert a new one."""
    obj = session.scalar(select(model).where(natural_key_col == natural_key_val))
    if obj is None:
        session.add(model(**{natural_key_col.key: natural_key_val}, **values))
    else:
        for k, v in values.items():
            setattr(obj, k, v)


def incremental() -> None:
    markers = {}
    with TargetSession() as t, t.begin():
        markers = _get_markers(t)

    with SourceSession() as src:
        def changed(model, table):
            """Source rows at or after the stored marker.

            ``>=`` rather than ``>`` so an edit landing in the same second as the
            marker is never skipped (MySQL TIMESTAMP has one-second resolution).
            Boundary rows are therefore re-read on every run; every write is an
            upsert, so reprocessing them is harmless.
            """
            marker = markers.get(table, EPOCH)
            return src.scalars(select(model).where(model.last_update >= marker)).all()

        # changed rows per source table
        films_raw = changed(Film, "film")
        actors = changed(Actor, "actor")
        categories = changed(Category, "category")
        stores_raw = changed(Store, "store")
        customers_raw = changed(Customer, "customer")
        film_actors = changed(FilmActor, "film_actor")
        film_categories = changed(FilmCategory, "film_category")
        rentals_raw = changed(Rental, "rental")
        payments_raw = changed(Payment, "payment")

        # related tables (their changes must propagate to dim_customer / dim_store)
        addresses = changed(Address, "address")
        cities = changed(City, "city")
        countries = changed(Country, "country")
        languages = changed(Language, "language")
        inventories = changed(Inventory, "inventory")
        staff = changed(Staff, "staff")

        # full lookup dicts (read ALL, not just changed, so we can always resolve)
        lang_name = {l.language_id: l.name for l in src.scalars(select(Language)).all()}
        country_name = {c.country_id: c.country for c in src.scalars(select(Country)).all()}
        city_info = {c.city_id: (c.city, c.country_id) for c in src.scalars(select(City)).all()}
        addr_city = {a.address_id: a.city_id for a in src.scalars(select(Address)).all()}
        inv_info = {i.inventory_id: (i.film_id, i.store_id) for i in src.scalars(select(Inventory)).all()}
        staff_store = {s.staff_id: s.store_id for s in src.scalars(select(Staff)).all()}

        # --- propagation: find customers/stores affected by related-table changes ---
        changed_city_ids = {c.city_id for c in cities}
        changed_city_ids |= {co_city for co in countries
                             for co_city in [cid for cid, (_, coid) in city_info.items() if coid == co.country_id]}
        changed_address_ids = {a.address_id for a in addresses}
        changed_address_ids |= {aid for aid, cid in addr_city.items() if cid in changed_city_ids}

        if changed_address_ids:
            extra_customers = src.scalars(
                select(Customer).where(Customer.address_id.in_(changed_address_ids))).all()
            extra_stores = src.scalars(
                select(Store).where(Store.address_id.in_(changed_address_ids))).all()
        else:
            extra_customers, extra_stores = [], []

        # dim_film stores the language name, so a renamed language must refresh its films
        changed_language_ids = {l.language_id for l in languages}
        extra_films = src.scalars(select(Film).where(
            Film.language_id.in_(changed_language_ids))).all() if changed_language_ids else []

        # inventory carries film_id/store_id, so moving a copy rewrites fact_rental's keys
        changed_inventory_ids = {i.inventory_id for i in inventories}
        extra_rentals = src.scalars(select(Rental).where(
            Rental.inventory_id.in_(changed_inventory_ids))).all() if changed_inventory_ids else []

        # payments with no rental fall back to the staff member's store
        changed_staff_ids = {s.staff_id for s in staff}
        extra_payments = src.scalars(select(Payment).where(
            Payment.staff_id.in_(changed_staff_ids),
            Payment.rental_id.is_(None))).all() if changed_staff_ids else []

        # merge (dedupe by id) changed + propagated
        customers = list({c.customer_id: c for c in (customers_raw + extra_customers)}.values())
        stores = list({s.store_id: s for s in (stores_raw + extra_stores)}.values())
        films = list({f.film_id: f for f in (films_raw + extra_films)}.values())
        rentals = list({r.rental_id: r for r in (rentals_raw + extra_rentals)}.values())
        payments = list({p.payment_id: p for p in (payments_raw + extra_payments)}.values())

    def geo(address_id):
        city_name, country_id = city_info[addr_city[address_id]]
        return city_name, country_name[country_id]

    # ---- WRITE to SQLite in ONE transaction ----
    with TargetSession() as t, t.begin():
        # dimensions (Type 1 overwrite via upsert)
        for f in films:
            _upsert(t, DimFilm, DimFilm.film_id, f.film_id, dict(
                title=f.title, rating=f.rating, length=f.length,
                language=lang_name[f.language_id], release_year=f.release_year,
                last_update=f.last_update))
        for a in actors:
            _upsert(t, DimActor, DimActor.actor_id, a.actor_id, dict(
                first_name=a.first_name, last_name=a.last_name, last_update=a.last_update))
        for c in categories:
            _upsert(t, DimCategory, DimCategory.category_id, c.category_id, dict(
                name=c.name, last_update=c.last_update))
        for s in stores:
            city, country = geo(s.address_id)
            _upsert(t, DimStore, DimStore.store_id, s.store_id, dict(
                city=city, country=country, last_update=s.last_update))
        for c in customers:
            city, country = geo(c.address_id)
            _upsert(t, DimCustomer, DimCustomer.customer_id, c.customer_id, dict(
                first_name=c.first_name, last_name=c.last_name, active=c.active,
                city=city, country=country, last_update=c.last_update))
        t.flush()

        # natural key -> surrogate key maps (query current state of all dims)
        film_key = {d.film_id: d.film_key for d in t.scalars(select(DimFilm)).all()}
        actor_key = {d.actor_id: d.actor_key for d in t.scalars(select(DimActor)).all()}
        category_key = {d.category_id: d.category_key for d in t.scalars(select(DimCategory)).all()}
        store_key = {d.store_id: d.store_key for d in t.scalars(select(DimStore)).all()}
        customer_key = {d.customer_id: d.customer_key for d in t.scalars(select(DimCustomer)).all()}

        # bridges (upsert by composite key)
        for fa in film_actors:
            fk, ak = film_key[fa.film_id], actor_key[fa.actor_id]
            if t.scalar(select(BridgeFilmActor).where(
                    BridgeFilmActor.film_key == fk, BridgeFilmActor.actor_key == ak)) is None:
                t.add(BridgeFilmActor(film_key=fk, actor_key=ak))
        for fc in film_categories:
            fk, ck = film_key[fc.film_id], category_key[fc.category_id]
            if t.scalar(select(BridgeFilmCategory).where(
                    BridgeFilmCategory.film_key == fk, BridgeFilmCategory.category_key == ck)) is None:
                t.add(BridgeFilmCategory(film_key=fk, category_key=ck))

        # ensure dim_date covers any new dates
        used_dates = set()
        for r in rentals:
            used_dates.add(r.rental_date.date())
            if r.return_date:
                used_dates.add(r.return_date.date())
        for p in payments:
            used_dates.add(p.payment_date.date())
        ensure_date_keys(t, used_dates)

        # facts (upsert by natural key)
        rental_store = {}
        for r in rentals:
            f_id, s_id = inv_info[r.inventory_id]
            rental_store[r.rental_id] = s_id
            returned = r.return_date is not None
            _upsert(t, FactRental, FactRental.rental_id, r.rental_id, dict(
                date_key_rented=to_date_key(r.rental_date),
                date_key_returned=to_date_key(r.return_date) if returned else None,
                film_key=film_key[f_id], store_key=store_key[s_id],
                customer_key=customer_key[r.customer_id], staff_id=r.staff_id,
                rental_duration_days=(r.return_date.date() - r.rental_date.date()).days if returned else None))

        for p in payments:
            if p.rental_id is not None and p.rental_id in rental_store:
                sk = store_key[rental_store[p.rental_id]]
            else:
                # rental loaded by an earlier run, so read its store straight off the fact row
                sk = t.scalar(select(FactRental.store_key).where(
                    FactRental.rental_id == p.rental_id)) if p.rental_id is not None else None
                if sk is None:
                    sk = store_key[staff_store[p.staff_id]]
            _upsert(t, FactPayment, FactPayment.payment_id, p.payment_id, dict(
                date_key_paid=to_date_key(p.payment_date),
                customer_key=customer_key[p.customer_id], store_key=sk,
                staff_id=p.staff_id, amount=p.amount))

        # advance markers (max of changed rows, but never below the old marker)
        def new_marker(rows, table):
            return max([r.last_update for r in rows] + [markers.get(table, EPOCH)])
        _set_markers(t, {
            "film": new_marker(films_raw, "film"), "actor": new_marker(actors, "actor"),
            "category": new_marker(categories, "category"), "language": new_marker(languages, "language"),
            "store": new_marker(stores_raw, "store"), "staff": new_marker(staff, "staff"),
            "inventory": new_marker(inventories, "inventory"), "customer": new_marker(customers_raw, "customer"),
            "address": new_marker(addresses, "address"), "city": new_marker(cities, "city"),
            "country": new_marker(countries, "country"), "film_actor": new_marker(film_actors, "film_actor"),
            "film_category": new_marker(film_categories, "film_category"),
            "rental": new_marker(rentals_raw, "rental"), "payment": new_marker(payments_raw, "payment"),
        })

    log.info("incremental done: %d films, %d customers, %d stores, %d rentals, %d payments updated/inserted",
             len(films), len(customers), len(stores), len(rentals), len(payments))

# validate
def _latest_payment_date(src) -> date:
    """Latest payment_date in the source (Sakila ends ~2006-02), as a date."""
    dt = src.scalar(select(func.max(Payment.payment_date)))
    return dt.date() if dt else date(2006, 2, 14)


def validate(date_from: str | None = None, date_to: str | None = None) -> None:
    errors = []

    # 1) resolve the validation window
    with SourceSession() as src:
        if date_to:
            end = date.fromisoformat(date_to)
        else:
            end = _latest_payment_date(src)
        start = date.fromisoformat(date_from) if date_from else end - timedelta(days=30)

        start_key, end_key = to_date_key(start), to_date_key(end)
        log.info("Validation window: %s .. %s", start, end)

        # source totals within the window (ORM aggregates, not raw SQL)
        src_rentals = src.scalar(
            select(func.count()).select_from(Rental)
            .where(func.date(Rental.rental_date) >= start, func.date(Rental.rental_date) <= end)) or 0
        src_payments = src.scalar(
            select(func.count()).select_from(Payment)
            .where(func.date(Payment.payment_date) >= start, func.date(Payment.payment_date) <= end)) or 0
        src_amount = src.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0))
            .where(func.date(Payment.payment_date) >= start, func.date(Payment.payment_date) <= end)) or 0

        # per-store payment totals (store resolved the same way the ETL does it:
        # payment -> rental -> inventory -> store, falling back to the staff's store)
        store_expr = func.coalesce(Inventory.store_id, Staff.store_id)
        src_by_store = {
            row[0]: (row[1], float(row[2]))
            for row in src.execute(
                select(store_expr, func.count(), func.coalesce(func.sum(Payment.amount), 0))
                .select_from(Payment)
                .outerjoin(Rental, Payment.rental_id == Rental.rental_id)
                .outerjoin(Inventory, Rental.inventory_id == Inventory.inventory_id)
                .join(Staff, Payment.staff_id == Staff.staff_id)
                .where(func.date(Payment.payment_date) >= start, func.date(Payment.payment_date) <= end)
                .group_by(store_expr)).all()
        }

    # 2) target totals within the window
    with TargetSession() as t:
        tgt_rentals = t.scalar(
            select(func.count()).select_from(FactRental)
            .where(FactRental.date_key_rented >= start_key, FactRental.date_key_rented <= end_key)) or 0
        tgt_payments = t.scalar(
            select(func.count()).select_from(FactPayment)
            .where(FactPayment.date_key_paid >= start_key, FactPayment.date_key_paid <= end_key)) or 0
        tgt_amount = t.scalar(
            select(func.coalesce(func.sum(FactPayment.amount), 0))
            .where(FactPayment.date_key_paid >= start_key, FactPayment.date_key_paid <= end_key)) or 0

        # 3) count checks
        if src_rentals != tgt_rentals:
            errors.append(f"Rental count mismatch: source={src_rentals} target={tgt_rentals}")
        if src_payments != tgt_payments:
            errors.append(f"Payment count mismatch: source={src_payments} target={tgt_payments}")

        # 4) amount check (tolerance $0.01)
        if abs(float(src_amount) - float(tgt_amount)) > 0.01:
            errors.append(f"Payment amount mismatch: source={src_amount} target={tgt_amount}")

        # 4b) per-store checks: count exact, amount within $0.01 (catches mis-attributed stores)
        tgt_by_store = {
            row[0]: (row[1], float(row[2]))
            for row in t.execute(
                select(DimStore.store_id, func.count(), func.coalesce(func.sum(FactPayment.amount), 0))
                .select_from(FactPayment)
                .join(DimStore, FactPayment.store_key == DimStore.store_key)
                .where(FactPayment.date_key_paid >= start_key, FactPayment.date_key_paid <= end_key)
                .group_by(DimStore.store_id)).all()
        }
        for store_id in sorted(set(src_by_store) | set(tgt_by_store)):
            s_cnt, s_amt = src_by_store.get(store_id, (0, 0.0))
            t_cnt, t_amt = tgt_by_store.get(store_id, (0, 0.0))
            if s_cnt != t_cnt:
                errors.append(f"Store {store_id} payment count mismatch: source={s_cnt} target={t_cnt}")
            if abs(s_amt - t_amt) > 0.01:
                errors.append(f"Store {store_id} payment amount mismatch: source={s_amt:.2f} target={t_amt:.2f}")

        # 5) duplicate natural keys in target
        for model, key in ((FactRental, FactRental.rental_id), (FactPayment, FactPayment.payment_id),
                           (DimFilm, DimFilm.film_id), (DimCustomer, DimCustomer.customer_id)):
            dupes = t.scalar(
                select(func.count()).select_from(
                    select(key).group_by(key).having(func.count() > 1).subquery()))
            if dupes:
                errors.append(f"Duplicate natural keys in {model.__tablename__}: {dupes}")

        # 6) orphan facts (fact rows whose dimension key is missing)
        orphan_checks = [
            ("fact_rental.film_key", FactRental.film_key, DimFilm.film_key),
            ("fact_rental.customer_key", FactRental.customer_key, DimCustomer.customer_key),
            ("fact_rental.store_key", FactRental.store_key, DimStore.store_key),
            ("fact_payment.customer_key", FactPayment.customer_key, DimCustomer.customer_key),
            ("fact_payment.store_key", FactPayment.store_key, DimStore.store_key),
        ]
        for label, fact_col, dim_col in orphan_checks:
            orphans = t.scalar(
                select(func.count()).select_from(fact_col.parent.class_)
                .where(fact_col.notin_(select(dim_col))))
            if orphans:
                errors.append(f"Orphan facts in {label}: {orphans} rows with no matching dimension")

    # 7) report
    if errors:
        for e in errors:
            log.error("VALIDATION FAILED: %s", e)
        raise ValueError(f"{len(errors)} validation check(s) failed")
    log.info("Validation passed: rentals=%d payments=%d amount=%.2f (window %s..%s)",
             tgt_rentals, tgt_payments, float(tgt_amount), start, end)
    for store_id in sorted(tgt_by_store):
        cnt, amt = tgt_by_store[store_id]
        log.info("  store %s: payments=%d amount=%.2f", store_id, cnt, amt)