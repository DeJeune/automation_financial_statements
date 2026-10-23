//! Platform receipt mappings, independent of the recognition provider.
use crate::{Cell, Report, source::number};
use anyhow::{Context, Result, bail, ensure};
use calamine::Reader;
use rust_decimal::{Decimal as D, RoundingStrategy};
use std::{collections::BTreeMap, path::Path};
pub const CATEGORIES: [&str; 8] = [
    "货车帮",
    "滴滴加油",
    "国通1",
    "国通2",
    "团油",
    "POS",
    "超市销售收入",
    "抖音",
];
pub fn fields(category: &str) -> Result<Vec<&'static str>> {
    Ok(match category {
        "货车帮" => vec!["柴油统计", "油站折扣", "油站直降", "服务费", "结算金额"],
        "滴滴加油" => vec!["油品应收金额", "油品预收金额", "油品优惠合计", "油品数量"],
        "国通1" | "国通2" => vec!["订单金额", "退款订单金额", "交易明细金额合计"],
        "团油" => vec![
            "加油升数汇总",
            "加油金额汇总",
            "实际结算金额汇总",
            "通道费汇总",
        ],
        "POS" => vec!["结算总金额"],
        "超市销售收入" => vec!["现金"],
        "抖音" => vec!["用户侧划线价合计", "订单实收合计", "预计收入合计"],
        _ => bail!("不支持的图片类别"),
    })
}
pub fn parse(value: &serde_json::Value) -> Result<D> {
    // A missing recognition must never silently become zero in a financial report.
    let value = match value {
        serde_json::Value::String(s) => s.clone(),
        serde_json::Value::Number(n) => n.to_string(),
        _ => bail!("图片存在未识别字段，请核对原图"),
    };
    let cleaned = value.replace([',', '，', ' '], "");
    let re = regex::Regex::new(r"[-+]?\d*\.?\d+")?;
    let matches: Vec<_> = re.find_iter(&cleaned).collect();
    ensure!(matches.len() == 1, "识别字段没有唯一数值：{value}");
    number(matches[0].as_str())
}
/// Guotong accepts either an order/refund summary or a transaction table total.
/// Partial summaries still fail rather than silently treating a missing refund as zero.
pub fn parse_fields(category: &str, data: &serde_json::Value) -> Result<BTreeMap<&'static str, D>> {
    let fields = fields(category)?;
    let read = |key| parse(&data[key]).with_context(|| format!("{category} / {key}"));
    if matches!(category, "国通1" | "国通2") {
        let amount = if data["订单金额"].is_null() && data["退款订单金额"].is_null() {
            read("交易明细金额合计")?
        } else {
            read("订单金额")? - read("退款订单金额")?
        };
        Ok(BTreeMap::from([("交易明细金额合计", amount)]))
    } else {
        fields
            .into_iter()
            .map(|key| Ok((key, read(key)?)))
            .collect()
    }
}
fn rounded(amount: D) -> D {
    (amount / D::from(3)).round_dp_with_strategy(2, RoundingStrategy::MidpointNearestEven)
}

