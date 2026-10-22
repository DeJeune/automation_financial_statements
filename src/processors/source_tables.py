"""Read station exports without counting footer totals as transactions."""

from pathlib import Path
from typing import Iterable
import re

import pandas as pd


def read_source(path: Path, required: Iterable[str]) -> pd.DataFrame:
    """Find the header, trim text and remove explicit summary/footer rows."""
    required = set(required)
    raw = (pd.read_csv(path, header=None) if path.suffix.lower() == '.csv'
           else pd.read_excel(path, header=None))
    for index, row in raw.head(10).iterrows():
        labels = row.map(lambda value: str(value).strip() if pd.notna(value) else '')
        if required.issubset(set(labels)):
            if any(list(labels).count(name) != 1 for name in required):
                raise ValueError(f'{path.name}: 表头字段重复')
            frame = raw.iloc[index + 1:].copy()
            frame.columns = labels
            frame = frame.dropna(how='all')
            for column in required:
                frame[column] = frame[column].map(
                    lambda value: value.strip() if isinstance(value, str) else value)
            footer = frame.iloc[:, :4].apply(
                lambda col: col.astype(str).str.strip().str.match(
                    r'^(合计|汇总|总计|小计|记录总数|次数)(?:$|[（(:：])'))
            frame = frame.loc[~footer.any(axis=1)].copy()
            heading = ' '.join(str(value) for value in raw.iloc[:index].values.flatten())
            times = re.findall(r'\d{4}-\d{1,2}-\d{1,2}\s+\d{1,2}:\d{2}:\d{2}', heading)
            if len(times) == 2:
                frame.attrs['period'] = tuple(pd.Timestamp(value) for value in times)
            return frame
    raise ValueError(f'{path.name}: 找不到表头，需要 {"、".join(sorted(required))}')


def numeric(frame: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    """Reject invalid numbers instead of silently understating totals."""
    frame = frame.copy()
    for column in columns:
        values = pd.to_numeric(frame[column], errors='coerce')
        if values.isna().any() or not values.map(lambda x: float('-inf') < x < float('inf')).all():
            raise ValueError(f'{column}: 存在空白或无效数值')
        frame[column] = values
    return frame


def read_discounts(path: Path) -> pd.DataFrame:
    """The grouped XLS export uses blank fuel headings and numeric subtotal labels."""
    frame = read_source(path, ['油品', '优惠'])
    detail = frame['油品'].notna() & pd.to_numeric(frame['油品'], errors='coerce').isna()
    return numeric(frame.loc[detail], ['优惠'])
