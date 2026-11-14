import os
import tempfile
from datetime import datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker


@pytest.fixture(scope="session", autouse=True)
def _env_setup():
    """Redirect the app to sakila_test and a throwaway SQLite file for the whole test session."""
    os.environ["MYSQL_DB"] = "sakila_test"
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    os.environ["SQLITE_PATH"] = tmp.name
    yield
    os.unlink(tmp.name)  # delete the temp SQLite file after all tests


@pytest.fixture()
def fresh_db():
    """Give each test a clean analytics DB (drop + recreate all target tables)."""
    # import AFTER env vars are set, so engines pick up sakila_test / temp sqlite
    from src.config import target_engine
    from src.models_target import TargetBase
    TargetBase.metadata.drop_all(target_engine)
    TargetBase.metadata.create_all(target_engine)
    yield


@pytest.fixture()
def source_session():
    """A session on sakila_test that undoes its writes afterwards, keeping the copy clean."""
    from src.config import source_engine
    Session = sessionmaker(bind=source_engine)
    s = Session()
    undo = []           # callables that revert what the test changed
    yield s, undo
    s.rollback()
    for fn in reversed(undo):
        fn(s)
    s.commit()
    s.close()


# ---------- Test 1: init ----------
def test_init_creates_all_tables(fresh_db):
    from sqlalchemy import inspect

    from src import sync
    from src.config import TargetSession, target_engine
    from src.models_target import DimDate, SyncState, TargetBase

    TargetBase.metadata.drop_all(target_engine)  # start from nothing
    sync.init()

    tables = set(inspect(target_engine).get_table_names())
    expected = {
        "dim_date", "dim_film", "dim_actor", "dim_category", "dim_store", "dim_customer",
        "bridge_film_actor", "bridge_film_category", "fact_rental", "fact_payment", "sync_state",
    }
    assert expected.issubset(tables), f"missing tables: {expected - tables}"

    # dim_date and sync_state were prepared
    with TargetSession() as t:
        assert t.scalar(select(func.count()).select_from(DimDate)) > 0
        assert t.scalar(select(func.count()).select_from(SyncState)) == 15


# ---------- Test 2: full-load ----------
def test_full_load_copies_all_data(fresh_db):
    from src import sync
    from src.config import SourceSession, TargetSession
    from src.models_source import Actor, Film, Payment, Rental
    from src.models_target import DimActor, DimFilm, FactPayment, FactRental

    sync.init()
    sync.full_load()

    pairs = [(Film, DimFilm), (Actor, DimActor), (Rental, FactRental), (Payment, FactPayment)]
    with SourceSession() as s, TargetSession() as t:
        for src_model, tgt_model in pairs:
            src_n = s.scalar(select(func.count()).select_from(src_model))
            tgt_n = t.scalar(select(func.count()).select_from(tgt_model))
            assert src_n == tgt_n, f"{tgt_model.__tablename__}: source={src_n} target={tgt_n}"


# ---------- Test 3: incremental (new data) ----------
def test_incremental_new_data(fresh_db, source_session):
    from src import sync
    from src.config import TargetSession
    from src.models_source import Actor
    from src.models_target import DimActor

    s, undo = source_session
    sync.init()
    sync.full_load()

    # insert a brand-new actor into sakila_test via the ORM
    actor = Actor(first_name="TEST", last_name="NEWACTOR", last_update=datetime.now())
    s.add(actor)
    s.commit()  # incremental reads on a different connection, so commit here
    new_id = actor.actor_id
    undo.append(lambda sess: sess.delete(sess.get(Actor, new_id)))

    sync.incremental()

    with TargetSession() as t:
        found = t.scalar(select(DimActor).where(DimActor.actor_id == new_id))
        assert found is not None, "new actor did not appear in dim_actor"
        assert (found.first_name, found.last_name) == ("TEST", "NEWACTOR")


# ---------- Test 4: incremental (updates: return a rental + change an address) ----------
def test_incremental_updates(fresh_db, source_session):
    from src import sync
    from src.config import TargetSession
    from src.models_source import Address, City, Customer, Rental
    from src.models_target import DimCustomer, FactRental

    s, undo = source_session
    sync.init()
    sync.full_load()

    # (a) return a rental that was not yet returned
    rental = s.scalar(select(Rental).where(Rental.return_date.is_(None)).limit(1))
    rid = rental.rental_id
    undo.append(lambda sess, r=rid: setattr(sess.get(Rental, r), "return_date", None))
    rental.return_date = datetime.now()
    rental.last_update = datetime.now()

    # (b) move customer 1 to a different city (customer.last_update does NOT change)
    customer = s.get(Customer, 1)
    address = s.get(Address, customer.address_id)
    old_city_id = address.city_id
    undo.append(lambda sess, a=address.address_id, c=old_city_id:
                setattr(sess.get(Address, a), "city_id", c))
    new_city = s.scalar(select(City).where(City.city_id != old_city_id).limit(1))
    address.city_id = new_city.city_id
    address.last_update = datetime.now()
    s.commit()

    sync.incremental()

    with TargetSession() as t:
        # (a) rental now has a return date + duration
        fr = t.scalar(select(FactRental).where(FactRental.rental_id == rid))
        assert fr.date_key_returned is not None, "returned rental not updated"
        assert fr.rental_duration_days is not None

        # (b) customer 1's city propagated from the address change
        dc = t.scalar(select(DimCustomer).where(DimCustomer.customer_id == 1))
        assert dc.city == new_city.city, f"address change did not propagate (got {dc.city})"


# ---------- Test 5: validate ----------
def test_validate_pass_and_catch_mismatch(fresh_db):
    from src import sync
    from src.config import TargetSession
    from src.models_target import FactPayment

    sync.init()
    sync.full_load()

    # consistent -> should pass (no exception)
    sync.validate()

    # introduce a deliberate mismatch: delete one payment fact row
    with TargetSession() as t, t.begin():
        row = t.scalar(select(FactPayment).limit(1))
        day = str(row.date_key_paid)  # YYYYMMDD of the row we are about to break
        t.delete(row)

    # counts are only compared inside the window, so validate the day we broke
    iso = f"{day[:4]}-{day[4:6]}-{day[6:]}"
    with pytest.raises(ValueError):
        sync.validate(date_from=iso, date_to=iso)