/// Match the daily report: round each supermarket image before adding them.
pub fn supermarket_total(recognized: &[serde_json::Value]) -> Result<Option<Cell>> {
    if recognized.is_empty() {
        return Ok(None);
    }
    let amount = recognized.iter().try_fold(D::ZERO, |total, data| {
        let values = parse_fields("超市销售收入", data)?;
        Ok::<_, anyhow::Error>(total + rounded(values["现金"]))
    })?;
    Ok(Some(Cell::Number(amount.normalize().to_string())))
}
pub fn apply(
    report: &mut Report,
    template: &Path,
    day: u32,
    gas_price: D,
    recognized: &BTreeMap<String, serde_json::Value>,
) -> Result<()> {
    apply_many(
        report,
        template,
        day,
        gas_price,
        &recognized
            .iter()
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect::<Vec<_>>(),
    )
}
/// Fold each image's already-rounded values, matching the legacy updater.
pub fn apply_many(
    report: &mut Report,
    template: &Path,
    day: u32,
    gas_price: D,
    recognized: &[(String, serde_json::Value)],
) -> Result<()> {
    if recognized.is_empty() {
        return Ok(());
    }
    let mut book = calamine::open_workbook_auto(template)?;
    let range = book.worksheet_range("油品优惠明细 2")?;
    let start = range.start().unwrap_or_default();
    let date_row = range
        .used_cells()
        .find(|(r, c, v)| {
            *r + start.0 as usize >= 1
                && *c + start.1 as usize == 1
                && v.to_string() == day.to_string()
        })
        .map(|(r, _, _)| r + start.0 as usize + 1)
        .context("优惠表找不到日期")?;
    let mut updates = BTreeMap::<(String, String), D>::new();
    for (category, data) in recognized {
        let values = parse_fields(category, data)?;
        let v = |key: &str| values[key];
        let mut first = vec![];
        let mut second = vec![];
        match category.as_str() {
            "货车帮" => {
                first.extend([("E81", v("服务费")), ("C90", v("结算金额"))]);
                second.extend([("AA", v("柴油统计")), ("AB", v("油站折扣") + v("油站直降"))]);
            }
            "滴滴加油" => {
                first.extend([
                    ("E81", v("油品预收金额") - v("油品应收金额")),
                    ("C88", v("油品应收金额")),
                ]);
                second.extend([("P", v("油品数量")), ("Q", v("油品优惠合计"))]);
            }
            "国通1" | "国通2" => first.push((
                if category == "国通1" { "H92" } else { "H93" },
                v("交易明细金额合计"),
            )),
            "团油" => {
                first.extend([("E81", v("通道费汇总")), ("C89", v("实际结算金额汇总"))]);
                second.extend([
                    ("W", v("加油升数汇总")),
                    (
                        "X",
                        v("加油金额汇总") - v("实际结算金额汇总") - v("通道费汇总"),
                    ),
                ]);
            }
            "POS" => first.push(("E80", v("结算总金额"))),
            "超市销售收入" => first.push(("H71", v("现金"))),
            "抖音" => {
                ensure!(gas_price > D::ZERO, "92#油价必须大于零");
                first.extend([
                    ("E81", v("订单实收合计") - v("预计收入合计")),
                    ("C93", v("预计收入合计")),
                ]);
                second.extend([
                    ("AY", v("用户侧划线价合计") / gas_price),
                    ("AZ", v("用户侧划线价合计") - v("订单实收合计")),
                ]);
            }
            _ => unreachable!(),
        }
        for (cell, amount) in first {
            *updates.entry(("调价前".into(), cell.into())).or_default() += rounded(amount);
        }
        for (col, amount) in second {
            *updates
                .entry(("油品优惠明细 2".into(), format!("{col}{date_row}")))
                .or_default() += rounded(amount);
        }
        report
            .notes
            .push(format!("{category}：已识别并按日报规则折算，请核对图片"));
    }
    for ((sheet, address), amount) in updates {
        report
            .updates
            .entry(sheet)
            .or_default()
            .cells
            .insert(address, Cell::Number(amount.normalize().to_string()));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn supermarket_totals_keep_daily_rounding_and_distinguish_missing_from_zero() {
        assert!(supermarket_total(&[]).unwrap().is_none());
        for (data, expected) in [
            (vec![json!({"现金":"587.70元"})], "195.9"),
            (vec![json!({"现金":1}), json!({"现金":1})], "0.66"),
            (
                vec![json!({"现金":"0.015"}), json!({"现金":"0.045"})],
                "0.02",
            ),
            (vec![json!({"现金":0})], "0"),
        ] {
            assert!(
                matches!(supermarket_total(&data).unwrap(), Some(Cell::Number(n)) if n == expected)
            );
        }
        assert!(supermarket_total(&[json!({"现金":null})]).is_err());
    }

    #[test]
    fn guotong_accepts_table_totals_and_preserves_summary_validation() {
        for category in ["国通1", "国通2"] {
            for (data, expected) in [
                (json!({"订单金额":"300元","退款订单金额":"30元"}), "270"),
                (json!({"订单金额":300,"退款订单金额":0}), "300"),
                (
                    json!({"订单金额":null,"退款订单金额":null,"交易明细金额合计":"13,307.06"}),
                    "13307.06",
                ),
                (json!({"交易明细金额合计":0}), "0"),
            ] {
                assert_eq!(
                    parse_fields(category, &data).unwrap()["交易明细金额合计"],
                    number(expected).unwrap()
                );
            }
            for data in [
                json!({}),
                json!({"订单金额":300,"退款订单金额":null}),
                json!({"订单金额":300,"退款订单金额":null,"交易明细金额合计":300}),
                json!({"交易明细金额合计":"无法识别"}),
            ] {
                assert!(parse_fields(category, &data).is_err());
            }
        }
        assert!(parse_fields("POS", &json!({"结算总金额":null})).is_err());
    }
}
