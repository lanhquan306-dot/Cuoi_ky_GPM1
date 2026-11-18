from datetime import date

import pandas as pd
import pytest

from execscreen.config import ROOT, load_config
from execscreen.data.mock import business_days, generate_mock_history
from execscreen.data.storage import Store


@pytest.fixture(scope="session")
def cfg():
    return load_config(ROOT / "config" / "screener.yaml")


@pytest.fixture(scope="session")
def mock_df():
    uni = pd.read_csv(ROOT / "config" / "universe_sample.csv").head(14)
    days = business_days(date(2026, 11, 13), 6)
    return generate_mock_history(uni.symbol.tolist(), dict(zip(uni.symbol, uni.tier)), days, interval_s=60, seed=3)


@pytest.fixture()
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


@pytest.fixture()
def filled_store(store, mock_df):
    store.insert_frame(mock_df)
    return store
