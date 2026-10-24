//! Preserve the original per-machine litre calculation across split exports.
use crate::source::{Table, num, text};
use anyhow::{Context, Result, bail};
use chrono::NaiveDateTime;
use rust_decimal::Decimal as D;
use std::collections::{BTreeMap, BTreeSet};

pub struct Group {
    pub fuel: &'static str,
    pub period: usize,
    pub price: D,
    pub machines: BTreeMap<D, D>,
}

impl Group {
    pub fn litres(&self, scale: D) -> D {
        self.machines
            .values()
            .map(|v| crate::report::round(*v / scale, 2))
            .sum()
    }
}

pub fn groups(statistics: &[Table], details: &Table) -> Result<Vec<Group>> {
    for row in statistics.iter().flat_map(|part| &part.rows) {
        if !crate::report::FUELS.contains(&text(row, "油品")) {
            bail!("未支持的油品：{}", text(row, "油品"));
        }
    }
    let mut result = vec![];
    for fuel in crate::report::FUELS {
        let detail: Vec<_> = details
            .rows
            .iter()
            .filter(|r| text(r, "油品") == fuel)
            .collect();
        let prices: BTreeSet<D> = detail
            .iter()
            .map(|r| num(r, "单价"))
            .collect::<Result<_>>()?;
        if prices.len() <= 1 {
            let mut machines = BTreeMap::<D, D>::new();
            for r in statistics
                .iter()
                .flat_map(|part| &part.rows)
                .filter(|r| text(r, "油品") == fuel)
            {
                *machines.entry(num(r, "机号")?).or_default() += num(r, "加油升")?;
            }
            if prices.is_empty() && machines.values().any(|v| !v.is_zero()) {
                bail!("{fuel} 缺少加油明细单价");
            }
            result.push(Group {
                fuel,
                period: 0,
                price: prices.first().copied().unwrap_or_default(),
                machines,
            });
            continue;
        }
        if statistics.len() < 2 {
            bail!("{fuel} 存在多个单价，请提供调价后统计");
        }
        let timed = detail
            .iter()
            .map(|r| {
                let time =
                    NaiveDateTime::parse_from_str(text(r, "加油完成时间"), "%Y-%m-%d %H:%M:%S%.f")
                        .with_context(|| format!("{fuel} 调价计算需要有效的加油完成时间"))?;
                Ok((*r, time))
            })
            .collect::<Result<Vec<_>>>()?;
        for (period, part) in statistics.iter().enumerate() {
            if part.period.len() != 2 || part.period[0] >= part.period[1] {
                bail!("{fuel} 调价计算需要各段统计的完整时段");
            }
            let exclusive_end = statistics
                .iter()
                .any(|other| other.period.len() == 2 && other.period[0] == part.period[1]);
            let selected: Vec<_> = timed
                .iter()
                .filter(|(_, t)| {
                    *t >= part.period[0]
                        && if exclusive_end {
                            *t < part.period[1]
                        } else {
                            *t <= part.period[1]
                        }
                })
                .map(|(r, _)| *r)
                .collect();
            let rows: Vec<_> = part
                .rows
                .iter()
                .filter(|r| text(r, "油品") == fuel)
                .collect();
            let expected: D = rows.iter().map(|r| num(r, "加油升")).sum::<Result<_>>()?;
            let actual: D = selected.iter().map(|r| num(r, "升数")).sum::<Result<_>>()?;
            if (actual - expected).abs() > D::new(11, 3) {
                bail!("{fuel} 调价时段升数不一致");
            }
            let prices: BTreeSet<D> = selected
                .iter()
                .map(|r| num(r, "单价"))
                .collect::<Result<_>>()?;
            if prices.len() > 1 {
                bail!("{fuel} 同一统计时段存在多个单价，请按实际调价时间拆分统计");
            }
            if rows.is_empty() {
                continue;
            }
            let price = prices
                .first()
                .copied()
                .with_context(|| format!("{fuel} 调价时段缺少加油明细单价"))?;
            let mut machines = BTreeMap::<D, D>::new();
            for r in rows {
                *machines.entry(num(r, "机号")?).or_default() += num(r, "加油升")?;
            }
            result.push(Group {
                fuel,
                period,
                price,
                machines,
            });
        }
    }
    Ok(result)
}
