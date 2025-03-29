# src/types.pyi
# -*- coding: utf-8 -*-
# type: ignore[misc]  # Add this if using experimental type features
from pathlib import Path
from pandas import DataFrame

def read_data(_path: str | Path) -> DataFrame: ...
