"""Fill the supplied T-CD simple report from station exports."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from src.config.shift_config import ShiftConfig
from src.processors.source_tables import numeric, read_discounts, read_source

SIMPLE_CATEGORIES = ('油品时间统计', '油品优惠', '加油明细', '充值明细')
SIMPLE_REQUIRED_CATEGORIES = ('油品时间统计', '加油明细', '充值明细')
FUEL_ROWS = {'0#柴油': 3, '92#汽油': 4, '95#汽油': 5}


def total(values) -> Decimal:
    return sum((Decimal(str(value)) for value in values), Decimal(0))


def rounded(value: Decimal, places: int = 2) -> float:
    return float(value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def is_simple_report(workbook) -> bool:
    """Recognize the template by content rather than its filename."""
    return (
        {'Sheet1', 'Sheet2'}.issubset(workbook.sheetnames)
        and '数据简表' in str(workbook['Sheet1']['A1'].value)
        and workbook['Sheet1']['A13'].value == '无卡次数'
        and workbook['Sheet2']['A4'].value == '油品'
        and workbook['Sheet2']['A10'].value == '充值明细'
    )


class SimpleReportProcessor:
    """Reproduce the user-verified simple report's field-specific calculations."""

    def __init__(self, config: ShiftConfig, divisor: float = 3, count_divisor: float = 3,
                 closing_balance: str | None = None):
        if not 0 < divisor < float('inf') or not 0 < count_divisor < float('inf'):
            raise ValueError('折算除数必须为有限正数')
        self.config = config
        self.divisor = divisor
        self.count_divisor = count_divisor
        self.money_scale = Decimal(str(divisor))
        self.count_scale = Decimal(str(count_divisor))
        self.closing_balance = None
        if closing_balance is not None and str(closing_balance).strip():
            try:
                balance = Decimal(str(closing_balance).strip())
                if not balance.is_finite():
                    raise InvalidOperation
                self.closing_balance = rounded(balance / self.money_scale)
            except InvalidOperation as error:
                raise ValueError('期末余额合计必须是有效数字') from error

    def build_updates(self, paths: Mapping[str, Path]) -> dict[str, Any]:
        """Validate all sources before returning an idempotent update batch."""
        missing = set(SIMPLE_REQUIRED_CATEGORIES) - paths.keys()
        if missing:
            raise ValueError(f'缺少源表：{"、".join(sorted(missing))}')
        stats = numeric(read_source(paths['油品时间统计'],
            ['机号', '油品', '加油升', '加油元', '次数']), ['机号', '加油升', '加油元', '次数'])
        details = numeric(read_source(paths['加油明细'],
            ['油品', '单价', '升数', '油机金额', '结算金额', '优惠金额', '收款方式']),
            ['单价', '升数', '油机金额', '结算金额', '优惠金额'])
        discounts = read_discounts(paths['油品优惠']) if '油品优惠' in paths else None
        recharge = numeric(read_source(paths['充值明细'],
            ['原余额', '充值金额', '充值赠送', '付款方式']), ['原余额', '充值金额', '充值赠送'])
        self._check_periods(stats, details, recharge)
        self._check_fuels(stats, details, discounts)
        self._reconcile(stats, details, discounts)
        first, second = self._fuel_cells(stats, details)
        if discounts is not None:
            self._discount_cells(discounts, second)
        self._consumption_cells(details, first)
        self._recharge_cells(recharge, first)
        if self.closing_balance is not None:
            first['G7'] = self.closing_balance
        return {
            'updates': [
                {'sheet': 'Sheet1', 'cells': first,
                 'number_formats': {**{f'E{row}': '0' for row in range(3, 7)},
                                    'B8': '0.00', 'B9': '0.00', 'B13': '0',
                                    **({'G7': '0.00'} if self.closing_balance is not None else {})}},
                {'sheet': 'Sheet2', 'cells': second},
            ],
            'processed_data': {
                '折算': f'金额/升数 ÷ {self.divisor:g}；次数 ÷ {self.count_divisor:g}',
                '原始升数': round(float(stats['加油升'].sum()), 2),
                '原始油机金额': round(float(stats['加油元'].sum()), 2),
                '原始次数': int(stats['次数'].sum()),
                '交叉校验': ('逐油品升数、油机金额、次数和优惠一致' if discounts is not None
                         else '逐油品升数、油机金额、次数一致；未提供优惠表，优惠栏保留原值'),
                '消费口径': 'D11=充值卡、电子卡结算金额分别折算取两位后相加；D12=电子卡结算金额；D13=无卡筛选后的结算金额。',
                '充值口径': 'D8/D9=原余额为零/非零的现金、微信、支付宝充值金额含赠送，保留负数；B12=微信/支付宝充值本金。',
                '次数口径': '油品次数、无卡次数折算后取整数；新次数只计原余额为零且有上述付款方式的记录；旧次数计全部明细（含开户、撤单），折算取两位。',
                '余额': ('期末余额合计已折算填入 G7' if self.closing_balance is not None
                       else '未输入截图期末余额合计，G7 保留原值'),
                '待核对': '未说明字段不计算、不覆盖：新会、积分、洗车、超市、充值面额明细及汽柴油充值分类、平台优惠等均保留模板原值。',
            },
        }

    @staticmethod
    def _check_periods(*frames: pd.DataFrame) -> None:
        """Reject exports with conflicting report intervals when headers provide them."""
        periods = {frame.attrs['period'] for frame in frames if 'period' in frame.attrs}
        if len(periods) > 1:
            raise ValueError('源表导出时段不一致，请选择同一时段的数据')
        stations = []
        for frame in frames:
            if '站号' in frame:
                ids = pd.to_numeric(frame['站号'], errors='coerce').dropna()
                if len(ids):
                    stations.append(set(ids))
        if stations and any(ids != stations[0] for ids in stations[1:]):
            raise ValueError('源表站号不一致，请选择同一站点的数据')

    @staticmethod
    def _check_fuels(*frames: pd.DataFrame) -> None:
        """Do not silently discard new or misspelled fuel grades."""
        for frame in frames:
            if frame is None:
                continue
            unknown = set(frame['油品']) - FUEL_ROWS.keys()
            if unknown:
                raise ValueError(f'未支持的油品：{unknown}')

    @staticmethod
    def _reconcile(stats, details, discounts) -> None:
        """Compare independent exports before display rounding."""
        for fuel in FUEL_ROWS:
            s = stats[stats['油品'] == fuel]
            d = details[details['油品'] == fuel]
            checks = [('升数', s['加油升'].sum(), d['升数'].sum()),
                      ('油机金额', s['加油元'].sum(), d['油机金额'].sum()),
                      ('次数', s['次数'].sum(), len(d))]
            if discounts is not None:
                checks.append(('优惠', discounts.loc[discounts['油品'] == fuel, '优惠'].sum(),
                               d['油机金额'].sum() - d['结算金额'].sum()))
            for metric, actual, expected in checks:
                tolerance = 0 if metric == '次数' else 0.011
                if abs(actual - expected) > tolerance:
                    raise ValueError(f'{fuel} {metric}不一致：{actual:.2f} / {expected:.2f}，请核对源表时段和站点')

    def _fuel_cells(self, stats, details) -> tuple[dict, dict]:
        """Restore live averages in both sheets, including zero-sales days."""
        first = {'C2': self.config.date.day}
        second = {}
        for fuel, row in FUEL_ROWS.items():
            source = stats.loc[stats['油品'] == fuel]
            prices = details.loc[details['油品'] == fuel, '单价'].unique()
            if len(prices) > 1:
                raise ValueError(f'{fuel} 存在多个单价，当前简表按固定单价计算，请拆分调价时段')
            price = Decimal(str(prices[0])) if len(prices) else Decimal(0)
            # Round each machine's scaled litres before summing, then apply its fuel price.
            litres = total(rounded(total(group['加油升']) / self.money_scale)
                           for _, group in source.groupby('机号'))
            first.update({
                f'A{row}': fuel,
                f'B{row}': float(litres),
                f'D{row}': rounded(litres * price),
                f'E{row}': rounded(total(source['次数']) / self.count_scale, 0),
                f'C{row}': f'=IF(B6=0,0,B{row}/B6)',
                f'F{row}': f'=IF(E{row}=0,0,D{row}/E{row})',
            })
            second[f'D{row+2}'] = f'=IF(C{row+2}=0,0,B{row+2}/C{row+2})'
        first['F6'] = '=IF(E6=0,0,D6/E6)'
        first['F13'] = '=IF(SUM(D4:D5)=0,0,D13/SUM(D4:D5))'
        return first, second

    def _discount_cells(self, discounts, cells) -> None:
        """Use the discount export's complete reduction, including its coupon component."""
        diesel = total(discounts.loc[discounts['油品'] == '0#柴油', '优惠'])
        gasoline = total(discounts.loc[discounts['油品'].isin(['92#汽油', '95#汽油']), '优惠'])
        cells.update(D31=rounded(gasoline / self.money_scale),
                     D34=rounded(diesel / self.money_scale),
                     G31='=IF(A31=0,0,F31/A31)', G34='=IF(A34=0,0,F34/A34)')

    def _consumption_cells(self, details, cells) -> None:
        """Use settlement amounts for all consumption metrics."""
        card_totals = [rounded(total(details.loc[details['收款方式'] == method,
                                               '结算金额']) / self.money_scale)
                       for method in ('充值卡收款', '电子卡收款')]
        cells['D11'] = float(total(card_totals))
        cells['D12'] = card_totals[1]
        no_card = details.loc[(details['优惠金额'] == 0) & (details['结算金额'] != 0)
                              & details['油品'].isin(['92#汽油', '95#汽油'])]
        cells['B13'] = rounded(Decimal(len(no_card)) / self.count_scale, 0)
        cells['D13'] = rounded(total(no_card['结算金额']) / self.money_scale)
        cells.update(F11='=IF(D6=0,0,D11/D6)', F12='=IF(D6=0,0,D12/D6)')

    def _recharge_cells(self, recharge, first) -> None:
        """Match the verified sample, including signed amounts and recharge gifts."""
        accepted = recharge['付款方式'].isin(['现金收款', '微信收款', '支付宝收款'])
        online = recharge['付款方式'].isin(['微信收款', '支付宝收款'])
        new = recharge.loc[accepted & (recharge['原余额'] == 0)]
        old = recharge.loc[accepted & (recharge['原余额'] != 0)]
        first['B8'] = rounded(Decimal(len(new)) / self.count_scale) if len(new) else None
        # The verified report counts ALL recharge-export records here, including opening/reversals.
        first['B9'] = rounded(Decimal(len(recharge)) / self.count_scale)
        first['D8'] = rounded((total(new['充值金额']) + total(new['充值赠送'])) / self.money_scale) if len(new) else None
        first['D9'] = rounded((total(old['充值金额']) + total(old['充值赠送'])) / self.money_scale)
        first['B12'] = rounded(total(recharge.loc[online, '充值金额']) / self.money_scale)
